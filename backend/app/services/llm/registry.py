"""Единый AI/ML registry — template-first для малых Docker-хостов."""

from __future__ import annotations

import os
from typing import Any

from app.services.llm.ai_mode import ai_mode, ai_user_note_ru, llm_enabled


def ollama_base() -> str | None:
    if not llm_enabled():
        return None
    for key in ("PLANSIGHT_OLLAMA_URL", "OLLAMA_BASE_URL", "OLLAMA_HOST"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v.rstrip("/")
    return "http://127.0.0.1:11434"


def _pick_model(tags: list[str], preferred: list[str], fallback: str) -> str:
    for pref in preferred:
        for t in tags:
            if t == pref or t.startswith(pref + "-") or t.startswith(pref + ":") or pref in t:
                return t
    return preferred[0] if preferred else fallback


def text_llm_model(tags: list[str] | None = None) -> str:
    env = (
        os.environ.get("PLANSIGHT_QWEN_MODEL")
        or os.environ.get("OLLAMA_MODEL")
        or os.environ.get("PLANSIGHT_OLLAMA_MODEL")
        or ""
    ).strip()
    if env:
        return env
    return _pick_model(
        tags or [],
        ["qwen3.5:9b", "qwen2.5:7b", "qwen2.5", "qwen"],
        "qwen2.5:7b",
    )


def vlm_model(tags: list[str] | None = None) -> str:
    env = (os.environ.get("PLANSIGHT_VLM_MODEL") or os.environ.get("QWEN_VLM_MODEL") or "").strip()
    if env:
        return env
    return _pick_model(
        tags or [],
        ["qwen3-vl:8b", "qwen3-vl:4b", "qwen3-vl:2b", "qwen3-vl", "llava"],
        "qwen3-vl:4b",
    )


def registry_snapshot() -> dict[str, Any]:
    mode = ai_mode()
    enabled = llm_enabled()
    base = ollama_base()
    reachable = False
    tags: list[str] = []
    probe_error: str | None = None

    if enabled and base:
        try:
            import httpx

            r = httpx.get(f"{base}/api/tags", timeout=1.5)
            r.raise_for_status()
            tags = [m.get("name") or "" for m in (r.json().get("models") or [])]
            reachable = True
        except Exception as exc:  # noqa: BLE001
            probe_error = str(exc)[:200]

    text_model = text_llm_model(tags) if enabled else None
    vlm = vlm_model(tags) if enabled else None
    text_present = bool(enabled and tags and any(text_model and (t == text_model or text_model in t) for t in tags))
    vlm_present = bool(
        enabled
        and tags
        and any("qwen3-vl" in t or "qwen2-vl" in t or (vlm and vlm in t) for t in tags)
    )

    return {
        "ai_mode": mode,
        "llm_enabled": enabled,
        "ollama_configured": bool(enabled and base),
        "ollama_reachable": reachable if enabled else False,
        "ollama_base": base if enabled else None,
        "probe_error": probe_error if enabled else None,
        "available_tags": tags[:40] if enabled else [],
        "models": {
            "rules_engine": {
                "id": "rules_v1",
                "role": "finding_explanation",
                "status": "CONNECTED",
                "source_of_truth": True,
                "user_label": "Правила и кадры (основной разбор)",
            },
            "text_llm": {
                "id": text_model,
                "role": "canonical_match_and_explain",
                "status": "DISABLED" if not enabled else ("CONNECTED" if text_present else "OFFLINE"),
                "present": text_present,
                "source_of_truth": False,
                "user_label": "Языковая модель (отключена на этом сервере)"
                if not enabled
                else "Языковая модель для сопоставления видов работ",
            },
            "vlm": {
                "id": vlm,
                "role": "optional_multimodal_assistant",
                "status": "DISABLED" if not enabled else ("CONNECTED" if vlm_present else "OPTIONAL"),
                "present": vlm_present,
                "source_of_truth": False,
                "user_label": "Мультимодальный помощник по кадрам (отключён)"
                if not enabled
                else "Мультимодальный помощник по кадрам",
            },
            "yolo": {
                "id": "yolo11s_combined_v1_best",
                "role": "equipment_detection",
                "status": "CONNECTED",
                "source_of_truth": True,
                "user_label": "Детекция техники на кадрах",
            },
            "activity": {
                "id": "heuristic_v2",
                "role": "activity_hypothesis",
                "status": "CONNECTED_HEURISTIC",
                "activitynet": "DATASET_READY_NOT_TRAINED",
                "source_of_truth": True,
                "user_label": "Оценка активности (эвристика)",
            },
        },
        "presentation": {
            "connected": ["Правила и кадры", "Детекция техники", "Эвристика активности"],
            "disabled_on_this_host": ["Языковая модель", "Мультимодальный помощник"]
            if not enabled
            else [],
            "optional": [] if not enabled else ["Языковая модель через Ollama", "Qwen3-VL"],
            "planned_training": ["Обучение ActivityNet по вердиктам специалистов"],
        },
        "endpoints": [
            "GET /api/ai/status",
            "POST /api/ai/canonical-match",
            "POST /api/ai/explain",
            "POST /api/ai/vlm-assist",
            "GET /api/ai/feedback-dataset",
        ],
        "browser_ollama": False,
        # FE shows «Пояснить по кадрам» only when LLM mode is on
        "vlm_ui_enabled": bool(enabled),
        "setup_hint_ru": ai_user_note_ru(),
        "note": ai_user_note_ru(),
        "host_profile": {
            "recommended_ram_gb": 2,
            "ai_default": "template",
            "comment_ru": "На 2 ядрах / 2 ГБ ИИ-модели не запускаются — только правила и YOLO.",
        },
    }
