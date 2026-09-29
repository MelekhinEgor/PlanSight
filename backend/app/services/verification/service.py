from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import ActivityHypothesis, HumanVerdict, ScheduleMatch


# Подтверждение lifecycle ack — НЕ ML-метка; в обучение идут только confirm/reject/correct.
ML_VERDICTS = frozenset({"confirm", "confirmed", "accept", "reject", "rejected", "correct", "ambiguous"})
ACK_VERDICTS = frozenset({"ack_for_review", "acknowledged", "ack"})


def is_ml_label(verdict: str) -> bool:
    v = (verdict or "").lower().strip()
    return v in ML_VERDICTS and v not in ACK_VERDICTS


def submit_verdict(
    db: Session,
    *,
    target_type: str,
    target_id: int,
    verdict: str,
    correction: dict | None = None,
    user_id: str = "operator",
) -> HumanVerdict:
    from app.db.models import Deviation

    v_norm = (verdict or "").lower().strip()
    row = HumanVerdict(
        target_type=target_type,
        target_id=target_id,
        verdict=v_norm,
        correction_json=json.dumps(
            {**(correction or {}), "is_ml_label": is_ml_label(v_norm)},
            ensure_ascii=False,
        ),
        user_id=user_id,
        created_at=datetime.utcnow(),
    )
    db.add(row)

    if target_type == "hypothesis":
        hyp = db.get(ActivityHypothesis, target_id)
        if hyp is not None:
            if v_norm in ("confirm", "confirmed", "accept"):
                hyp.ui_status = "CONFIRMED"
                hyp.score_kind = "human_confirmed"
            elif v_norm in ("reject", "rejected"):
                hyp.ui_status = "REJECTED"
            elif v_norm == "ambiguous":
                hyp.ui_status = "NEEDS_REVIEW"
            corr = correction or {}
            if "schedule_item_id" in corr:
                # ручной bind: insert/update top match без изменения сырых inference-скоров
                existing = (
                    db.query(ScheduleMatch)
                    .filter(ScheduleMatch.hypothesis_id == hyp.id, ScheduleMatch.rank == 1)
                    .first()
                )
                if existing:
                    existing.schedule_item_id = int(corr["schedule_item_id"])
                    existing.is_unmatched = False
                    existing.reason_codes_json = json.dumps(["HUMAN_OVERRIDE"])
                    existing.score_kind = "human_confirmed"
                else:
                    db.add(
                        ScheduleMatch(
                            hypothesis_id=hyp.id,
                            schedule_item_id=int(corr["schedule_item_id"]),
                            score=1.0,
                            score_kind="human_confirmed",
                            rank=1,
                            reason_codes_json=json.dumps(["HUMAN_OVERRIDE"]),
                            is_unmatched=False,
                        )
                    )
    elif target_type == "deviation":
        d = db.get(Deviation, target_id)
        if d is not None:
            details = json.loads(d.details_json or "{}")
            hist = details.setdefault("verdict_history", [])
            hist.append(
                {
                    "at": datetime.utcnow().isoformat(),
                    "verdict": v_norm,
                    "is_ml_label": is_ml_label(v_norm),
                    "user_id": user_id,
                }
            )
            details["last_verdict"] = v_norm
            details["last_verdict_is_ml_label"] = is_ml_label(v_norm)
            d.details_json = json.dumps(details, ensure_ascii=False)
            # ML-метки могут двигать lifecycle; ack_for_review только подтверждает просмотр
            if v_norm in ("confirm", "confirmed", "accept"):
                d.lifecycle = "RESOLVED"
                d.status = "resolved"
                d.resolved_at = datetime.utcnow()
            elif v_norm in ("reject", "rejected"):
                d.lifecycle = "RESOLVED"
                d.status = "rejected"
                d.resolved_at = datetime.utcnow()
            elif v_norm == "correct":
                d.lifecycle = "ACKNOWLEDGED"
                d.status = "corrected"
                corr = correction or {}
                if "schedule_item_id" in corr and corr["schedule_item_id"] is not None:
                    try:
                        d.schedule_item_id = int(corr["schedule_item_id"])
                    except (TypeError, ValueError):
                        pass
                if corr.get("work_type_code") or corr.get("ground_truth_work_type"):
                    details["corrected_work_type"] = corr.get("ground_truth_work_type") or corr.get(
                        "work_type_code"
                    )
                    d.details_json = json.dumps(details, ensure_ascii=False)
            elif v_norm in ACK_VERDICTS:
                d.lifecycle = "ACKNOWLEDGED"
                d.status = "acknowledged"
    db.flush()
    return row


def queue_ambiguous(db: Session, project_id: int) -> list[ActivityHypothesis]:
    from app.db.models import Camera

    camera_ids = [c.id for c in db.query(Camera).filter(Camera.project_id == project_id).all()]
    if not camera_ids:
        return []
    hyps = (
        db.query(ActivityHypothesis)
        .filter(ActivityHypothesis.camera_id.in_(camera_ids))
        .order_by(ActivityHypothesis.id.desc())
        .limit(200)
        .all()
    )
    out: list[ActivityHypothesis] = []
    for h in hyps:
        if h.ui_status in ("UNKNOWN", "NEEDS_REVIEW"):
            matches = (
                db.query(ScheduleMatch)
                .filter(ScheduleMatch.hypothesis_id == h.id)
                .order_by(ScheduleMatch.rank.asc())
                .all()
            )
            for m in matches[:3]:
                reasons = json.loads(m.reason_codes_json or "[]")
                if m.is_unmatched or "AMBIGUOUS_LOCATION" in reasons:
                    out.append(h)
                    break
    return out
