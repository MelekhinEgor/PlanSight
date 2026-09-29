"""Продуктовые API для UI V3: overview, timeline, evidence отклонения."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    Camera,
    CameraVisualZone,
    Deviation,
    Frame,
    InferenceRun,
    Observation,
    ScheduleItem,
    WorkType,
)
from app.services.explanation.service import explain_deviation
from app.services.product.ru_labels import (
    deviation_code_ru,
    equipment_list_ru,
    equipment_ru,
    limitations_ru,
    zone_ru,
)
from app.services.schedule.service import get_active_schedule, list_schedule_items
from app.services.zones.service import building_for_zone, list_active_zones, zones_payload


def _norm(name: str | None) -> str:
    return " ".join((name or "").strip().lower().split())


def build_overview(db: Session, project_id: int, *, as_of: datetime | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.utcnow()
    version = get_active_schedule(db, project_id)
    cameras = db.query(Camera).filter(Camera.project_id == project_id, Camera.enabled.is_(True)).all()
    items = list_schedule_items(db, project_id)
    leaf = [i for i in items if not i.is_summary and not i.is_milestone]

    # V6: без утечки будущего — last_frame / открытые алерты ограничены as_of
    last_frame_q = db.query(Frame).filter(
        Frame.project_id == project_id,
        Frame.captured_at.isnot(None),
        Frame.captured_at <= as_of,
    )
    last_frame = last_frame_q.order_by(Frame.captured_at.desc()).first()
    frames_day = (
        db.query(Frame)
        .filter(
            Frame.project_id == project_id,
            Frame.captured_at >= as_of.replace(hour=0, minute=0, second=0, microsecond=0),
            Frame.captured_at <= as_of,
        )
        .count()
    )

    open_dev = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project_id,
            Deviation.lifecycle.in_(["OPEN", "ACKNOWLEDGED"]),
        )
        .order_by(Deviation.id.desc())
        .all()
    )
    # Предпочитать first_seen/last_seen; отбросить finding только после as_of
    bounded: list[Deviation] = []
    for d in open_dev:
        marker = getattr(d, "first_seen", None) or getattr(d, "last_seen", None)
        if marker is not None and marker > as_of:
            continue
        bounded.append(d)
    open_dev = bounded

    # Ситуации по корпусам / зонам
    situations: list[dict[str, Any]] = []
    buildings = sorted(
        {
            (i.building_normalized or i.building or "").strip()
            for i in leaf
            if (i.building_normalized or i.building)
        }
    )
    wt = {w.id: w for w in db.query(WorkType).all()}

    for b in buildings or ["—"]:
        related_dev = []
        for d in open_dev:
            details = json.loads(d.details_json or "{}")
            if (details.get("building") or "") == b:
                related_dev.append(d)
                continue
            if d.schedule_item_id:
                it = db.get(ScheduleItem, d.schedule_item_id)
                if it and (it.building or "") == b:
                    related_dev.append(d)
        if not frames_day and not last_frame:
            status = "no_data"
            label = "Нет данных для вывода"
        elif any(d.code == "REQUIRED_EQUIPMENT_GAP" for d in related_dev):
            status = "needs_check"
            label = "Требует проверки"
        elif any(d.code == "NEEDS_CAMERA_SETUP" for d in related_dev):
            status = "needs_setup"
            label = "Нужна настройка камеры/зоны"
        elif related_dev:
            status = "needs_check"
            label = "Требует проверки"
        elif last_frame:
            status = "signs_ok"
            label = "Есть подтверждающие признаки / рисков не выявлено"
        else:
            status = "insufficient"
            label = "Недостаточно данных"

        situations.append(
            {
                "building": b,
                "status": status,
                "status_label": label,
                "open_issues": len(related_dev),
                "top_codes": list({d.code for d in related_dev})[:5],
            }
        )

    issues = []
    for d in open_dev[:20]:
        expl = explain_deviation(d)
        item = db.get(ScheduleItem, d.schedule_item_id) if d.schedule_item_id else None
        details = json.loads(d.details_json or "{}")
        issues.append(
            {
                "id": d.id,
                "code": d.code,
                "lifecycle": d.lifecycle,
                "title": item.raw_name if item else d.code,
                "building": details.get("building") or (item.building if item else None),
                "zone_key": details.get("camera_visual_zone_id") or details.get("zone_key"),
                "explanation_ru": expl["text_ru"],
                "finding": expl["finding"],
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "project_id": project_id,
        "schedule": {
            "version_id": version.id if version else None,
            "kind": version.kind if version else None,
            "leaf_count": len(leaf),
        },
        "freshness": {
            "last_observation": last_frame.captured_at.isoformat() if last_frame and last_frame.captured_at else None,
            "frames_today": frames_day,
            "cameras": len(cameras),
        },
        "attention_count": len(
            [i for i in issues if i["code"] in ("REQUIRED_EQUIPMENT_GAP", "UNEXPECTED_EQUIPMENT_IN_ZONE", "AMBIGUOUS_ASSIGNMENT")]
        ),
        "situations": situations,
        "issues": issues,
        "note": "При отсутствии наблюдений показывается «нет данных», а не «рисков нет».",
    }


def build_timeline(
    db: Session,
    project_id: int,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    building: str | None = None,
) -> dict[str, Any]:
    items = list_schedule_items(db, project_id)
    wt = {w.id: w for w in db.query(WorkType).all()}
    rows = []
    for item in items:
        if item.is_summary or item.is_milestone:
            continue
        if building and (item.building or "").lower() != building.lower():
            continue
        if date_from and item.planned_finish < date_from:
            continue
        if date_to and item.planned_start > date_to:
            continue
        # наблюдаемые интервалы — по OPEN/связанным отклонениям и кадрам зоны (упрощённо)
        details_obs: list[dict[str, Any]] = []
        devs = (
            db.query(Deviation)
            .filter(
                Deviation.project_id == project_id,
                Deviation.schedule_item_id == item.id,
                Deviation.lifecycle.in_(["OPEN", "ACKNOWLEDGED", "RESOLVED"]),
            )
            .all()
        )
        obs_status = "unknown"
        if any(d.code == "REQUIRED_EQUIPMENT_GAP" for d in devs):
            obs_status = "incomplete_composition"
        elif any(d.code == "NEEDS_CAMERA_SETUP" for d in devs):
            obs_status = "needs_setup"
        elif last_related_frames(db, project_id, item):
            obs_status = "observed_signs"
            details_obs = last_related_frames(db, project_id, item)

        rows.append(
            {
                "schedule_item_id": item.id,
                "name": item.raw_name,
                "building": item.building,
                "work_type": wt[item.work_type_id].code if item.work_type_id in wt else None,
                "observability_mode": item.observability_mode,
                "planned_start": item.planned_start.isoformat(),
                "planned_finish": item.planned_finish.isoformat(),
                "observed_status": obs_status,
                "observed_intervals": details_obs,
                "note": "наблюдение по снимкам — не % физической готовности",
            }
        )
    return {"items": rows, "count": len(rows)}


def last_related_frames(db: Session, project_id: int, item: ScheduleItem) -> list[dict[str, Any]]:
    cams = db.query(Camera).filter(Camera.project_id == project_id).all()
    if item.building:
        cams = [c for c in cams if (c.building_hint or "").lower() == item.building.lower()] or cams
    out = []
    for c in cams[:3]:
        fr = (
            db.query(Frame)
            .filter(Frame.camera_id == c.id, Frame.captured_at.isnot(None))
            .order_by(Frame.captured_at.desc())
            .first()
        )
        if fr and fr.captured_at:
            out.append(
                {
                    "camera_id": c.id,
                    "frame_id": fr.id,
                    "start": fr.captured_at.isoformat(),
                    "end": (fr.captured_at + timedelta(minutes=20)).isoformat(),
                    "source": "frame",
                }
            )
    return out


def list_frames(
    db: Session,
    project_id: int,
    *,
    camera_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = db.query(Frame).filter(Frame.project_id == project_id)
    if camera_id:
        q = q.filter(Frame.camera_id == camera_id)
    if date_from:
        q = q.filter(Frame.captured_at >= date_from)
    if date_to:
        q = q.filter(Frame.captured_at <= date_to)
    # Скрываем архив/удалённые из продуктовой ленты
    q = q.filter(~Frame.ingest_status.in_(("ARCHIVED", "DELETED")))
    frames = q.order_by(Frame.captured_at.desc(), Frame.id.desc()).limit(limit).all()
    out = []
    for fr in frames:
        run = (
            db.query(InferenceRun)
            .filter(InferenceRun.frame_id == fr.id, InferenceRun.status == "COMPLETED")
            .order_by(InferenceRun.id.desc())
            .first()
        )
        out.append(
            {
                "id": fr.id,
                "camera_id": fr.camera_id,
                "captured_at": fr.captured_at.isoformat() if fr.captured_at else None,
                "quality": fr.image_quality,
                "image_url": f"/api/frames/{fr.id}/image",
                "overlay_url": None,
                "run_id": run.id if run else None,
                "run_status": run.status if run else None,
            }
        )
        if run:
            from app.core.config import get_settings

            overlay = (
                get_settings().overlays_dir()
                / f"project_{project_id}"
                / f"frame_{fr.id}_run_{run.id}.jpg"
            )
            if overlay.exists():
                out[-1]["overlay_url"] = f"/api/frames/{fr.id}/overlay"
    return out


def deviation_evidence(db: Session, project_id: int, deviation_id: int) -> dict[str, Any]:
    d = db.get(Deviation, deviation_id)
    if not d or d.project_id != project_id:
        raise ValueError("deviation not found")
    expl = explain_deviation(d)
    finding = expl["finding"]
    details = json.loads(d.details_json or "{}")
    item = db.get(ScheduleItem, d.schedule_item_id) if d.schedule_item_id else None

    frame_ids = finding.get("evidence_ids") or details.get("evidence_frame_ids") or []
    if not frame_ids:
        try:
            frame_ids = json.loads(d.evidence_ids_json or "[]")
        except Exception:
            frame_ids = []
    # V5 P0: не подставлять кадры чужого проекта как evidence
    if isinstance(frame_ids, str):
        try:
            frame_ids = json.loads(frame_ids or "[]")
        except Exception:
            frame_ids = []
    cleaned: list[int] = []
    for x in frame_ids or []:
        try:
            cleaned.append(int(x))
        except (TypeError, ValueError):
            continue
    frame_ids = cleaned

    # V6: не изобретать CV_VERIFIED_FINDING из непрозрачных id (hyp/evidence row)
    signal_kind = details.get("signal_kind") or (
        "SCHEDULE_EDITORIAL" if d.code == "SCHEDULE_LAG" else "UNVERIFIED"
    )
    if signal_kind == "CV_VERIFIED_FINDING" and details.get("data_origin") == "SYNTHETIC_TEST_FIXTURE":
        signal_kind = "SYNTHETIC_DEMO_FINDING"
    if signal_kind == "UNVERIFIED" and frame_ids and d.code in (
        "REQUIRED_EQUIPMENT_GAP",
        "UNEXPECTED_EQUIPMENT_IN_ZONE",
        "CAMERA_COVERAGE_GAP",
        "UNCONFIRMED_ACTIVITY",
        "POSSIBLE_PAUSE",
        "WORK_AFTER_PLAN",
        "LOW_ACTIVITY",
    ):
        signal_kind = "CV_VERIFIED_FINDING"
    if signal_kind == "CV_VERIFIED_FINDING" and not frame_ids:
        signal_kind = "UNVERIFIED"

    zone_key = details.get("camera_visual_zone_id") or details.get("zone_key")
    cam_id_for_zones: int | None = None
    frames = []
    for fid in frame_ids[:12]:
        fr = db.get(Frame, int(fid))
        if not fr or fr.project_id != project_id:
            continue
        cam_id_for_zones = fr.camera_id
        # Предпочитать явные evidence_ids soft mismatch building_hint;
        # конфликты hint — в limitations, доказательства не дропаем.
        if item and item.building and fr.camera_id:
            cam = db.get(Camera, fr.camera_id)
            if cam and cam.building_hint and _norm(cam.building_hint) != _norm(item.building):
                # Кадр оставить; mismatch отметить один раз
                pass
        run = (
            db.query(InferenceRun)
            .filter(InferenceRun.frame_id == fr.id, InferenceRun.status == "COMPLETED")
            .order_by(InferenceRun.id.desc())
            .first()
        )
        eq = {}
        zones_eq: dict[str, dict] = {}
        dets_out: list[dict[str, Any]] = []
        if run:
            obs = db.query(Observation).filter(Observation.inference_run_id == run.id).one_or_none()
            if obs:
                eq = json.loads(obs.equipment_vector_json or "{}")
                zones_eq = json.loads(obs.quality_json or "{}").get("zones") or {}
                if zone_key and zone_key in zones_eq:
                    eq = zones_eq[zone_key]
            from app.db.models import Detection as Det

            for det in db.query(Det).filter(Det.inference_run_id == run.id).all():
                dets_out.append(
                    {
                        "equipment_code": det.equipment_code,
                        "confidence": det.confidence,
                        "bbox_norm": json.loads(det.bbox_norm_json or "{}"),
                        "zone_id": det.zone_id,
                    }
                )
        frames.append(
            {
                "id": fr.id,
                "frame_id": fr.id,
                "captured_at": fr.captured_at.isoformat() if fr.captured_at else None,
                "camera_id": fr.camera_id,
                "image_url": f"/api/frames/{fr.id}/image",
                "overlay_url": None,
                "equipment": eq,
                "zones_equipment": zones_eq,
                "detections": dets_out,
            }
        )
        if run:
            from app.core.config import get_settings

            overlay = (
                get_settings().overlays_dir()
                / f"project_{project_id}"
                / f"frame_{fr.id}_run_{run.id}.jpg"
            )
            if overlay.exists():
                frames[-1]["overlay_url"] = f"/api/frames/{fr.id}/overlay"

    zone_payload = None
    all_zones: list[dict[str, Any]] = []
    if cam_id_for_zones:
        zs = list_active_zones(db, cam_id_for_zones)
        all_zones = zones_payload(zs, db)
        if zone_key:
            zone_payload = next((z for z in all_zones if z.get("zone_key") == zone_key), None)
    elif zone_key:
        z = (
            db.query(CameraVisualZone)
            .filter(
                CameraVisualZone.project_id == project_id,
                CameraVisualZone.zone_key == zone_key,
                CameraVisualZone.status == "active",
            )
            .first()
        )
        if z:
            zone_payload = zones_payload([z], db)[0]
            all_zones = [zone_payload]

    lims = limitations_ru(finding.get("limitations") or details.get("limitations") or [])
    observed_ru = equipment_list_ru(finding.get("observed_equipment"))
    expected_ru = equipment_list_ru(finding.get("expected_equipment"))
    zone_label = zone_ru(zone_key)
    hyp = finding.get("hypothesis") or deviation_code_ru(d.code)

    chain = [
        {"step": 1, "title": "Кадры и время съёмки", "detail": f"{len(frames)} кадров-доказательств"},
        {
            "step": 2,
            "title": "Машины (детекция)",
            "detail": f"наблюдалось: {observed_ru}",
        },
        {
            "step": 3,
            "title": "Пространственная привязка",
            "detail": f"{zone_label} · корпус {details.get('building') or (item.building if item else '—')}",
        },
        {
            "step": 4,
            "title": "Технологическая схема",
            "detail": f"ожидалось: {expected_ru}",
        },
        {
            "step": 5,
            "title": "Строка КСГ",
            "detail": item.raw_name if item else "не назначена",
        },
        {
            "step": 6,
            "title": "Условие предупреждения",
            "detail": hyp,
        },
        {
            "step": 7,
            "title": "Ограничения",
            "detail": "; ".join(lims) or "—",
        },
        {
            "step": 8,
            "title": "Что проверить",
            "detail": finding.get("suggested_check") or "сверить с площадкой",
        },
    ]

    return {
        "finding_id": str(d.id),
        "deviation_id": d.id,
        "signal_kind": signal_kind,
        "code": d.code,
        "lifecycle": d.lifecycle,
        "explanation_ru": expl["text_ru"],
        "finding": finding,
        "limitations": lims,
        "focus_zone_key": zone_key,
        "schedule_item_id": str(item.id) if item else None,
        "project_object_id": str(item.project_object_id) if item and item.project_object_id else None,
        "camera_id": cam_id_for_zones,
        "zone_id": (zone_payload or {}).get("id") if zone_payload else None,
        "schedule_item": {
            "id": str(item.id),
            "name": item.raw_name,
            "building": item.building,
            "project_object_id": str(item.project_object_id) if item.project_object_id else None,
            "planned_start": item.planned_start.isoformat() if item.planned_start else None,
            "planned_finish": item.planned_finish.isoformat() if item.planned_finish else None,
            "planned_progress": item.planned_progress,
            "actual_progress": item.actual_progress,
            "forecast_end": item.forecast_end.isoformat() if item.forecast_end else None,
        }
        if item
        else None,
        "zone": zone_payload,
        "zones": all_zones,
        "frames": frames,
        "chain": chain,
        "card": {
            "what_seen": [equipment_ru(x) for x in (finding.get("observed_equipment") or [])],
            "what_missing": [
                equipment_ru(x)
                for x in (
                    finding.get("not_confirmed_equipment")
                    or finding.get("unexpected_equipment")
                    or []
                )
            ],
            "why": finding.get("hypothesis"),
            "unknown": lims[0] if lims else "Процент готовности по фото не выводится",
            "check": finding.get("suggested_check"),
        },
    }


def schedule_item_evidence(
    db: Session,
    project_id: int,
    item_id: int,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Доказательства строки графика: CV finding если связан, иначе editorial RISK (без кадров)."""
    item = db.get(ScheduleItem, item_id)
    if not item:
        raise ValueError("schedule item not found")
    version = get_active_schedule(db, project_id)
    if not version or item.schedule_version_id != version.id:
        # Разрешить, если принадлежит проекту через version
        from app.db.models import ScheduleVersion

        ver = db.get(ScheduleVersion, item.schedule_version_id)
        if not ver or ver.project_id != project_id:
            raise ValueError("schedule item not found")

    cv = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project_id,
            Deviation.schedule_item_id == item_id,
            Deviation.lifecycle != "RESOLVED",
        )
        .order_by(Deviation.id.desc())
        .first()
    )
    if cv:
        details = json.loads(cv.details_json or "{}")
        eids = []
        try:
            eids = json.loads(cv.evidence_ids_json or "[]")
        except Exception:
            eids = []
        if eids or details.get("signal_kind") == "CV_VERIFIED_FINDING":
            return deviation_evidence(db, project_id, cv.id)

    plan = float(item.planned_progress or 0)
    fact = float(item.actual_progress or 0)
    return {
        "finding_id": None,
        "deviation_id": None,
        "signal_kind": "RISK_FROM_SCHEDULE",
        "code": "SCHEDULE_RISK",
        "lifecycle": None,
        "explanation_ru": (
            f"Риск по календарному графику на срез {as_of or '—'}: план {plan:.0f}% · факт {fact:.0f}%. "
            "Кадры камер к этой оценке не привязаны."
        ),
        "finding": {"finding": "SCHEDULE_RISK", "limitations": ["Оценка только по полям КСГ"]},
        "limitations": ["Оценка только по полям КСГ", "Нет кадров-доказательств"],
        "focus_zone_key": None,
        "schedule_item_id": str(item.id),
        "project_object_id": str(item.project_object_id) if item.project_object_id else None,
        "camera_id": None,
        "zone_id": None,
        "schedule_item": {
            "id": str(item.id),
            "name": item.raw_name,
            "building": item.building,
            "project_object_id": str(item.project_object_id) if item.project_object_id else None,
            "planned_start": item.planned_start.isoformat() if item.planned_start else None,
            "planned_finish": item.planned_finish.isoformat() if item.planned_finish else None,
            "planned_progress": item.planned_progress,
            "actual_progress": item.actual_progress,
            "forecast_end": item.forecast_end.isoformat() if item.forecast_end else None,
        },
        "zone": None,
        "zones": [],
        "frames": [],
        "chain": [
            {"step": 1, "title": "Источник", "detail": "Календарный график (editorial)"},
            {"step": 2, "title": "План / факт", "detail": f"{plan:.0f}% / {fact:.0f}%"},
            {
                "step": 3,
                "title": "Прогноз",
                "detail": item.forecast_end.date().isoformat() if item.forecast_end else "—",
            },
        ],
        "card": {
            "what_seen": [],
            "what_missing": [],
            "why": "Расхождение плана, факта или прогноза по графику",
            "unknown": "Без кадров камер",
            "check": "Сверить сроки с площадкой или загрузить кадры",
        },
        "as_of": as_of,
    }


