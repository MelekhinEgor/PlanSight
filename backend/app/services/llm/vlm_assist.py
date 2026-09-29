"""Опциональный VLM-ассистент — Qwen3-VL через Ollama; никогда не source of truth."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

from app.services.jobs.queue import record_latency
from app.services.llm.claim_validator import verify_claims
from app.services.llm.qwen_explain import sanitize_user_text
from app.services.llm.registry import ollama_base, registry_snapshot, vlm_model
from app.services.product.ru_labels import equipment_list_ru, zone_ru

ALLOWED_KEYS = frozenset(
    {
        "scene_summary",
        "supports_finding",
        "visual_observations",
        "limitations",
        "user_explanation",
    }
)

FORBIDDEN_MUTATIONS = frozenset(
    {
        "schedule_item_id",
        "readiness_pct",
        "create_finding",
        "lifecycle",
        "work_type_override",
        "delay_days",
    }
)


def _template_assist(payload: dict[str, Any]) -> dict[str, Any]:
    code = sanitize_user_text(str(payload.get("finding_code") or ""), max_len=64)
    item = sanitize_user_text(
        str((payload.get("schedule_item") or {}).get("name") or payload.get("activity_name") or ""),
        max_len=200,
    )
    observed = payload.get("observed_equipment") or payload.get("equipment") or []
    missing = payload.get("missing_equipment") or []
    obs = []
    if observed:
        obs.append(f"На кадрах отмечено: {equipment_list_ru(observed)}")
    else:
        obs.append("Визуальные наблюдения ограничены переданными детекциями")
    if missing:
        obs.append(f"Не подтверждено в окне: {equipment_list_ru(missing)}")
    text = (
        f"По работе «{item or '—'}» собрано краткое резюме по уже известным фактам и кадрам. "
        "Это рекомендация для проверки специалистом, а не юридический факт."
    )
    _ = code  # не отдаём системный код пользователю
    return {
        "scene_summary": text,
        "supports_finding": True if observed or missing else None,
        "visual_observations": obs,
        "limitations": list(
            payload.get("limitations")
            or [
                "Разбор без нейросетевого помощника — так стабильнее на небольшом сервере",
                "Отсутствие на кадре не означает отсутствие на площадке",
            ]
        ),
        "user_explanation": text,
    }


def _validate_assist(raw: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    cleaned = {k: raw.get(k) for k in ALLOWED_KEYS}
    smuggled = [k for k in raw.keys() if k in FORBIDDEN_MUTATIONS]
    cleaned["supports_finding"] = (
        bool(cleaned.get("supports_finding")) if cleaned.get("supports_finding") is not None else None
    )
    if not isinstance(cleaned.get("visual_observations"), list):
        cleaned["visual_observations"] = []
    if not isinstance(cleaned.get("limitations"), list):
        cleaned["limitations"] = []
    for key in ("scene_summary", "user_explanation"):
        cleaned[key] = sanitize_user_text(str(cleaned.get(key) or ""), max_len=1200)
    verification = verify_claims(
        f"{cleaned.get('scene_summary')} {cleaned.get('user_explanation')}",
        facts=facts,
    )
    return {
        **cleaned,
        "forbidden_keys_dropped": smuggled,
        "verification": verification,
        "source_of_truth": False,
        "may_mutate_schedule": False,
        "may_create_finding": False,
    }


def _load_frame_images(payload: dict[str, Any], *, limit: int = 4) -> list[str]:
    """Возвращает base64 JPEG/PNG для поля images Ollama."""
    out: list[str] = []
    from app.db import SessionLocal
    from app.db.models import Frame

    frame_ids = payload.get("frame_ids") or []
    for fr in payload.get("frames") or []:
        if isinstance(fr, dict) and fr.get("id") is not None:
            frame_ids.append(fr["id"])
    ids: list[int] = []
    for x in frame_ids:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    ids = ids[:limit]
    if not ids:
        return out
    db = SessionLocal()
    try:
        for fid in ids:
            fr = db.get(Frame, fid)
            if not fr or not fr.file_path:
                continue
            path = Path(fr.file_path)
            if not path.is_file():
                # пробуем под data/frames
                from app.core.config import get_settings

                alt = get_settings().frames_dir() / path.name
                path = alt if alt.is_file() else path
            if not path.is_file():
                continue
            raw = path.read_bytes()
            if len(raw) > 4_000_000:
                continue
            out.append(base64.b64encode(raw).decode("ascii"))
    finally:
        db.close()
    return out


def vlm_assist(payload: dict[str, Any]) -> dict[str, Any]:
    """Возвращает JSON ассистента. Не мутирует БД / findings."""
    from app.services.llm.ai_mode import llm_enabled

    facts = {
        "activity_name": payload.get("activity_name"),
        "finding_code": payload.get("finding_code"),
        "schedule_item_id": (payload.get("schedule_item") or {}).get("id"),
        "observed_equipment": payload.get("observed_equipment") or payload.get("equipment"),
        "limitations": payload.get("limitations"),
        "camera_id": payload.get("camera_id"),
        "zone_id": payload.get("zone_id") or payload.get("visual_zone_id"),
    }
    if not llm_enabled():
        out = _validate_assist(_template_assist(payload), facts)
        out["engine"] = "rules_template_v2"
        out["model"] = None
        out["ai_used"] = False
        out["user_note_ru"] = (
            "Пояснение собрано по правилам и фактам. "
            "Нейросетевой помощник на этом сервере отключён (экономия ресурсов)."
        )
        return out

    snap = registry_snapshot()
    base = ollama_base()
    tags = snap.get("available_tags") or []
    model = vlm_model(tags)
    vlm_ok = bool(snap.get("ollama_reachable") and (snap.get("models") or {}).get("vlm", {}).get("present"))

    if not base or not vlm_ok:
        out = _validate_assist(_template_assist(payload), facts)
        out["engine"] = "vlm_template_fallback"
        out["model"] = model
        out["ai_used"] = False
        out["user_note_ru"] = (
            "Мультимодальный помощник сейчас недоступен. Показано краткое резюме по уже известным фактам."
        )
        return out

    safe = {
        "работа": sanitize_user_text(
            str((payload.get("schedule_item") or {}).get("name") or payload.get("activity_name") or "")
        ),
        "зона": zone_ru(str(payload.get("zone_id") or payload.get("visual_zone_id") or "")),
        "наблюдаемая_техника": equipment_list_ru(payload.get("observed_equipment") or []),
        "не_подтверждено": equipment_list_ru(payload.get("missing_equipment") or []),
        "ограничения": payload.get("limitations") or [],
        "число_кадров": len(payload.get("frame_ids") or payload.get("frames") or []),
    }
    images = _load_frame_images(payload, limit=4)
    system = (
        "Ты помощник PlanSight по строительной площадке. Отвечай по-русски. "
        "Ты НЕ источник истины: нельзя менять строку графика, процент готовности, "
        "создавать предупреждения. Верни ТОЛЬКО JSON с ключами: "
        "scene_summary, supports_finding, visual_observations, limitations, user_explanation. "
        "visual_observations — массив коротких фраз на русском."
    )
    user_content = (
        "Опиши сцену и согласованность с фактами. Не выдумывай проценты и GPS.\n"
        + json.dumps(safe, ensure_ascii=False)
    )
    message: dict[str, Any] = {"role": "user", "content": user_content}
    if images:
        message["images"] = images
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            message,
        ],
    }
    try:
        import httpx

        t0 = time.perf_counter()
        r = httpx.post(f"{base}/api/chat", json=body, timeout=90.0)
        record_latency("llm", (time.perf_counter() - t0) * 1000)
        r.raise_for_status()
        content = ((r.json().get("message") or {}).get("content") or "").strip()
        start, end = content.find("{"), content.rfind("}")
        raw = json.loads(content[start : end + 1]) if start >= 0 and end > start else _template_assist(payload)
        out = _validate_assist(raw if isinstance(raw, dict) else _template_assist(payload), facts)
        out["engine"] = "vlm_ollama"
        out["model"] = model
        out["images_sent"] = len(images)
        out["ai_used"] = True
        out["user_note_ru"] = "Пояснение помощника по кадрам. Итог подтверждает специалист."
        return out
    except Exception as exc:  # noqa: BLE001
        out = _validate_assist(_template_assist(payload), facts)
        out["engine"] = "vlm_error_fallback"
        out["model"] = model
        out["error"] = str(exc)[:200]
        out["ai_used"] = False
        out["user_note_ru"] = "Не удалось получить ответ помощника. Показано шаблонное резюме."
        return out
