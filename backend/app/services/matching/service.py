from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import MatchReason
from app.db.models import Camera, CameraZoneBinding, ScheduleDependency, ScheduleItem, ScheduleItemState
from app.services.activity.service import calendar_prior
from app.services.schedule.building import guess_building, parse_building_from_text
from app.services.schedule.service import list_candidates


def _is_verified_binding(bind: CameraZoneBinding | None) -> bool:
    if bind is None:
        return False
    status = (getattr(bind, "binding_status", None) or "").upper()
    source = (getattr(bind, "binding_source", None) or "").lower()
    return status == "VERIFIED" or source in ("human_verified", "imported_verified")


def _building_exact_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.strip().lower() == b.strip().lower()


def _building_soft_match(a: str | None, b: str | None) -> bool:
    """Префиксное/каноническое совпадение (К1 ↔ Корпус 1…). Только soft-candidate, не ACCEPTED."""
    if not a or not b:
        return False
    if _building_exact_match(a, b):
        return True
    na = guess_building(a) or parse_building_from_text(a).normalized
    nb = guess_building(b) or parse_building_from_text(b).normalized
    if na and nb and na == nb:
        return True
    if na and nb and (na.startswith(nb) or nb.startswith(na)):
        return True
    return False


def _resolve_zone_binding(
    db: Session,
    camera: Camera | None,
    *,
    visual_zone_key: str | None,
    building_override: str | None,
) -> tuple[str | None, bool]:
    """Возвращает (building_filter, verified_gate).

    VERIFIED binding → жёсткий корпус, fallback на другой корпус запрещён.
    """
    if camera is None:
        return building_override, False
    key = visual_zone_key or "WHOLE_FRAME"
    bind = (
        db.query(CameraZoneBinding)
        .filter(
            CameraZoneBinding.camera_id == camera.id,
            CameraZoneBinding.visual_zone_key == key,
        )
        .order_by(CameraZoneBinding.id.desc())
        .first()
    )
    if bind and bind.building and _is_verified_binding(bind):
        return bind.building, True
    if building_override:
        # Переопределение без verified binding — мягкий hint
        return building_override, False
    if bind and bind.building:
        return bind.building, False
    return camera.building_hint, False


def _bound_building(
    db: Session, camera: Camera | None, *, building_override: str | None = None
) -> str | None:
    b, _ = _resolve_zone_binding(
        db, camera, visual_zone_key="WHOLE_FRAME", building_override=building_override
    )
    return b


def location_compatibility(
    db: Session,
    item: ScheduleItem,
    camera: Camera | None,
    *,
    building_override: str | None = None,
    verified_gate: bool = False,
) -> tuple[float, list[str]]:
    """Совместимость корпуса.

    exact → полный score;
    soft (К1↔Корпус…) → SOFT_LOCATION_CANDIDATE, без авто-ACCEPTED при нескольких детях;
    VERIFIED gate + mismatch → AMBIGUOUS / низкий score.
    """
    reasons: list[str] = []
    bound = building_override or _bound_building(db, camera, building_override=building_override)
    if not item.building:
        reasons.append(MatchReason.LOCATION_UNKNOWN.value)
        return 0.75, reasons
    if camera is None or not bound:
        reasons.append(MatchReason.LOCATION_UNKNOWN.value)
        penalty = float(
            get_settings().section("engine").get("matching", {}).get("location_unknown_penalty", 0.35)
        )
        return max(0.2, 1.0 - penalty), reasons
    if _building_exact_match(item.building, bound):
        return 1.0, reasons
    if (not verified_gate) and _building_soft_match(item.building, bound):
        reasons.append(MatchReason.SOFT_LOCATION_CANDIDATE.value)
        return 0.55, reasons
    reasons.append(MatchReason.AMBIGUOUS_LOCATION.value)
    return 0.15, reasons


def temporal_compatibility(item: ScheduleItem, at: datetime) -> tuple[float, list[str]]:
    score = calendar_prior(item.planned_start, item.planned_finish, at)
    reasons = [
        MatchReason.TEMPORAL_OK.value if score >= 0.4 else MatchReason.TEMPORAL_WEAK.value
    ]
    return score, reasons