def patch_deviation_lifecycle(
    db: Session,
    project_id: int,
    deviation_id: int,
    *,
    lifecycle: str,
    note: str | None = None,
    user_id: str = "operator",
) -> Deviation:
    """Только lifecycle. ACK — НЕ ML-метка (см. submit_verdict)."""
    d = db.get(Deviation, deviation_id)
    if not d or d.project_id != project_id:
        raise ValueError("deviation not found")
    allowed = {"OPEN", "ACKNOWLEDGED", "RESOLVED"}
    life = lifecycle.upper()
    if life not in allowed:
        raise ValueError(f"lifecycle must be one of {allowed}")
    d.lifecycle = life
    d.status = life.lower()
    if life == "RESOLVED":
        d.resolved_at = datetime.utcnow()
    elif life == "OPEN":
        d.resolved_at = None
        d.status = "open"
    details = json.loads(d.details_json or "{}")
    hist = details.setdefault("lifecycle_history", [])
    hist.append(
        {
            "at": datetime.utcnow().isoformat(),
            "lifecycle": life,
            "note": note,
            "is_ml_label": False,
        }
    )
    d.details_json = json.dumps(details, ensure_ascii=False)
    # Вердикт HumanVerdict без ML: ack аудитируем, но не метка обучения
    if life == "ACKNOWLEDGED":
        from app.services.verification.service import submit_verdict

        submit_verdict(
            db,
            target_type="deviation",
            target_id=deviation_id,
            verdict="ack_for_review",
            correction={"note": note, "source": "lifecycle_ack"},
            user_id=user_id,
        )
    db.flush()
    return d
