"""Общий DTO отчёта PlanSight (один finding / проект) — без повторного CV inference."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Deviation, Project, ScheduleVersion
from app.services.product.decision_trace import build_decision_trace
from app.services.product.overview import deviation_evidence


def _project_card(project: Project) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    try:
        settings = json.loads(getattr(project, "settings_json", None) or "{}")
    except Exception:
        settings = {}
    return {
        "id": project.id,
        "name": project.name,
        "address": settings.get("address") or settings.get("location"),
        "region": settings.get("region"),
    }


def _frame_ids_from_deviation(d: Deviation | None) -> list[int]:
    if not d:
        return []
    try:
        raw = json.loads(d.evidence_ids_json or "[]")
    except Exception:
        raw = []
    out: list[int] = []
    for x in raw or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+00:00", ""))
    except ValueError:
        return None


def _match_status(details: dict[str, Any], evidence: dict[str, Any], trace: dict[str, Any]) -> str:
    raw = (
        details.get("match_status")
        or details.get("assignment_status")
        or (trace.get("matching") or {}).get("assignment_status")
        or ""
    )
    raw = str(raw).upper() or ""
    if raw in ("ACCEPTED", "AMBIGUOUS", "REJECTED", "UNMATCHED", "MATCHED"):
        if raw == "MATCHED":
            return "ACCEPTED" if evidence.get("schedule_item") else "UNMATCHED"
        return raw
    if evidence.get("schedule_item") and evidence.get("signal_kind") in (
        "CV_VERIFIED_FINDING",
        "SYNTHETIC_DEMO_FINDING",
    ):
        return "ACCEPTED"
    if evidence.get("schedule_item"):
        return "ACCEPTED"
    return "UNMATCHED"


def _safe_schedule_item(match_status: str, evidence: dict[str, Any]) -> dict[str, Any] | None:
    """КСГ как установленный факт — только при ACCEPTED."""
    if match_status != "ACCEPTED":
        return None
    return evidence.get("schedule_item")


def build_finding_report_section(
    db: Session,
    project_id: int,
    deviation_id: int,
    *,
    max_frames: int = 3,
    include_all_frames: bool = False,
) -> dict[str, Any]:
    evidence = deviation_evidence(db, project_id, deviation_id)
    try:
        trace = build_decision_trace(db, project_id, deviation_id)
    except ValueError:
        trace = {"trace_status": "TRACE_INCOMPLETE", "user_logic": []}

    d = db.get(Deviation, deviation_id)
    details: dict[str, Any] = {}
    if d:
        try:
            details = json.loads(d.details_json or "{}")
        except Exception:
            details = {}

    match_status = _match_status(details, evidence, trace)
    frames = list(evidence.get("frames") or [])
    if not include_all_frames:
        frames = frames[: max(1, min(max_frames, 12))]
    else:
        frames = frames[:40]

    # Не включать пути сервера в DTO
    frames_out = []
    for fr in frames:
        frames_out.append(
            {
                "frame_id": fr.get("id") or fr.get("frame_id"),
                "captured_at": fr.get("captured_at"),
                "timestamp_source": fr.get("timestamp_source") or "не зафиксировано",
                "camera_id": fr.get("camera_id"),
                "image_quality": fr.get("image_quality"),
                "zone_key": evidence.get("focus_zone_key"),
                "image_url": fr.get("image_url"),
                "overlay_url": fr.get("overlay_url"),
                "detections": [
                    {
                        "equipment_code": det.get("equipment_code"),
                        "confidence": det.get("confidence"),
                        "bbox_norm": det.get("bbox_norm"),
                        "zone_id": det.get("zone_id"),
                    }
                    for det in (fr.get("detections") or [])
                ],
                "role": fr.get("role") or "evidence",
                "available": bool(fr.get("image_url")),
            }
        )

    provenance = trace.get("provenance") or {}
    return {
        "finding_id": str(evidence.get("deviation_id") or deviation_id),
        "deviation_id": evidence.get("deviation_id") or deviation_id,
        "code": evidence.get("code"),
        "signal_kind": evidence.get("signal_kind"),
        "lifecycle": evidence.get("lifecycle"),
        "severity": details.get("severity") or details.get("priority") or "medium",
        "explanation_ru": evidence.get("explanation_ru") or "Не зафиксировано",
        "match_status": match_status,
        "schedule_item": _safe_schedule_item(match_status, evidence),
        "schedule_item_refused_reason": None
        if match_status == "ACCEPTED"
        else f"Matching {match_status}: строка КСГ не показывается как установленный факт",
        "zone": evidence.get("zone"),
        "expected": (evidence.get("card") or {}).get("what_missing")
        or (trace.get("rule") or {}).get("expected")
        or [],
        "observed": (evidence.get("card") or {}).get("what_seen")
        or (trace.get("rule") or {}).get("observed")
        or [],
        "limitations": evidence.get("limitations") or [],
        "recommendation": (evidence.get("card") or {}).get("check")
        or details.get("suggested_check")
        or "Сверить с площадкой",
        "decision_trace": {
            "trace_status": trace.get("trace_status") or "TRACE_INCOMPLETE",
            "user_logic": trace.get("user_logic") or [],
            "rule": trace.get("rule"),
            "matching": {
                "assignment_status": match_status,
                "selected": _safe_schedule_item(match_status, evidence),
            },
            "provenance": {
                "cv_model_version": provenance.get("cv_model_version"),
                "kb_version": provenance.get("kb_version"),
                "engine_version": provenance.get("engine_version"),
                "schedule_version_id": provenance.get("schedule_version_id"),
                "re_inferred": False,
            },
        },
        "verdict_history": evidence.get("verdict_history") or [],
        "last_verdict": evidence.get("last_verdict"),
        "frames": frames_out,
        "evidence_frame_ids": _frame_ids_from_deviation(d)
        if d
        else [int(f["frame_id"]) for f in frames_out if f.get("frame_id") is not None],
        "disclaimer": (
            "Настоящий отчёт носит информационно-аналитический характер. Он не заменяет предусмотренные "
            "законодательством и контрактом документы о приёмке, экспертизу результатов исполнения контракта, "
            "строительный контроль и решения уполномоченных лиц. Правовые последствия определяются "
            "уполномоченными лицами с учётом условий контракта и применимого законодательства."
        ),
    }


def build_project_report_dto(
    db: Session,
    project_id: int,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    include_false_positives: bool = True,
    include_no_data: bool = True,
    lifecycles: list[str] | None = None,
    detail: str = "full",
    max_frames_per_finding: int = 3,
    include_all_frames: bool = False,
    author: str | None = None,
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError("project not found")

    df = _parse_dt(date_from)
    dt = _parse_dt(date_to)
    q = db.query(Deviation).filter(Deviation.project_id == project_id)
    rows = q.order_by(Deviation.id.asc()).all()

    filtered: list[Deviation] = []
    for d in rows:
        details: dict[str, Any] = {}
        try:
            details = json.loads(d.details_json or "{}")
        except Exception:
            details = {}
        sk = str(details.get("signal_kind") or "")
        created = d.created_at
        if df and created and created < df:
            continue
        if dt and created and created > dt:
            continue
        if lifecycles and (d.lifecycle or "").upper() not in {x.upper() for x in lifecycles}:
            continue
        last_v = str(details.get("last_verdict") or "").lower()
        if not include_false_positives and last_v in ("reject", "false_positive", "ложная"):
            continue
        if not include_no_data and (
            d.code in ("CAMERA_COVERAGE_GAP", "NO_DATA") or sk in ("NO_DATA", "CAMERA_COVERAGE_GAP")
        ):
            continue
        filtered.append(d)

    findings: list[dict[str, Any]] = []
    for d in filtered:
        try:
            findings.append(
                build_finding_report_section(
                    db,
                    project_id,
                    d.id,
                    max_frames=max_frames_per_finding,
                    include_all_frames=include_all_frames or detail == "full",
                )
            )
        except ValueError:
            continue

    def count(pred) -> int:
        return sum(1 for f in findings if pred(f))

    summary = {
        "total": len(findings),
        "open": count(lambda f: (f.get("lifecycle") or "").upper() in ("OPEN", "ACKNOWLEDGED", "")),
        "confirmed_by_specialist": count(
            lambda f: str(f.get("last_verdict") or "").lower() in ("confirm", "confirmed")
        ),
        "rejected_false_positive": count(
            lambda f: str(f.get("last_verdict") or "").lower() in ("reject", "false_positive")
        ),
        "no_data": count(
            lambda f: f.get("code") in ("CAMERA_COVERAGE_GAP", "NO_DATA")
            or f.get("signal_kind") in ("NO_DATA", "CAMERA_COVERAGE_GAP")
        ),
        "cv_verified": count(lambda f: f.get("signal_kind") == "CV_VERIFIED_FINDING"),
        "by_severity": {},
        "by_match_status": {},
    }
    for f in findings:
        sev = str(f.get("severity") or "medium")
        summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
        ms = str(f.get("match_status") or "UNMATCHED")
        summary["by_match_status"][ms] = summary["by_match_status"].get(ms, 0) + 1

    sch = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == project_id, ScheduleVersion.is_active.is_(True))
        .order_by(ScheduleVersion.id.desc())
        .first()
    )

    generated_at = datetime.utcnow().isoformat() + "Z"
    return {
        "report_type": "project",
        "project": _project_card(project),
        "period": {"date_from": date_from, "date_to": date_to},
        "filters": {
            "include_false_positives": include_false_positives,
            "include_no_data": include_no_data,
            "lifecycles": lifecycles,
            "detail": detail,
            "max_frames_per_finding": max_frames_per_finding,
            "include_all_frames": include_all_frames,
        },
        "generated_at": generated_at,
        "author": author or "plansight",
        "schedule_version_id": sch.id if sch else None,
        "summary": summary,
        "findings": findings if detail != "brief" else [],
        "registry": [
            {
                "finding_id": f["finding_id"],
                "code": f.get("code"),
                "lifecycle": f.get("lifecycle"),
                "severity": f.get("severity"),
                "match_status": f.get("match_status"),
                "schedule_item_name": (f.get("schedule_item") or {}).get("name")
                if f.get("match_status") == "ACCEPTED"
                else None,
                "zone": (f.get("zone") or {}).get("zone_key") or (f.get("zone") or {}).get("name"),
                "last_verdict": f.get("last_verdict"),
                "evidence_frames": len(f.get("frames") or []),
                "explanation_ru": (f.get("explanation_ru") or "")[:240],
            }
            for f in findings
        ],
        "disclaimer": (
            "Настоящий отчёт носит информационно-аналитический характер. Он не заменяет предусмотренные "
            "законодательством и контрактом документы о приёмке, экспертизу результатов исполнения контракта, "
            "строительный контроль и решения уполномоченных лиц. Правовые последствия определяются "
            "уполномоченными лицами с учётом условий контракта и применимого законодательства."
        ),
        "methodology_note": (
            "Автоматическое предупреждение или отсутствие объекта на кадре сами по себе не устанавливают "
            "нарушение контракта или сроков. Связь с работой КСГ до подтверждения специалистом — гипотеза. "
            "Отчёт сформирован из сохранённых evidence без повторного CV inference."
        ),
    }


def build_single_finding_report_dto(
    db: Session,
    project_id: int,
    deviation_id: int,
    *,
    include_all_frames: bool = True,
    author: str | None = None,
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if not project:
        raise ValueError("project not found")
    section = build_finding_report_section(
        db,
        project_id,
        deviation_id,
        max_frames=12,
        include_all_frames=include_all_frames,
    )
    sch = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == project_id, ScheduleVersion.is_active.is_(True))
        .order_by(ScheduleVersion.id.desc())
        .first()
    )
    return {
        "report_type": "finding",
        "project": _project_card(project),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "author": author or "plansight",
        "schedule_version_id": sch.id if sch else None,
        "finding": section,
        "disclaimer": section.get("disclaimer"),
        "methodology_note": (
            "Документ самодостаточен: данные из сохранённого evidence и Decision Trace. "
            "Повторный inference не выполнялся. Автоматический сигнал не устанавливает нарушение "
            "законодательства или контракта; решение принимает уполномоченное лицо."
        ),
    }
