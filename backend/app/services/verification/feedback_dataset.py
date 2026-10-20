"""P2-ML-01 — экспорт примеров HumanVerdict для будущего обучения ActivityNet / CatBoost.

ACK / ack_for_review исключены (не ML-метки).
Production engine никогда не подменяется автоматически из этого датасета.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ActivityHypothesis,
    Camera,
    Detection,
    Deviation,
    Frame,
    HumanVerdict,
    ScheduleItem,
    ScheduleMatch,
)
from app.services.verification.service import is_ml_label


DATASET_SCHEMA = [
    "verdict_id",
    "camera_id",
    "zone_id",
    "time_window",
    "frame_ids",
    "equipment_counts",
    "schedule_context",
    "heuristic_features",
    "predicted_work_type",
    "ground_truth_work_type",
    "verified_schedule_item_id",
    "verdict",
]


def _equip_counts(db: Session, frame_ids: list[int]) -> dict[str, Any]:
    if not frame_ids:
        return {"counts": {}, "confidences": {}}
    from app.db.models import InferenceRun

    run_ids = [
        r.id
        for r in db.query(InferenceRun).filter(InferenceRun.frame_id.in_(frame_ids)).all()
    ]
    if not run_ids:
        return {"counts": {}, "confidences": {}}
    rows = db.query(Detection).filter(Detection.inference_run_id.in_(run_ids)).all()
    counts: dict[str, int] = {}
    confs: dict[str, list[float]] = {}
    for d in rows:
        cls = d.equipment_code or d.raw_class_name or "unknown"
        counts[cls] = counts.get(cls, 0) + 1
        confs.setdefault(cls, []).append(float(d.confidence or 0))
    return {
        "counts": counts,
        "confidences": {k: round(sum(v) / len(v), 4) for k, v in confs.items() if v},
    }


def build_feedback_dataset(db: Session, *, project_id: int | None = None, limit: int = 500) -> dict[str, Any]:
    q = db.query(HumanVerdict).order_by(HumanVerdict.id.desc())
    rows = q.limit(limit * 3).all()  # oversample then filter
    examples: list[dict[str, Any]] = []
    skipped_ack = 0
    for hv in rows:
        if not is_ml_label(hv.verdict):
            skipped_ack += 1
            continue
        try:
            corr = json.loads(hv.correction_json or "{}")
        except Exception:
            corr = {}
        if corr.get("is_ml_label") is False:
            skipped_ack += 1
            continue

        frame_ids: list[int] = []
        camera_id = None
        zone_id = None
        schedule_item_id = corr.get("schedule_item_id")
        predicted_wt = corr.get("predicted_work_type")
        gt_wt = corr.get("ground_truth_work_type") or corr.get("work_type_code") or corr.get("work_type")
        schedule_ctx: dict[str, Any] = {}
        heuristic: dict[str, Any] = {}
        time_window = None

        if hv.target_type == "deviation":
            d = db.get(Deviation, hv.target_id)
            if not d:
                continue
            if project_id is not None and d.project_id != project_id:
                continue
            try:
                details = json.loads(d.details_json or "{}")
            except Exception:
                details = {}
            try:
                frame_ids = [int(x) for x in json.loads(d.evidence_ids_json or "[]")]
            except Exception:
                frame_ids = list(details.get("evidence_frame_ids") or [])
            zone_id = details.get("camera_visual_zone_id") or details.get("visual_zone_id") or details.get("zone_key")
            schedule_item_id = schedule_item_id or d.schedule_item_id
            heuristic = {
                "code": d.code,
                "risk_score": d.heuristic_score if d.heuristic_score is not None else d.risk_score,
                "signal_kind": details.get("signal_kind"),
            }
            if d.schedule_item_id:
                item = db.get(ScheduleItem, d.schedule_item_id)
                if item:
                    schedule_ctx = {
                        "id": item.id,
                        "name": item.raw_name,
                        "building": item.building,
                        "work_type_id": item.work_type_id,
                    }
                    predicted_wt = predicted_wt or item.canonical_work_code
            if frame_ids:
                fr = db.get(Frame, frame_ids[0])
                if fr:
                    camera_id = fr.camera_id
                    time_window = {
                        "start": fr.captured_at.isoformat() if fr.captured_at else None,
                        "end": None,
                    }

        elif hv.target_type == "hypothesis":
            hyp = db.get(ActivityHypothesis, hv.target_id)
            if not hyp:
                continue
            cam = db.get(Camera, hyp.camera_id) if hyp.camera_id else None
            if project_id is not None and cam and cam.project_id != project_id:
                continue
            camera_id = hyp.camera_id
            predicted_wt = predicted_wt or hyp.work_type_code
            top = (
                db.query(ScheduleMatch)
                .filter(ScheduleMatch.hypothesis_id == hyp.id)
                .order_by(ScheduleMatch.rank.asc())
                .first()
            )
            if top:
                schedule_item_id = schedule_item_id or top.schedule_item_id
            heuristic = {"ui_status": hyp.ui_status, "score_kind": hyp.score_kind, "score": hyp.score}

        examples.append(
            {
                "verdict_id": hv.id,
                "target_type": hv.target_type,
                "target_id": hv.target_id,
                "camera_id": camera_id,
                "zone_id": zone_id,
                "time_window": time_window,
                "frame_ids": frame_ids,
                "equipment_counts": _equip_counts(db, frame_ids),
                "schedule_context": schedule_ctx,
                "heuristic_features": heuristic,
                "predicted_work_type": predicted_wt,
                "ground_truth_work_type": gt_wt,
                "verified_schedule_item_id": schedule_item_id,
                "verdict": hv.verdict,
                "user_id": hv.user_id,
                "created_at": hv.created_at.isoformat() if hv.created_at else None,
                "correction": {k: v for k, v in corr.items() if k != "is_ml_label"},
            }
        )
        if len(examples) >= limit:
            break

    return {
        "schema": DATASET_SCHEMA,
        "count": len(examples),
        "skipped_non_ml": skipped_ack,
        "examples": examples,
        "note": "For challenger training only — never auto-deploy to production engine",
        "production_engine": "heuristic_v2",
        "auto_replace_forbidden": True,
    }
