"""V7.1 Sprint 4 — сбор decision-trace из сохранённых фактов (без повторного инференса)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    ActivityHypothesis,
    Camera,
    Detection,
    Deviation,
    Frame,
    InferenceRun,
    ModelVersion,
    Observation,
    ScheduleItem,
    ScheduleMatch,
    WorkType,
)
from app.services.explanation.service import explain_deviation
from app.services.product.overview import deviation_evidence
from app.services.product.ru_labels import (
    binding_status_ru,
    equipment_list_ru,
    limitations_ru,
    zone_ru,
)


def _safe_json(raw: str | None, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        return json.loads(raw or (json.dumps(default) if not isinstance(default, str) else default))
    except Exception:
        return default


def _analysis_source(signal_kind: str | None, has_frames: bool) -> str:
    if signal_kind in ("CV_VERIFIED_FINDING", "SYNTHETIC_DEMO_FINDING"):
        return "COMBINED" if has_frames else "OBSERVATION"
    if signal_kind in ("SCHEDULE_EDITORIAL", "RISK_FROM_SCHEDULE"):
        return "SCHEDULE"
    if has_frames:
        return "COMBINED"
    return "SCHEDULE"


def build_decision_trace(db: Session, project_id: int, deviation_id: int) -> dict[str, Any]:
    d = db.get(Deviation, deviation_id)
    if not d or d.project_id != project_id:
        raise ValueError("deviation not found")

    evidence = deviation_evidence(db, project_id, deviation_id)
    details = _safe_json(d.details_json, {})
    expl = explain_deviation(d)
    finding = expl.get("finding") or {}
    signal_kind = evidence.get("signal_kind")
    frames = evidence.get("frames") or []
    item = db.get(ScheduleItem, d.schedule_item_id) if d.schedule_item_id else None
    wt = db.get(WorkType, item.work_type_id) if item and item.work_type_id else None

    frame_ids = [int(f["id"]) for f in frames if f.get("id") is not None]
    cam_id = evidence.get("camera_id")
    camera = db.get(Camera, cam_id) if cam_id else None
    zone = evidence.get("zone")

    # Сначала provenance: не выдумывать другой match, чем Deviation.schedule_item_id
    source_hyp_id = details.get("source_hypothesis_id")
    source_match_id = details.get("source_schedule_match_id")
    trace_complete = True
    hyp_payload: dict[str, Any] | None = None
    match_payload: dict[str, Any] | None = None
    activity_candidates: list[dict[str, Any]] = []
    model_payload: dict[str, Any] | None = None
    detections_out: list[dict[str, Any]] = []
    kb_version = None
    engine_version = None
    config_hash = None

    if source_hyp_id:
        h = db.get(ActivityHypothesis, int(source_hyp_id))
        if h:
            w = db.get(WorkType, h.work_type_id)
            hyp_payload = {
                "hypothesis_id": h.id,
                "work_type": w.code if w else None,
                "work_type_name": w.name if w else None,
                "activity_score": h.activity_score,
                "score_kind": h.score_kind,
                "ui_status": h.ui_status,
                "interval": [
                    h.interval_start.isoformat() if h.interval_start else None,
                    h.interval_end.isoformat() if h.interval_end else None,
                ],
                "explanation": _safe_json(h.explanation_json, {}),
            }
            activity_candidates = [hyp_payload]
            if source_match_id:
                m = db.get(ScheduleMatch, int(source_match_id))
                if m and m.hypothesis_id == h.id:
                    si = db.get(ScheduleItem, m.schedule_item_id) if m.schedule_item_id else None
                    selected = {
                        "match_id": m.id,
                        "rank": m.rank,
                        "score": m.score,
                        "score_kind": m.score_kind,
                        "is_unmatched": m.is_unmatched,
                        "reason_codes": _safe_json(m.reason_codes_json, []),
                        "schedule_item_id": m.schedule_item_id,
                        "schedule_item_name": si.raw_name if si else None,
                        "building": si.building if si else None,
                        "assignment_status": "MATCHED" if m.schedule_item_id else "UNMATCHED",
                    }
                    match_payload = {
                        "candidates": [selected],
                        "selected": selected,
                        "assignment_status": selected["assignment_status"],
                    }
        else:
            trace_complete = False
    else:
        # Нет сохранённой связи с гипотезой — не восстанавливать из "ближайшего" top score
        if signal_kind in ("CV_VERIFIED_FINDING", "SYNTHETIC_DEMO_FINDING") and frame_ids:
            trace_complete = False

    # При MATCHED якорь selected match всегда Deviation.schedule_item_id
    if item is not None:
        selected_forced = {
            "schedule_item_id": item.id,
            "schedule_item_name": item.raw_name,
            "building": item.building,
            "assignment_status": "MATCHED",
            "source": "deviation.schedule_item_id",
        }
        if match_payload and match_payload.get("selected"):
            sel = match_payload["selected"]
            if sel.get("schedule_item_id") not in (None, item.id):
                match_payload["consistency_error"] = {
                    "code": "TRACE_MISMATCH",
                    "match_item": sel.get("schedule_item_id"),
                    "deviation_item": item.id,
                }
                match_payload["selected"] = selected_forced
                trace_complete = False
            else:
                sel["schedule_item_id"] = item.id
                sel["schedule_item_name"] = item.raw_name
                sel["building"] = item.building
                sel["assignment_status"] = "MATCHED"
        else:
            match_payload = {
                "candidates": [selected_forced],
                "selected": selected_forced,
                "assignment_status": "MATCHED",
            }
    elif not match_payload:
        match_payload = {"candidates": [], "selected": None, "assignment_status": "UNMATCHED"}

    # CV-детекции из кадров evidence (факты), без повторного выбора activity
    for fid in frame_ids[:8]:
        run = (
            db.query(InferenceRun)
            .filter(InferenceRun.frame_id == fid, InferenceRun.status == "COMPLETED")
            .order_by(InferenceRun.id.desc())
            .first()
        )
        if not run:
            continue
        kb_version = kb_version or run.kb_version
        engine_version = engine_version or run.engine_version
        config_hash = config_hash or run.config_hash
        if model_payload is None:
            mv = db.get(ModelVersion, run.model_version_id)
            if mv:
                model_payload = {
                    "id": mv.id,
                    "name": mv.name,
                    "weights_sha256": mv.weights_sha256,
                    "weights_path": mv.weights_path,
                }
        for det in db.query(Detection).filter(Detection.inference_run_id == run.id).all():
            detections_out.append(
                {
                    "frame_id": fid,
                    "run_id": run.id,
                    "equipment_code": det.equipment_code,
                    "raw_class_name": det.raw_class_name,
                    "confidence": det.confidence,
                    "bbox_norm": _safe_json(det.bbox_norm_json, {}),
                    "zone_id": det.zone_id,
                }
            )

    covered = details.get("covered_interval") or []
    period = None
    if isinstance(covered, list) and len(covered) >= 2:
        period = f"{covered[0]} – {covered[1]}"
    elif frame_ids:
        times = [f["captured_at"] for f in frames if f.get("captured_at")]
        if times:
            period = f"{min(times)} – {max(times)}"

    binding_status = (zone or {}).get("binding_status") if zone else None
    if camera and camera.building_hint and not binding_status:
        binding_status = "HINT"

    user_steps = _user_logic_steps(
        camera=camera,
        zone=zone,
        frames=frames,
        period=period,
        details=details,
        finding=finding,
        item=item,
        wt=wt,
        signal_kind=signal_kind,
        explanation_ru=evidence.get("explanation_ru") or expl.get("text_ru"),
    )

    source = _analysis_source(signal_kind, bool(frames))
    is_schedule_only = source == "SCHEDULE" and not frames

    return {
        "finding": {
            "id": d.id,
            "code": d.code,
            "lifecycle": d.lifecycle,
            "signal_kind": signal_kind,
            "heuristic_score": d.heuristic_score if d.heuristic_score is not None else d.risk_score,
            "explanation_ru": evidence.get("explanation_ru") or expl.get("text_ru"),
            "card": evidence.get("card"),
        },
        "source": source,
        "context": {
            "as_of": details.get("as_of")
            or (d.last_seen.isoformat() if d.last_seen else None)
            or (d.first_seen.isoformat() if d.first_seen else None),
            "schedule_version_id": d.schedule_version_id,
            "schedule_item": evidence.get("schedule_item"),
            "work_type": {"code": wt.code, "name": wt.name} if wt else None,
        },
        "observation": None
        if is_schedule_only
        else {
            "camera": {"id": camera.id, "name": camera.name, "building_hint": camera.building_hint}
            if camera
            else None,
            "zone": zone,
            "binding_status": binding_status or "UNASSIGNED",
            "frames": [
                {
                    "id": f.get("id"),
                    "captured_at": f.get("captured_at"),
                    "image_url": f.get("image_url"),
                    "overlay_url": f.get("overlay_url"),
                    "quality": None,
                    "detections_count": len(f.get("detections") or []),
                }
                for f in frames
            ],
            "usable_frames": details.get("frames_in_window") or len(frames),
            "period": period,
        },
        "cv": None
        if is_schedule_only
        else {
            "model": model_payload,
            "detections": detections_out[:40],
            "observed_equipment": finding.get("observed_equipment")
            or details.get("observed_equipment")
            or [],
            "equipment_coverage": details.get("equipment_coverage"),
        },
        "activity": None
        if is_schedule_only
        else {
            "engine": engine_version or "heuristic_v2",
            "score_kind": (hyp_payload or {}).get("score_kind") or "uncalibrated_score",
            "candidates": activity_candidates[:8],
            "feature_breakdown": (hyp_payload or {}).get("explanation") or {},
            "selected": hyp_payload,
        },
        "matching": None
        if is_schedule_only
        else (match_payload or {
            "candidates": [],
            "selected": evidence.get("schedule_item"),
            "assignment_status": "MATCHED" if item else "UNMATCHED",
        }),
        "trace_status": "OK" if trace_complete else "TRACE_INCOMPLETE",
        "rule": {
            "code": d.code,
            "expected": finding.get("expected_equipment") or details.get("expected_equipment") or [],
            "observed": finding.get("observed_equipment") or details.get("observed_equipment") or [],
            "missing": finding.get("not_confirmed_equipment")
            or details.get("not_confirmed_equipment")
            or details.get("unexpected_equipment")
            or [],
            "parameters": {
                "lookback_hours": details.get("lookback_hours"),
                "frames_in_window": details.get("frames_in_window"),
                "camera_visual_zone_id": details.get("camera_visual_zone_id") or details.get("zone_key"),
                "building": details.get("building") or (item.building if item else None),
            },
            "user_label": finding.get("hypothesis") or details.get("hypothesis") or d.code,
        },
        "explanation": {
            "engine": "template_fallback",
            "model": None,
            "unsupported_claims_blocked": False,
            "text_ru": evidence.get("explanation_ru") or expl.get("text_ru"),
            "limitations": limitations_ru(
                evidence.get("limitations") or finding.get("limitations") or []
            ),
        },
        "provenance": {
            "cv_model_version": (model_payload or {}).get("name") or (model_payload or {}).get("weights_sha256"),
            "cv_weights_sha256": (model_payload or {}).get("weights_sha256"),
            "kb_version": kb_version,
            "engine_version": engine_version,
            "config_hash": config_hash,
            "schedule_version_id": d.schedule_version_id,
            "deviation_id": d.id,
            "assembled_at": datetime.utcnow().isoformat() + "Z",
            "re_inferred": False,
        },
        "user_logic": user_steps,
        "expert": {
            "frame_ids": frame_ids,
            "details": details,
            "evidence_chain": evidence.get("chain") or [],
            "zones": evidence.get("zones") or [],
        },
    }


def _user_logic_steps(
    *,
    camera: Camera | None,
    zone: dict | None,
    frames: list[dict],
    period: str | None,
    details: dict,
    finding: dict,
    item: ScheduleItem | None,
    wt: WorkType | None,
    signal_kind: str | None,
    explanation_ru: str | None,
) -> list[dict[str, str]]:
    if signal_kind in ("SCHEDULE_EDITORIAL", "RISK_FROM_SCHEDULE") and not frames:
        return [
            {
                "id": "schedule",
                "title": "Источник сигнала",
                "body": "Предупреждение сформировано по полям календарного графика, без кадров камер.",
            },
            {
                "id": "work",
                "title": "Работа КСГ",
                "body": (item.raw_name if item else "Строка не назначена")
                + (f" · {item.building}" if item and item.building else ""),
            },
            {
                "id": "rule",
                "title": "Правило",
                "body": finding.get("hypothesis") or details.get("note") or explanation_ru or "—",
            },
            {
                "id": "limits",
                "title": "Ограничения",
                "body": "; ".join(
                    limitations_ru(finding.get("limitations") or details.get("limitations") or [])
                )
                or "Не заменяет проверку на площадке.",
            },
        ]

    cam_name = camera.name if camera else "Камера не определена"
    zone_label = (
        (zone or {}).get("name")
        or zone_ru((zone or {}).get("zone_key") or details.get("camera_visual_zone_id"))
    )
    building = details.get("building") or (item.building if item else None) or (camera.building_hint if camera else None)
    observed = finding.get("observed_equipment") or details.get("observed_equipment") or []
    missing = finding.get("not_confirmed_equipment") or details.get("not_confirmed_equipment") or []
    unexpected = details.get("unexpected_equipment") or []

    seen_line = equipment_list_ru(observed) if observed else "техника в окне анализа не классифицирована уверенно"
    miss_line = ""
    if missing:
        miss_line = f" Не подтверждены в окне: {equipment_list_ru(missing)}."
    if unexpected:
        miss_line += f" Вне этапа: {equipment_list_ru(unexpected)}."

    activity_name = (wt.name if wt else None) or finding.get("hypothesis") or "гипотеза по составу техники и зоне"
    work_line = item.raw_name if item else "строка КСГ не выбрана"
    if item and item.planned_start and item.planned_finish:
        work_line += f" · план {item.planned_start.date().isoformat()}–{item.planned_finish.date().isoformat()}"
    if building:
        work_line = f"{building}: {work_line}"

    raw_bind = (zone or {}).get("binding_status")
    if isinstance(raw_bind, str) and raw_bind.strip():
        bind = binding_status_ru(raw_bind)
    else:
        bind = "привязка зоны подтверждена" if building else "привязка не подтверждена"

    return [
        {
            "id": "observation",
            "title": "Наблюдение",
            "body": f"{cam_name}\nЗона: {zone_label}"
            + (f" / {building}" if building else "")
            + f"\nПригодных кадров: {details.get('frames_in_window') or len(frames)}"
            + (f"\nПериод анализа: {period}" if period else ""),
        },
        {
            "id": "detected",
            "title": "Что обнаружено",
            "body": seen_line + miss_line,
        },
        {
            "id": "activity",
            "title": "Какую активность предположили",
            "body": f"Вероятный вид работ: {activity_name}\n"
            "Основания: состав техники + зона + календарное окно. "
            "Оценка модели ориентировочная, это не вероятность события.",
        },
        {
            "id": "matching",
            "title": "С какой работой КСГ связали",
            "body": f"{work_line}\nПривязка зоны: {bind}",
        },
        {
            "id": "rule",
            "title": "Какое правило сработало",
            "body": finding.get("hypothesis")
            or details.get("hypothesis")
            or "Сопоставление ожидаемой и наблюдаемой техники / покрытия камер.",
        },
        {
            "id": "signal",
            "title": "Почему сформирован сигнал",
            "body": explanation_ru or finding.get("hypothesis") or "—",
        },
        {
            "id": "limits",
            "title": "Ограничения",
            "body": "; ".join(
                limitations_ru(finding.get("limitations") or details.get("limitations") or [])
            )
            or "Вывод основан на зоне обзора камеры и не доказывает отсутствие техники на всей площадке.",
        },
    ]
