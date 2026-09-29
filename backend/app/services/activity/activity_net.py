"""Статус ActivityNet и каркас признаков (Stage 5).

Прод-скоринг остаётся heuristic_v2, пока не утверждена обученная модель.
Модуль никогда не подменяет движок молча.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.paths import REPO_ROOT

REGISTRY = REPO_ROOT / "models" / "registry" / "activity_net_v0.json"


def activity_net_status() -> dict[str, Any]:
    artifact = None
    if REGISTRY.exists():
        artifact = str(REGISTRY.relative_to(REPO_ROOT)).replace("\\", "/")
    return {
        "model_id": "activity_net_v0",
        "status": "NOT_TRAINED",
        "production_engine": "heuristic_v2",
        "swapped_into_production": False,
        "artifact": artifact,
        "note": (
            "CatBoost/multi-label ActivityNet не обучен. "
            "В проде только heuristic_v2 (uncalibrated_score). "
            "Expert feedback → кандидаты в dataset, не автоподмена модели."
        ),
        "required_before_train": [
            "object/camera/date grouped splits",
            "zone-time window features",
            "ground-truth multi-label work types",
            "calibration separate from ranking",
        ],
    }


def build_window_features(
    *,
    equipment_counts: dict[str, float] | None = None,
    equipment_conf_mean: dict[str, float] | None = None,
    episode_duration_sec: float | None = None,
    spatial_coverage: float | None = None,
    frame_quality: float | None = None,
    matched_schedule_item_id: str | None = None,
) -> dict[str, Any]:
    """Вектор признаков в форме экспорта для будущего обучения — не скорит."""
    return {
        "schema": "activity_net_features_v0",
        "equipment_counts": dict(equipment_counts or {}),
        "equipment_conf_mean": dict(equipment_conf_mean or {}),
        "episode_duration_sec": episode_duration_sec,
        "spatial_coverage": spatial_coverage,
        "frame_quality": frame_quality,
        "matched_schedule_item_id": matched_schedule_item_id,
        "label": None,
        "note": "feature scaffold only — not a model inference",
    }


def ensure_registry_stub() -> Path:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY.exists():
        import json

        REGISTRY.write_text(
            __import__("json").dumps(activity_net_status(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return REGISTRY