def sequence_compatibility(
    db: Session,
    item: ScheduleItem,
    at: datetime,
) -> tuple[float, list[str]]:
    """Флаг SEQUENCE_OK только при загруженных deps.

    FS: предшественник «готов» по плану (finish+lag ≤ at) ИЛИ есть подтверждённое
    завершение (ui_status LIKELY_FINISH/HUMAN_CONFIRMED). Одна лишь активность
    предшественника НЕ даёт SEQUENCE_OK для finish-to-start.
    """
    deps = (
        db.query(ScheduleDependency)
        .filter(ScheduleDependency.successor_item_id == item.id)
        .all()
    )
    if not deps:
        return 1.0, []

    ok = 0
    plan_only = False
    for dep in deps:
        pred = db.get(ScheduleItem, dep.predecessor_item_id)
        if pred is None:
            continue
        state = (
            db.query(ScheduleItemState)
            .filter(
                ScheduleItemState.schedule_item_id == pred.id,
                ScheduleItemState.schedule_version_id == item.schedule_version_id,
            )
            .one_or_none()
        )
        status = (state.ui_status if state else "") or ""
        finished_confirmed = status in ("LIKELY_FINISH", "HUMAN_CONFIRMED", "CONFIRMED_COMPLETED")
        lag = timedelta(minutes=int(dep.lag_minutes or 0))
        link = (dep.link_type or "FS").upper()
        if link == "FS":
            plan_ready = at >= (pred.planned_finish + lag)
            if finished_confirmed:
                ok += 1
            elif plan_ready:
                ok += 1
                plan_only = True
        elif link == "SS":
            if at >= (pred.planned_start + lag) or finished_confirmed:
                ok += 1
                if not finished_confirmed:
                    plan_only = True
        else:
            if finished_confirmed:
                ok += 1

    if ok == 0 or ok < len(deps):
        return 1.0, []
    reasons = [MatchReason.SEQUENCE_OK.value]
    if plan_only:
        reasons.append("SEQUENCE_PLAN_ONLY")
    return 1.08, reasons


