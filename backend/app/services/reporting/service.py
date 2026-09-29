from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import (
    ActivityHypothesis,
    Camera,
    DailySummary,
    Detection,
    Deviation,
    Evidence,
    Frame,
    InferenceRun,
    ModelVersion,
    Observation,
    ScheduleItem,
    ScheduleMatch,
    StateEvent,
    WorkType,
)
from app.services.deviations.service import build_daily_summary
from app.services.schedule.service import list_schedule_items
from app.core.config import get_settings


def get_project_dashboard(db: Session, project_id: int) -> dict:
    items = list_schedule_items(db, project_id)
    cameras = db.query(Camera).filter(Camera.project_id == project_id).all()
    frames = db.query(Frame).filter(Frame.project_id == project_id).count()
    deviations = (
        db.query(Deviation)
        .filter(Deviation.project_id == project_id, Deviation.status == "open")
        .count()
    )
    return {
        "project_id": project_id,
        "schedule_items": len(items),
        "cameras": len(cameras),
        "frames": frames,
        "open_deviations": deviations,
    }


def serialize_hypothesis(db: Session, h: ActivityHypothesis) -> dict:
    wt = db.get(WorkType, h.work_type_id)
    matches = (
        db.query(ScheduleMatch)
        .filter(ScheduleMatch.hypothesis_id == h.id)
        .order_by(ScheduleMatch.rank.asc())
        .all()
    )
    return {
        "id": h.id,
        "work_type": wt.code if wt else None,
        "work_type_name": wt.name if wt else None,
        "camera_id": h.camera_id,
        "episode_id": h.episode_id,
        "interval_start": h.interval_start.isoformat() if h.interval_start else None,
        "interval_end": h.interval_end.isoformat() if h.interval_end else None,
        "activity_score": h.activity_score,
        "score_kind": h.score_kind,
        "state_distribution": json.loads(h.state_distribution_json or "{}"),
        "ui_status": h.ui_status,
        "explanation": json.loads(h.explanation_json or "{}"),
        "matches": [
            {
                "id": m.id,
                "schedule_item_id": m.schedule_item_id,
                "score": m.score,
                "score_kind": m.score_kind,
                "rank": m.rank,
                "reason_codes": json.loads(m.reason_codes_json or "[]"),
                "is_unmatched": m.is_unmatched,
            }
            for m in matches
        ],
    }


def list_activities(db: Session, project_id: int, date_from: datetime | None, date_to: datetime | None) -> list[dict]:
    q = (
        db.query(ActivityHypothesis)
        .join(Camera, Camera.id == ActivityHypothesis.camera_id)
        .filter(Camera.project_id == project_id)
    )
    if date_from:
        q = q.filter(ActivityHypothesis.interval_start >= date_from)
    if date_to:
        q = q.filter(ActivityHypothesis.interval_end <= date_to)
    rows = q.order_by(ActivityHypothesis.activity_score.desc(), ActivityHypothesis.interval_start.desc()).limit(200).all()
    return [serialize_hypothesis(db, h) for h in rows]


def list_matches(db: Session, project_id: int, date_from: datetime | None, date_to: datetime | None) -> list[dict]:
    activities = list_activities(db, project_id, date_from, date_to)
    out = []
    for a in activities:
        for m in a["matches"]:
            item = db.get(ScheduleItem, m["schedule_item_id"]) if m["schedule_item_id"] else None
            out.append(
                {
                    **m,
                    "hypothesis_id": a["id"],
                    "work_type": a["work_type"],
                    "schedule_item_name": item.raw_name if item else "UNMATCHED",
                    "building": item.building if item else None,
                }
            )
    return out


def get_work_evidence(db: Session, hypothesis_id: int) -> dict:
    hyp = db.get(ActivityHypothesis, hypothesis_id)
    if hyp is None:
        raise ValueError("hypothesis not found")
    evidence = db.query(Evidence).filter(Evidence.hypothesis_id == hypothesis_id).all()
    run = db.get(InferenceRun, hyp.inference_run_id)
    model = db.get(ModelVersion, run.model_version_id) if run else None
    frame = db.get(Frame, run.frame_id) if run else None
    obs = db.query(Observation).filter(Observation.inference_run_id == run.id).one_or_none() if run else None
    detections = db.query(Detection).filter(Detection.inference_run_id == run.id).all() if run else []
    events = db.query(StateEvent).filter(StateEvent.hypothesis_id == hypothesis_id).all()
    explanation = json.loads(hyp.explanation_json or "{}")
    overlay = explanation.get("overlay_path")
    return {
        "hypothesis": serialize_hypothesis(db, hyp),
        "frame": {
            "id": frame.id if frame else None,
            "captured_at": frame.captured_at.isoformat() if frame and frame.captured_at else None,
            "file_path": frame.file_path if frame else None,
            "image_url": f"/api/frames/{frame.id}/image" if frame else None,
            "overlay_url": f"/api/frames/{frame.id}/overlay?run_id={run.id}" if frame and run else None,
            "sha256": frame.sha256 if frame else None,
            "quality": frame.image_quality if frame else None,
        },
        "inference_run": {
            "id": run.id if run else None,
            "status": run.status if run else None,
            "kb_version": run.kb_version if run else None,
            "engine_version": run.engine_version if run else None,
            "model": {
                "id": model.id if model else None,
                "name": model.name if model else None,
                "weights_sha256": model.weights_sha256 if model else None,
                "weights_path": model.weights_path if model else None,
            },
        },
        "observation": {
            "equipment_vector": json.loads(obs.equipment_vector_json or "{}") if obs else {},
            "observability": obs.observability if obs else None,
            "episode_id": obs.episode_id if obs else None,
        },
        "detections": [
            {
                "id": d.id,
                "equipment_code": d.equipment_code,
                "raw_class_name": d.raw_class_name,
                "confidence": d.confidence,
                "bbox_norm": json.loads(d.bbox_norm_json),
            }
            for d in detections
        ],
        "evidence": [
            {
                "id": e.id,
                "kind": e.kind,
                "weight": e.weight,
                "payload": json.loads(e.payload_json or "{}"),
                "frame_id": e.frame_id,
                "detection_id": e.detection_id,
            }
            for e in evidence
        ],
        "events": [
            {
                "id": ev.id,
                "event_type": ev.event_type,
                "event_at": ev.event_at.isoformat(),
                "status": ev.status,
                "source": ev.source,
                "details": json.loads(ev.details_json or "{}"),
            }
            for ev in events
        ],
        "chain": [
            "Кадр (фото + время съёмки)",
            "Прогон анализа (версии весов CV, базы знаний, КСГ)",
            "Детекции техники (неизменяемые)",
            "Наблюдение / эпизод",
            "Гипотеза вида работ (оценка модели, multi-label)",
            "Сопоставление со строкой КСГ (+ «не сопоставлено»)",
            "Событие состояния / отклонение",
        ],
    }


def ensure_daily_summary(db: Session, project_id: int, day: str) -> DailySummary:
    payload = build_daily_summary(db, project_id, day)
    existing = (
        db.query(DailySummary)
        .filter(DailySummary.project_id == project_id, DailySummary.date == day)
        .one_or_none()
    )
    version = str(get_settings().get("engine", "version", "plansight-engine-v1"))
    if existing:
        existing.payload_json = json.dumps(payload, ensure_ascii=False)
        existing.generated_at = datetime.utcnow()
        existing.run_version = version
        db.flush()
        return existing
    row = DailySummary(
        project_id=project_id,
        date=day,
        payload_json=json.dumps(payload, ensure_ascii=False),
        run_version=version,
    )
    db.add(row)
    db.flush()
    return row
