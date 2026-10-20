"""Серверный канонический матчинг работ (вместо browser → Ollama)."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from app.services.jobs.queue import record_latency
from app.services.llm.qwen_explain import sanitize_user_text
from app.services.llm.registry import ollama_base


def _norm(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[«»\"]", "", t)
    t = re.sub(r"[^a-zа-я0-9%]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _score(query: str, name: str, code: str = "", aliases: list[str] | None = None) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    n = _norm(name)
    if not n:
        return 0.0
    if q == n:
        return 1.0
    score = 0.0
    if n in q or q in n:
        score = max(score, 0.82)
    q_toks = set(q.split())
    n_toks = set(n.split())
    if q_toks and n_toks:
        inter = len(q_toks & n_toks) / max(1, len(q_toks | n_toks))
        score = max(score, inter)
    for a in aliases or []:
        an = _norm(a)
        if an and (an == q or an in q or q in an):
            score = max(score, 0.88)
    if code and _norm(code) in q:
        score = max(score, 0.55)
    return min(1.0, score)


def shortlist(source_name: str, catalog: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    scored = []
    for c in catalog:
        s = _score(
            source_name,
            str(c.get("name") or ""),
            str(c.get("code") or ""),
            list(c.get("aliases") or []),
        )
        if s <= 0:
            continue
        scored.append({**c, "score": round(s, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def heuristic_match(activity_id: str, source_name: str, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    cands = shortlist(source_name, catalog, limit=5)
    top = cands[0] if cands else None
    score = float(top["score"]) if top else 0.0
    if top and score >= 0.85:
        status = "MATCHED"
        needs = score < 0.9
    elif top and score >= 0.55:
        status = "AMBIGUOUS"
        needs = True
    else:
        status = "UNMAPPED"
        needs = True
        top = None
    return {
        "activity_id": activity_id,
        "source_name": source_name,
        "canonical_work_id": (top or {}).get("id"),
        "canonical_work_code": (top or {}).get("code"),
        "canonical_work_name": (top or {}).get("name"),
        "mapping_status": status,
        "needs_confirmation": needs,
        "candidates": cands,
        "score": score,
        "source": "heuristic",
    }


def _ollama_pick(source_name: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    from app.services.llm.registry import ollama_base, registry_snapshot, text_llm_model

    snap = registry_snapshot()
    base = ollama_base()
    if not base or not snap.get("ollama_reachable"):
        return None
    model = text_llm_model(snap.get("available_tags") or [])
    safe_name = sanitize_user_text(source_name, max_len=300)
    lines = []
    for i, c in enumerate(candidates[:12], 1):
        lines.append(f"{i}. id={c.get('id')} | {c.get('code')} | {c.get('name')}")
    prompt = (
        "Ты сопоставляешь название работы из КСГ со справочником CanonicalWork.\n"
        "Выбери ОДИН id из списка либо null.\n"
        f"Название: «{safe_name}»\nКандидаты:\n" + "\n".join(lines) + "\n"
        'Ответь ТОЛЬКО JSON: {"id":"...|null","confidence":0.0-1.0,"reason":"..."}'
    )
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 120},
        "messages": [
            {"role": "system", "content": "Ты классификатор строительных видов работ. Только JSON."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        import httpx

        t0 = time.perf_counter()
        r = httpx.post(f"{base}/api/chat", json=body, timeout=60.0)
        record_latency("llm", (time.perf_counter() - t0) * 1000)
        r.raise_for_status()
        content = ((r.json().get("message") or {}).get("content") or "").strip()
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return None
        obj = json.loads(content[start : end + 1])
        cid = obj.get("id")
        if cid in (None, "", "null"):
            cid = None
        else:
            cid = str(cid)
        conf = float(obj.get("confidence") or 0)
        return {"id": cid, "confidence": max(0.0, min(1.0, conf)), "reason": obj.get("reason"), "model": model}
    except Exception:
        return None


def match_activities(
    activities: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    from app.services.llm.ai_mode import llm_enabled

    base_rows = [
        heuristic_match(str(a.get("id") or ""), str(a.get("name") or ""), catalog)
        for a in activities
        if str(a.get("name") or "").strip()
    ]
    llm_used = 0
    detail = "Сопоставление по названиям (режим без языковой модели)"
    if use_llm and llm_enabled() and ollama_base():
        detail = None
        # Уникальные слабые имена
        need: dict[str, list[dict[str, Any]]] = {}
        for m in base_rows:
            weak = m["mapping_status"] != "MATCHED" or m["needs_confirmation"] or float(m.get("score") or 0) < 0.85
            if not weak:
                continue
            key = _norm(m["source_name"])
            need.setdefault(key, []).append(m)
        picks: dict[str, dict[str, Any]] = {}
        for key, group in need.items():
            sample = group[0]
            cands = sample["candidates"] if len(sample["candidates"]) >= 3 else shortlist(sample["source_name"], catalog, limit=12)
            pick = _ollama_pick(sample["source_name"], cands)
            if pick:
                picks[key] = {"pick": pick, "candidates": cands}
        by_id = {str(c.get("id")): c for c in catalog if c.get("id") is not None}
        for m in base_rows:
            key = _norm(m["source_name"])
            hit = picks.get(key)
            if not hit:
                continue
            pick = hit["pick"]
            llm_used += 1
            if not pick.get("id"):
                m["canonical_work_id"] = None
                m["canonical_work_code"] = None
                m["canonical_work_name"] = None
                m["mapping_status"] = "UNMAPPED"
                m["needs_confirmation"] = True
                m["source"] = "llm"
                continue
            item = by_id.get(str(pick["id"])) or next((c for c in hit["candidates"] if str(c.get("id")) == str(pick["id"])), None)
            if not item:
                continue
            conf = float(pick.get("confidence") or 0)
            m["canonical_work_id"] = item.get("id")
            m["canonical_work_code"] = item.get("code")
            m["canonical_work_name"] = item.get("name")
            m["mapping_status"] = "MATCHED" if conf >= 0.75 else "AMBIGUOUS"
            m["needs_confirmation"] = conf < 0.9
            m["score"] = conf
            m["source"] = "llm"
            m["candidates"] = hit["candidates"][:5]
        detail = f"Сопоставление уточнено автоматически ({llm_used})" if llm_used else "Сопоставление по названиям"

    return {
        "matches": base_rows,
        "used_llm": llm_used > 0,
        "llm_count": llm_used,
        "detail": detail,
        "model": None,
        "engine": "backend_canonical_match",
        "ai_mode": "ollama" if llm_enabled() else "template",
    }