def rank_schedule_items(
    db: Session,
    *,
    project_id: int,
    work_type_id: int,
    camera_id: int,
    at: datetime,
    building_override: str | None = None,
    visual_zone_key: str | None = None,
) -> list[dict[str, Any]]:
    """Нормировка: N кандидатов + ровно один UNMATCHED (+ OTHER при усечении top_n).

    Баллы — uncalibrated_score, не калиброванные вероятности.
    VERIFIED zone→building: жёсткий gate, без fallback на чужой корпус.
    Soft location (К1↔Корпус) — только CANDIDATE, не ACCEPTED при нескольких детях.
    """
    cfg = get_settings().section("engine").get("matching") or {}
    camera = db.get(Camera, camera_id)
    filter_building, verified_gate = _resolve_zone_binding(
        db,
        camera,
        visual_zone_key=visual_zone_key,
        building_override=building_override,
    )
    bound = filter_building or (camera.building_hint if camera else None)

    candidates = list_candidates(
        db,
        project_id,
        work_type_id,
        at,
        building=filter_building if verified_gate else None,
        before_days=int(cfg.get("before_days", 7)),
        after_days=int(cfg.get("after_days", 7)),
    )
    if verified_gate and filter_building:
        # Жёсткий gate: только exact building; пусто → UNMATCHED, без cross-building
        candidates = [
            c for c in candidates if c.building and _building_exact_match(c.building, filter_building)
        ]
    elif filter_building and not verified_gate:
        # Неподтверждённый hint: предпочитаем soft-совпадения, но не режем пул до нуля
        soft = [c for c in candidates if c.building and _building_soft_match(c.building, filter_building)]
        if soft:
            candidates = soft
        # Запасной вариант без корпуса — только CANDIDATE (accept gate ниже не пустит soft multi)
    elif bound and not filter_building:
        same = [c for c in candidates if c.building and _building_soft_match(c.building, bound)]
        if same:
            candidates = same

    scored: list[dict[str, Any]] = []
    min_temp = float(cfg.get("min_temporal_score", 0.15))
    for item in candidates:
        reasons: list[str] = [MatchReason.COMPATIBLE_TYPE.value]
        if visual_zone_key:
            reasons.append(f"ZONE:{visual_zone_key}")
        if verified_gate:
            reasons.append("VERIFIED_BUILDING_GATE")
        temp_score, temp_reasons = temporal_compatibility(item, at)
        if temp_score < min_temp:
            continue
        reasons.extend(temp_reasons)
        loc_score, loc_reasons = location_compatibility(
            db,
            item,
            camera,
            building_override=filter_building or building_override,
            verified_gate=verified_gate,
        )
        reasons.extend(loc_reasons)
        seq_score, seq_reasons = sequence_compatibility(db, item, at)
        reasons.extend(seq_reasons)
        score = 1.0 * temp_score * loc_score * seq_score
        scored.append(
            {
                "schedule_item_id": item.id,
                "external_id": item.external_id,
                "raw_name": item.raw_name,
                "building": item.building,
                "project_object_id": getattr(item, "project_object_id", None),
                "score": score,
                "reason_codes": reasons,
                "is_unmatched": False,
                "is_other": False,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    ambiguous_delta = float(cfg.get("ambiguous_delta", 0.08))
    force_ambiguous = False
    if len(scored) >= 2:
        buildings = {c.get("building") for c in scored[:5] if c.get("building")}
        if (
            abs(scored[0]["score"] - scored[1]["score"]) <= ambiguous_delta
            and len(buildings) >= 2
            and not verified_gate
        ):
            force_ambiguous = True
            for c in scored:
                if MatchReason.AMBIGUOUS_LOCATION.value not in c["reason_codes"]:
                    c["reason_codes"].append(MatchReason.AMBIGUOUS_LOCATION.value)

    unmatched_floor = float(cfg.get("unmatched_floor", 0.12))
    unmatched = {
        "schedule_item_id": None,
        "external_id": None,
        "raw_name": "UNMATCHED",
        "building": None,
        "score": unmatched_floor
        if not force_ambiguous
        else max(unmatched_floor, scored[0]["score"] if scored else unmatched_floor),
        "reason_codes": [MatchReason.UNMATCHED.value]
        + ([MatchReason.AMBIGUOUS_LOCATION.value] if force_ambiguous else [])
        + (["VERIFIED_BUILDING_GATE"] if verified_gate else []),
        "is_unmatched": True,
        "is_other": False,
    }

    pool = scored + [unmatched]
    total = sum(max(0.0, c["score"]) for c in pool) or 1.0
    for c in pool:
        c["prob"] = max(0.0, c["score"]) / total
        c["score_kind"] = "uncalibrated_score"

    pool.sort(key=lambda x: x["prob"], reverse=True)
    top_n = int(cfg.get("top_n", 5))
    subject = [c for c in pool if not c.get("is_unmatched")]
    unmatched_row = next(c for c in pool if c.get("is_unmatched"))
    head_subjects = subject[:top_n]
    tail = subject[top_n:]
    head = list(head_subjects)
    head.append(unmatched_row)
    if tail:
        other_prob = sum(c["prob"] for c in tail)
        head.append(
            {
                "schedule_item_id": None,
                "external_id": None,
                "raw_name": "OTHER",
                "building": None,
                "score": other_prob,
                "prob": other_prob,
                "score_kind": "uncalibrated_score",
                "reason_codes": ["OTHER_TRUNCATED"],
                "is_unmatched": False,
                "is_other": True,
            }
        )
    s = sum(c["prob"] for c in head) or 1.0
    for c in head:
        c["prob"] = c["prob"] / s

    if force_ambiguous:
        for c in head:
            if not c.get("is_unmatched") and not c.get("is_other"):
                c["assignment_blocked"] = True
                c["assignment_status"] = "AMBIGUOUS"
            elif c.get("is_unmatched"):
                c["assignment_status"] = "UNASSIGNED"
    else:
        for c in head:
            if c.get("is_unmatched"):
                c["assignment_status"] = "UNASSIGNED"
            elif c.get("is_other"):
                c["assignment_status"] = "OTHER"
            else:
                c["assignment_status"] = "CANDIDATE"

    for i, c in enumerate(head, start=1):
        c["rank"] = i
        c["match_score"] = float(c.get("score") or 0)
        c["display_weight"] = float(c.get("prob") or 0)
        c["verified_building_gate"] = verified_gate

    # Гейт ACCEPTED после ранжирования
    accept_min = float(cfg.get("accept_min_raw_score", 0.30))
    accept_margin = float(cfg.get("accept_min_margin", 0.10))
    max_unmatched = float(cfg.get("accept_max_unmatched_weight", 0.45))
    subjects = [
        c for c in head if c.get("schedule_item_id") and not c.get("is_unmatched") and not c.get("is_other")
    ]
    unmatched_w = next((float(c.get("prob") or 0) for c in head if c.get("is_unmatched")), 0.0)
    top = subjects[0] if subjects else None
    second = subjects[1] if len(subjects) > 1 else None
    accepted = False
    if top and not force_ambiguous and MatchReason.AMBIGUOUS_LOCATION.value not in (
        top.get("reason_codes") or []
    ):
        reasons_top = top.get("reason_codes") or []
        soft = MatchReason.SOFT_LOCATION_CANDIDATE.value in reasons_top
        soft_peers = [
            c
            for c in subjects
            if MatchReason.SOFT_LOCATION_CANDIDATE.value in (c.get("reason_codes") or [])
        ]
        # Мягкая локация при нескольких корпусах-детях — не ACCEPTED
        soft_blocks = soft and len({c.get("building") for c in soft_peers}) >= 2
        # Неподтверждённый hint без exact — не ACCEPTED
        hint_only = (not verified_gate) and soft
        margin_ok = True
        if second is not None:
            margin_ok = float(top.get("score") or 0) - float(second.get("score") or 0) >= accept_margin
        if (
            float(top.get("score") or 0) >= accept_min
            and margin_ok
            and unmatched_w <= max_unmatched
            and not soft_blocks
            and not hint_only
        ):
            accepted = True
            top["assignment_status"] = "ACCEPTED"
            top["assignment_blocked"] = False
    for c in head:
        if c.get("is_unmatched"):
            c["assignment_status"] = c.get("assignment_status") or "UNASSIGNED"
            continue
        if c.get("is_other"):
            c["assignment_status"] = "OTHER"
            continue
        if c is top and accepted:
            continue
        if force_ambiguous or MatchReason.AMBIGUOUS_LOCATION.value in (c.get("reason_codes") or []):
            c["assignment_blocked"] = True
            c["assignment_status"] = "AMBIGUOUS"
        elif not accepted:
            c["assignment_blocked"] = True
            c["assignment_status"] = c.get("assignment_status") or "REJECTED"
    return head


def explain_match(match: dict[str, Any]) -> str:
    reasons = ", ".join(match.get("reason_codes") or [])
    name = match.get("raw_name") or "UNMATCHED"
    return f"{name}: {reasons}" if reasons else str(name)
