from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    ActivityHypothesis,
    Camera,
    Deviation,
    Frame,
    ScheduleItem,
    ScheduleMatch,
    ScheduleVersion,
)
from app.services.schedule.service import get_active_schedule, list_schedule_items


# Коды V2 (стабильные); UI переводит на русский
CODE_POSSIBLE_LATE_START = "POSSIBLE_LATE_START"
CODE_UNCONFIRMED_ACTIVITY = "UNCONFIRMED_ACTIVITY"
CODE_POSSIBLE_PAUSE = "POSSIBLE_PAUSE"
CODE_WORK_AFTER_PLAN = "WORK_AFTER_PLAN"
CODE_AMBIGUOUS_ASSIGNMENT = "AMBIGUOUS_ASSIGNMENT"
CODE_CAMERA_COVERAGE_GAP = "CAMERA_COVERAGE_GAP"
CODE_REQUIRED_EQUIPMENT_GAP = "REQUIRED_EQUIPMENT_GAP"
CODE_EQUIPMENT_COMPOSITION_ANOMALY = "EQUIPMENT_COMPOSITION_ANOMALY"
CODE_UNEXPECTED_EQUIPMENT = "UNEXPECTED_EQUIPMENT_IN_ZONE"
CODE_NEEDS_CAMERA_SETUP = "NEEDS_CAMERA_SETUP"
# Устаревшие алиасы в enums для совместимости API
CODE_LEGACY_LATE = "LATE_START_RISK"
CODE_LEGACY_NOT_CONF = "WORK_NOT_CONFIRMED"
CODE_LEGACY_AMBIG = "AMBIGUOUS_MATCH"

TEMPORAL_FINDING_CODES = frozenset(
    {
        CODE_POSSIBLE_LATE_START,
        CODE_UNCONFIRMED_ACTIVITY,
        CODE_POSSIBLE_PAUSE,
        CODE_WORK_AFTER_PLAN,
        "EARLY_START",
        "LOW_ACTIVITY",
    }
)


def _incident_key(item_id: int, code: str, schedule_version_id: int | None) -> str:
    """Жизненный цикл инцидента — не ежедневный дубль."""
    return f"{schedule_version_id or 0}:{item_id}:{code}"


def _coverage_in_window(
    db: Session,
    project_id: int,
    start: datetime,
    end: datetime,
    camera_ids: list[int] | None = None,
) -> tuple[int, bool]:
    cfg = get_settings().section("engine").get("deviations") or {}
    need = int(cfg.get("min_coverage_in_window", cfg.get("min_coverage_frames", 2)))
    q = db.query(Frame).filter(
        Frame.project_id == project_id,
        Frame.captured_at.isnot(None),
        Frame.captured_at >= start,
        Frame.captured_at <= end,
        Frame.image_quality != "UNUSABLE",
    )
    if camera_ids:
        q = q.filter(Frame.camera_id.in_(camera_ids))
    n = q.count()
    return n, n >= need


def _frame_ids_for_hypothesis(db: Session, hyp: ActivityHypothesis) -> list[int]:
    """Гипотеза → InferenceRun.frame_id (нельзя подставлять hyp.id как evidence)."""
    from app.db.models import InferenceRun

    run = db.get(InferenceRun, hyp.inference_run_id)
    if run and run.frame_id:
        return [int(run.frame_id)]
    return []


def _frame_is_photo_archive(db: Session, frame_id: int | None) -> bool:
    """Режим PHOTO_ARCHIVE / назначенные метки времени — temporal-утверждения запрещены."""
    if not frame_id:
        return False
    fr = db.get(Frame, int(frame_id))
    if fr is None:
        return False
    try:
        q = json.loads(fr.quality_json or "{}")
    except Exception:
        q = {}
    if q.get("source_kind") == "PHOTO_ARCHIVE":
        return True
    if q.get("not_claiming_continuous_fixed_camera"):
        return True
    if str(q.get("timestamp_origin") or "").startswith("DEMO_ASSIGNED"):
        return True
    return False


def _hyp_is_photo_archive(db: Session, hyp: ActivityHypothesis | None) -> bool:
    if hyp is None:
        return False
    from app.db.models import InferenceRun

    run = db.get(InferenceRun, hyp.inference_run_id) if hyp.inference_run_id else None
    return _frame_is_photo_archive(db, run.frame_id if run else None)


def _provenance_block(
    db: Session,
    *,
    hyp: ActivityHypothesis | None,
    item: ScheduleItem | None,
    evid: list[int],
) -> dict[str, Any]:
    """Иммутабельная цепочка finding → match → hyp → frame (V7.4)."""
    match_id = None
    assignment_status = None
    if hyp is not None and item is not None:
        m = (
            db.query(ScheduleMatch)
            .filter(
                ScheduleMatch.hypothesis_id == hyp.id,
                ScheduleMatch.schedule_item_id == item.id,
                ScheduleMatch.is_unmatched.is_(False),
            )
            .order_by(ScheduleMatch.rank.asc())
            .first()
        )
        if m is not None:
            match_id = int(m.id)
            reasons = json.loads(m.reason_codes_json or "[]")
            if "AMBIGUOUS_LOCATION" in reasons or "AMBIGUOUS" in reasons:
                assignment_status = "AMBIGUOUS"
            else:
                assignment_status = "CANDIDATE"
    return {
        "source_hypothesis_id": int(hyp.id) if hyp is not None else None,
        "source_schedule_match_id": match_id,
        "source_frame_ids": list(evid),
        "source_zone_id": int(hyp.visual_zone_id) if hyp is not None and hyp.visual_zone_id else None,
        "source_camera_id": int(hyp.camera_id) if hyp is not None else None,
        "assignment_status": assignment_status,
    }


def _temporal_overlap(
    at: datetime | None,
    planned_start: datetime | None,
    planned_finish: datetime | None,
    *,
    before: timedelta,
    after: timedelta,
) -> bool:
    """Кадр/гипотеза относится к работе только если время в окне плана ± допуски."""
    if at is None or planned_start is None or planned_finish is None:
        return False
    return (planned_start - before) <= at <= (planned_finish + after)


def _match_time_window() -> tuple[timedelta, timedelta]:
    """Окно совпадения кадра с работой: matching.before/after_days (по умолчанию ±7)."""
    match_cfg = get_settings().section("engine").get("matching") or {}
    return (
        timedelta(days=int(match_cfg.get("before_days", 7))),
        timedelta(days=int(match_cfg.get("after_days", 7))),
    )


def _cameras_bound_to_building(
    db: Session,
    project_id: int,
    building: str | None,
    *,
    verified_only: bool = True,
) -> list[int]:
    """Камеры с привязкой к корпусу.

    По умолчанию только VERIFIED zone binding — hint не даёт coverage contract (V7.4).
    """
    if not building:
        return []
    from app.db.models import CameraZoneBinding

    out: set[int] = set()
    binds = (
        db.query(CameraZoneBinding)
        .filter(
            CameraZoneBinding.project_id == project_id,
            CameraZoneBinding.building.isnot(None),
        )
        .all()
    )
    for b in binds:
        if not b.building or b.building.lower() != building.lower():
            continue
        status = (getattr(b, "binding_status", None) or "").upper()
        source = (getattr(b, "binding_source", None) or "").lower()
        verified = status == "VERIFIED" or source in ("human_verified", "imported_verified")
        if verified_only and not verified:
            continue
        if not verified_only or verified:
            out.add(int(b.camera_id))
    if not verified_only:
        for c in db.query(Camera).filter(Camera.project_id == project_id).all():
            if c.building_hint and c.building_hint.lower() == building.lower():
                out.add(int(c.id))
    return sorted(out)


def _effective_matches_for_item(
    db: Session,
    item: ScheduleItem,
    hyps: list[ActivityHypothesis],
) -> tuple[float, ActivityHypothesis | None, bool, list[int]]:
    """Только matches с schedule_item_id == item.id И временным overlap.

    P0-03: UNMATCHED сам по себе НЕ делает назначение неоднозначным.
    ambiguous только при явном AMBIGUOUS_LOCATION у match этой строки во времени.
    evidence_ids = Frame.id (не hypothesis.id) — только кадры в окне работы.
    """
    best = 0.0
    best_h = None
    ambiguous = False
    evidence_ids: list[int] = []
    from app.db.models import ScheduleVersion

    ver = db.get(ScheduleVersion, item.schedule_version_id)
    pid = ver.project_id if ver else None
    # Статус VERIFIED зона→корпус: адресная привязка — пропускаем AMBIGUOUS_ASSIGNMENT
    verified_cams = _cameras_bound_to_building(db, pid, item.building) if pid and item.building else []
    has_verified_bind = bool(verified_cams)
    before, after = _match_time_window()

    for h in hyps:
        at = h.interval_start or h.interval_end
        if not _temporal_overlap(at, item.planned_start, item.planned_finish, before=before, after=after):
            continue
        matches = (
            db.query(ScheduleMatch)
            .filter(ScheduleMatch.hypothesis_id == h.id)
            .order_by(ScheduleMatch.rank.asc())
            .all()
        )
        for m in matches:
            # Только эта строка КСГ — не весь work_type по проекту
            if m.schedule_item_id != item.id or m.is_unmatched:
                continue
            reasons = json.loads(m.reason_codes_json or "[]")
            loc_ambiguous = "AMBIGUOUS_LOCATION" in reasons or "AMBIGUOUS" in reasons
            if loc_ambiguous and not has_verified_bind:
                ambiguous = True
            score = float(h.activity_score) * float(m.score)
            if score >= best:
                best = score
                best_h = h
            for fid in _frame_ids_for_hypothesis(db, h):
                if fid not in evidence_ids:
                    evidence_ids.append(fid)
    return best, best_h, ambiguous, evidence_ids


def _upsert(
    db: Session,
    *,
    project_id: int,
    schedule_version_id: int | None,
    item_id: int | None,
    code: str,
    heuristic_score: float,
    event_key: str,
    details: dict[str, Any],
    evidence_ids: list[int],
    now: datetime,
) -> Deviation:
    row = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project_id,
            Deviation.event_key == event_key,
        )
        .one_or_none()
    )
    # V7.1: CV-находки с разрешимыми кадрами обязаны указать signal_kind
    details = dict(details or {})
    # V7.4: provenance immutable — не перезаписывать source_* при повторном upsert
    if row is not None:
        try:
            prev = json.loads(row.details_json or "{}")
        except Exception:
            prev = {}
        for k in (
            "source_hypothesis_id",
            "source_schedule_match_id",
            "source_frame_ids",
            "source_zone_id",
            "source_camera_id",
            "assignment_status",
        ):
            if prev.get(k) is not None and details.get(k) is None:
                details[k] = prev[k]
    if evidence_ids and not details.get("signal_kind"):
        cv_codes = {
            CODE_REQUIRED_EQUIPMENT_GAP,
            CODE_EQUIPMENT_COMPOSITION_ANOMALY,
            CODE_UNEXPECTED_EQUIPMENT,
            CODE_CAMERA_COVERAGE_GAP,
            CODE_UNCONFIRMED_ACTIVITY,
            CODE_POSSIBLE_PAUSE,
            CODE_WORK_AFTER_PLAN,
            "EARLY_START",
            "LOW_ACTIVITY",
        }
        if code in cv_codes:
            # Только если ids похожи на PK кадров (не id гипотез)
            from app.db.models import Frame as _Frame

            frame_hits = 0
            for x in evidence_ids:
                try:
                    fr = db.get(_Frame, int(x))
                except (TypeError, ValueError):
                    fr = None
                if fr is not None and fr.project_id == project_id:
                    frame_hits += 1
            if frame_hits:
                details["signal_kind"] = "CV_VERIFIED_FINDING"
    payload = json.dumps(details, ensure_ascii=False)
    evid = json.dumps(evidence_ids, ensure_ascii=False)
    if row is None:
        row = Deviation(
            project_id=project_id,
            schedule_item_id=item_id,
            schedule_version_id=schedule_version_id,
            code=code,
            risk_score=heuristic_score,  # backward compat
            heuristic_score=heuristic_score,
            status="open",
            lifecycle="OPEN",
            event_key=event_key,
            first_seen=now,
            last_seen=now,
            evidence_ids_json=evid,
            details_json=payload,
        )
        db.add(row)
    else:
        if row.lifecycle == "RESOLVED":
            # не воскрешаем без явного reopen; только обновляем last_seen в details
            return row
        row.last_seen = now
        row.heuristic_score = heuristic_score
        row.risk_score = heuristic_score
        row.details_json = payload
        row.evidence_ids_json = evid
        row.schedule_item_id = item_id
        row.schedule_version_id = schedule_version_id
        if row.lifecycle not in ("ACKNOWLEDGED", "RESOLVED"):
            row.lifecycle = "OPEN"
            row.status = "open"
    return row


def detect_deviations(db: Session, project_id: int, as_of: datetime | None = None) -> list[Deviation]:
    """Операция upsert по event_key. Не wipe. as_of режет будущие гипотезы/кадры."""
    cfg = get_settings().section("engine").get("deviations") or {}
    as_of = as_of or datetime.utcnow()
    min_act = float(cfg.get("min_activity_for_deviation", 0.45))
    grace = timedelta(hours=float(cfg.get("late_start_grace_hours", 6)))
    early = timedelta(hours=float(cfg.get("early_start_hours", 6)))
    after = timedelta(hours=float(cfg.get("work_after_plan_hours", 2)))
    gap_min_frames = int(cfg.get("equipment_gap_min_frames", 3))

    version = get_active_schedule(db, project_id)
    items = list_schedule_items(db, project_id)
    cameras = db.query(Camera).filter(Camera.project_id == project_id).all()
    camera_ids = [c.id for c in cameras] or [-1]
    vid = version.id if version else None

    # только гипотезы этого проекта, не из будущего относительно as_of
    hyps = (
        db.query(ActivityHypothesis)
        .join(Camera, Camera.id == ActivityHypothesis.camera_id)
        .filter(
            Camera.project_id == project_id,
            ActivityHypothesis.camera_id.in_(camera_ids),
            ActivityHypothesis.interval_start <= as_of,
        )
        .order_by(ActivityHypothesis.id.desc())
        .limit(500)
        .all()
    )

    from app.services.knowledge_base.service import load_kb

    kb = load_kb()
    touched: list[Deviation] = []

    for item in items:
        mode = getattr(item, "observability_mode", None) or "UNKNOWN"
        if mode == "NOT_OBSERVABLE" or getattr(item, "is_milestone", False) or getattr(item, "is_summary", False):
            continue

        score, hyp, ambiguous, evid = _effective_matches_for_item(db, item, hyps)

        # окно покрытия не выходит за as_of — нет будущих кадров
        win_start = item.planned_start - grace
        win_end = min(as_of, item.planned_finish + after)
        if win_end < win_start:
            win_end = as_of
        # камеры с VERIFIED zone binding на корпус (hint ≠ coverage contract)
        bound_cams = _cameras_bound_to_building(db, project_id, item.building, verified_only=True)
        has_coverage_contract = bool(bound_cams)
        cov_cams = bound_cams
        cov_n, coverage_ok = (0, False)
        if has_coverage_contract:
            cov_n, coverage_ok = _coverage_in_window(db, project_id, win_start, win_end, cov_cams)
        archive_hyp = _hyp_is_photo_archive(db, hyp)
        prov = _provenance_block(db, hyp=hyp, item=item, evid=evid)

        ambig_key = _incident_key(item.id, CODE_AMBIGUOUS_ASSIGNMENT, vid)
        if ambiguous and mode in ("DIRECT", "INDIRECT", "UNKNOWN"):
            touched.append(
                _upsert(
                    db,
                    project_id=project_id,
                    schedule_version_id=vid,
                    item_id=item.id,
                    code=CODE_AMBIGUOUS_ASSIGNMENT,
                    heuristic_score=0.5,
                    event_key=ambig_key,
                    details={
                        "note": "несколько равноправных строк/корпусов без привязки камеры",
                        "legacy_code": CODE_LEGACY_AMBIG,
                        "limitations": [
                            "Без подтверждённой привязки камеры к корпусу назначение работы запрещено"
                        ],
                        **{k: v for k, v in prov.items() if v is not None},
                    },
                    evidence_ids=evid,
                    now=as_of,
                )
            )
        else:
            # Снять ложный fan-out: кадр другой даты больше не держит AMBIGUOUS на этой строке
            stale = (
                db.query(Deviation)
                .filter(
                    Deviation.project_id == project_id,
                    Deviation.event_key == ambig_key,
                    Deviation.lifecycle == "OPEN",
                )
                .one_or_none()
            )
            if stale is not None:
                stale.lifecycle = "RESOLVED"
                stale.status = "resolved"
                stale.evidence_ids_json = "[]"
                stale.last_seen = as_of
                touched.append(stale)

        if mode == "DIRECT" and as_of > item.planned_start + grace and not has_coverage_contract:
            key = _incident_key(item.id, CODE_NEEDS_CAMERA_SETUP, vid)
            touched.append(
                _upsert(
                    db,
                    project_id=project_id,
                    schedule_version_id=vid,
                    item_id=item.id,
                    code=CODE_NEEDS_CAMERA_SETUP,
                    heuristic_score=0.25,
                    event_key=key,
                    details={
                        "note": "для работы нет подтверждённой камеры/зоны — нельзя оценивать покрытие",
                        "building": item.building,
                        "limitations": [
                            "Отсутствие настройки наблюдения ≠ срыв работ на площадке"
                        ],
                    },
                    evidence_ids=[],
                    now=as_of,
                )
            )
        elif (
            has_coverage_contract
            and not coverage_ok
            and as_of > item.planned_start + grace
            and mode == "DIRECT"
        ):
            key = _incident_key(item.id, CODE_CAMERA_COVERAGE_GAP, vid)
            touched.append(
                _upsert(
                    db,
                    project_id=project_id,
                    schedule_version_id=vid,
                    item_id=item.id,
                    code=CODE_CAMERA_COVERAGE_GAP,
                    heuristic_score=0.35,
                    event_key=key,
                    details={
                        "note": "недостаточно пригодных кадров в окне — нельзя утверждать срыв",
                        "frames_in_window": cov_n,
                        "as_of": as_of.isoformat(),
                        "limitations": [
                            "Отсутствие кадров не означает отсутствие техники на площадке"
                        ],
                    },
                    evidence_ids=[],
                    now=as_of,
                )
            )
        elif (
            has_coverage_contract
            and coverage_ok
            and as_of > item.planned_start + grace
            and score < min_act
            and mode == "DIRECT"
            and not archive_hyp
        ):
            key = _incident_key(item.id, CODE_POSSIBLE_LATE_START, vid)
            touched.append(
                _upsert(
                    db,
                    project_id=project_id,
                    schedule_version_id=vid,
                    item_id=item.id,
                    code=CODE_POSSIBLE_LATE_START,
                    heuristic_score=0.55,
                    event_key=key,
                    details={
                        "note": "возможный поздний старт при покрытии камерой; не равно «работа не велась»",
                        "planned_start": item.planned_start.isoformat(),
                        "legacy_code": CODE_LEGACY_LATE,
                        "frames_in_window": cov_n,
                        **{k: v for k, v in prov.items() if v is not None},
                    },
                    evidence_ids=evid,
                    now=as_of,
                )
            )
            key2 = _incident_key(item.id, CODE_UNCONFIRMED_ACTIVITY, vid)
            touched.append(
                _upsert(
                    db,
                    project_id=project_id,
                    schedule_version_id=vid,
                    item_id=item.id,
                    code=CODE_UNCONFIRMED_ACTIVITY,
                    heuristic_score=0.4,
                    event_key=key2,
                    details={
                        "note": "запланированная наблюдаемая работа не подтверждена наблюдениями",
                        "legacy_code": CODE_LEGACY_NOT_CONF,
                        **{k: v for k, v in prov.items() if v is not None},
                    },
                    evidence_ids=evid,
                    now=as_of,
                )
            )

        # Код REQUIRED_EQUIPMENT_GAP — скользящее окно у as_of (P0-04 / REG-09)
        if mode == "DIRECT" and item.work_type_id and has_coverage_contract and coverage_ok and cov_n >= gap_min_frames:
            from app.db.models import WorkType

            wt = db.get(WorkType, item.work_type_id)
            if wt:
                lookback_h = float(cfg.get("equipment_gap_lookback_hours", 4))
                gap_start = max(win_start, as_of - timedelta(hours=lookback_h))
                gap_end = min(win_end, as_of)
                gap = _required_equipment_gap(
                    db,
                    work_code=wt.code,
                    kb=kb,
                    camera_ids=cov_cams,
                    win_start=gap_start,
                    win_end=gap_end,
                    as_of=as_of,
                    building=item.building,
                )
                if gap and gap.get("status") == "NEEDS_CAMERA_SETUP":
                    key = _incident_key(item.id, "NEEDS_CAMERA_SETUP", vid)
                    touched.append(
                        _upsert(
                            db,
                            project_id=project_id,
                            schedule_version_id=vid,
                            item_id=item.id,
                            code="NEEDS_CAMERA_SETUP",
                            heuristic_score=0.2,
                            event_key=key,
                            details={
                                "finding": "NEEDS_CAMERA_SETUP",
                                "building": item.building,
                                "hypothesis": "корпус в КСГ есть, но ROI↔корпус не подтверждён — адресный дефицит не выдаём",
                                "limitations": ["нужно подтвердить привязку зоны"],
                                "suggested_check": "подтвердить зону на экране «Камеры и зоны»",
                            },
                            evidence_ids=[],
                            now=as_of,
                        )
                    )
                elif gap and gap.get("missing"):
                    finding_code = gap.get("status") or CODE_REQUIRED_EQUIPMENT_GAP
                    if finding_code not in (
                        CODE_REQUIRED_EQUIPMENT_GAP,
                        CODE_EQUIPMENT_COMPOSITION_ANOMALY,
                    ):
                        finding_code = (
                            CODE_REQUIRED_EQUIPMENT_GAP
                            if gap.get("profile_kind") == "required"
                            else CODE_EQUIPMENT_COMPOSITION_ANOMALY
                        )
                    key = _incident_key(item.id, finding_code, vid)
                    is_required = finding_code == CODE_REQUIRED_EQUIPMENT_GAP
                    touched.append(
                        _upsert(
                            db,
                            project_id=project_id,
                            schedule_version_id=vid,
                            item_id=item.id,
                            code=finding_code,
                            heuristic_score=0.6 if is_required else 0.35,
                            event_key=key,
                            details={
                                "finding": finding_code,
                                "profile_kind": gap.get("profile_kind"),
                                "expected_equipment": gap["expected"],
                                "observed_equipment": gap["observed"],
                                "not_confirmed_equipment": gap["missing"],
                                "covered_interval": [gap_start.isoformat(), gap_end.isoformat()],
                                "lookback_hours": lookback_h,
                                "frames_in_window": gap.get("usable_frames", cov_n),
                                "equipment_coverage": gap.get("equipment_coverage"),
                                "hypothesis": gap.get("hypothesis"),
                                "camera_visual_zone_id": gap.get("zone_key"),
                                "building": item.building,
                                "limitations": [
                                    "Отсутствие на изображениях не доказывает отсутствие техники на всей площадке",
                                    (
                                        "Это возможный дефицит обязательной техники, а не оценка вероятности срыва сроков"
                                        if is_required
                                        else "Состав техники отличается от типового профиля — не утверждение о нехватке обязательной техники"
                                    ),
                                    "Оценка по подтверждённой зоне корпуса; окно — последние часы до контрольной даты",
                                ],
                                "suggested_check": gap.get("suggested_check"),
                                "evidence_frame_ids": gap.get("frame_ids") or [],
                            },
                            evidence_ids=gap.get("frame_ids") or [],
                            now=as_of,
                        )
                    )

        if (
            hyp
            and hyp.interval_start <= as_of
            and hyp.interval_start < item.planned_start - early
            and float(hyp.activity_score) >= min_act
            and not _hyp_is_photo_archive(db, hyp)
        ):
            if hyp.camera_id in (bound_cams or camera_ids):
                key = _incident_key(item.id, "EARLY_START", vid)
                fids = _frame_ids_for_hypothesis(db, hyp)
                touched.append(
                    _upsert(
                        db,
                        project_id=project_id,
                        schedule_version_id=vid,
                        item_id=item.id,
                        code="EARLY_START",
                        heuristic_score=0.5,
                        event_key=key,
                        details={
                            "observed_at": hyp.interval_start.isoformat(),
                            **_provenance_block(db, hyp=hyp, item=item, evid=fids),
                        },
                        evidence_ids=fids,
                        now=as_of,
                    )
                )

        if (
            hyp
            and hyp.interval_end <= as_of
            and hyp.interval_end > item.planned_finish + after
            and float(hyp.activity_score) >= min_act
            and not _hyp_is_photo_archive(db, hyp)
        ):
            key = _incident_key(item.id, CODE_WORK_AFTER_PLAN, vid)
            fids = _frame_ids_for_hypothesis(db, hyp)
            touched.append(
                _upsert(
                    db,
                    project_id=project_id,
                    schedule_version_id=vid,
                    item_id=item.id,
                    code=CODE_WORK_AFTER_PLAN,
                    heuristic_score=0.45,
                    event_key=key,
                    details={
                        "observed_at": hyp.interval_end.isoformat(),
                        **_provenance_block(db, hyp=hyp, item=item, evid=fids),
                    },
                    evidence_ids=fids,
                    now=as_of,
                )
            )

    # Код UNEXPECTED_EQUIPMENT_IN_ZONE — техника в зоне без согласованной работы корпуса
    from app.db.models import CameraVisualZone, Observation as Obs
    from app.db.models import InferenceRun as IR

    zones = (
        db.query(CameraVisualZone)
        .filter(CameraVisualZone.project_id == project_id, CameraVisualZone.status == "active")
        .all()
    )
    for z in zones:
        from app.services.zones.service import building_for_zone

        bld = building_for_zone(db, z.camera_id, z, require_verified=True)
        if not bld:
            continue
        planned_codes = set()
        for item in items:
            if item.building and item.building.lower() == bld.lower() and item.work_type_id:
                from app.db.models import WorkType as WT

                wt = db.get(WT, item.work_type_id)
                if wt and item.planned_start - grace <= as_of <= item.planned_finish + after:
                    planned_codes.add(wt.code)
        allowed_eq: set[str] = set()
        for code in planned_codes:
            for r in kb.rules_for_work(code):
                allowed_eq.add(r.equipment_type)
        if not allowed_eq:
            continue
        frames = (
            db.query(Frame)
            .filter(
                Frame.camera_id == z.camera_id,
                Frame.captured_at.isnot(None),
                Frame.captured_at <= as_of,
                Frame.captured_at >= as_of - timedelta(hours=6),
                Frame.image_quality != "UNUSABLE",
            )
            .order_by(Frame.captured_at.desc())
            .limit(10)
            .all()
        )
        seen: set[str] = set()
        fids: list[int] = []
        for fr in frames:
            run = (
                db.query(IR)
                .filter(IR.frame_id == fr.id, IR.status == "COMPLETED")
                .order_by(IR.id.desc())
                .first()
            )
            if not run:
                continue
            obs = db.query(Obs).filter(Obs.inference_run_id == run.id).one_or_none()
            if not obs:
                continue
            quality = json.loads(obs.quality_json or "{}")
            zvec = (quality.get("zones") or {}).get(z.zone_key) or {}
            for k, v in zvec.items():
                if float(v) > 0:
                    seen.add(k)
            fids.append(fr.id)
        unexpected = sorted(e for e in seen if e not in allowed_eq and not str(e).endswith("_unknown"))
        # Класс truck_unknown у земляных работ слаб — пропускаем unknown
        if not unexpected or not seen:
            continue
        # Только если в зоне есть разрешённая техника (иначе это просто активность площадки)
        if not (seen & allowed_eq):
            continue
        key = f"{vid or 0}:zone:{z.id}:{CODE_UNEXPECTED_EQUIPMENT}"
        touched.append(
            _upsert(
                db,
                project_id=project_id,
                schedule_version_id=vid,
                item_id=None,
                code=CODE_UNEXPECTED_EQUIPMENT,
                heuristic_score=0.45,
                event_key=key,
                details={
                    "finding": CODE_UNEXPECTED_EQUIPMENT,
                    "camera_visual_zone_id": z.zone_key,
                    "building": bld,
                    "unexpected_equipment": unexpected,
                    "observed_equipment": sorted(seen),
                    "allowed_for_planned_works": sorted(allowed_eq),
                    "hypothesis": f"в зоне {z.name} замечена техника вне текущего этапа: {', '.join(unexpected)}",
                    "limitations": [
                        "возможны подъезд/складирование вне производственной операции",
                        "не утверждает нарушение без проверки оператором",
                    ],
                    "suggested_check": "сверить назначение техники и параллельные работы в зоне",
                    "evidence_frame_ids": fids[:10],
                },
                evidence_ids=fids[:10],
                now=as_of,
            )
        )

    db.flush()
    return touched


def _required_equipment_gap(
    db: Session,
    *,
    work_code: str,
    kb,
    camera_ids: list[int],
    win_start: datetime,
    win_end: datetime,
    as_of: datetime,
    building: str | None = None,
) -> dict[str, Any] | None:
    """Требуемый состав техники в подтверждённой зоне корпуса за скользящее окно.

    joint_pattern — кандидат схемы, не норматив. Адресный gap только при VERIFIED binding.
    """
    expected: list[str] = []
    profile_kind = "required"  # required | typical
    # 1) профили Admin/KB в БД (продуктовый источник истины, если есть)
    from app.services.product.catalog_bridge import expected_equipment_for_work

    expected = expected_equipment_for_work(db, work_code)
    if expected:
        profile_kind = "required"
    if not expected:
        for pat in kb.joint_patterns:
            boosts = pat.get("boost_work_types") or []
            if work_code in boosts:
                expected = [str(x) for x in (pat.get("equipment") or [])]
                profile_kind = "typical"
                break
    if not expected:
        # Различие typical ≠ required (V7.4): required → REQUIRED_EQUIPMENT_GAP; typical → COMPOSITION_ANOMALY
        required = [r.equipment_type for r in kb.rules_for_work(work_code) if r.necessity == "required"]
        if required:
            expected = list(dict.fromkeys(required))
            profile_kind = "required"
        else:
            typical = [r.equipment_type for r in kb.rules_for_work(work_code) if r.necessity == "typical"]
            expected = list(dict.fromkeys(typical))
            profile_kind = "typical"
    if len(expected) < 2 and profile_kind == "required":
        return None
    if len(expected) < 1:
        return None

    from app.db.models import CameraZoneBinding, CameraVisualZone, InferenceRun, Observation

    zone_keys: set[str] = set()
    verified_found = False
    if building:
        binds = (
            db.query(CameraZoneBinding)
            .filter(
                CameraZoneBinding.camera_id.in_(camera_ids),
                CameraZoneBinding.building.isnot(None),
            )
            .all()
        )
        for b in binds:
            if not (b.building and b.building.lower() == building.lower()):
                continue
            status = (getattr(b, "binding_status", None) or "PROPOSED").upper()
            source = (getattr(b, "binding_source", None) or "").lower()
            if status == "VERIFIED" or source in ("human_verified", "imported_verified"):
                zone_keys.add(b.visual_zone_key)
                verified_found = True
        for z in (
            db.query(CameraVisualZone)
            .filter(
                CameraVisualZone.camera_id.in_(camera_ids),
                CameraVisualZone.status == "active",
            )
            .all()
        ):
            from app.services.zones.service import building_for_zone

            zb = building_for_zone(db, z.camera_id, z, require_verified=True)
            if zb and zb.lower() == building.lower():
                zone_keys.add(z.zone_key)
                verified_found = True
        if not verified_found:
            return {
                "status": "NEEDS_CAMERA_SETUP",
                "expected": expected,
                "observed": [],
                "missing": [],
                "hypothesis": None,
                "suggested_check": "подтвердить ROI↔корпус",
                "frame_ids": [],
                "zone_key": None,
                "usable_frames": 0,
                "equipment_coverage": {e: "UNKNOWN" for e in expected},
            }

    frames = (
        db.query(Frame)
        .filter(
            Frame.camera_id.in_(camera_ids),
            Frame.captured_at.isnot(None),
            Frame.captured_at >= win_start,
            Frame.captured_at <= win_end,
            Frame.captured_at <= as_of,
            Frame.image_quality != "UNUSABLE",
        )
        .order_by(Frame.captured_at.asc())
        .all()
    )
    if len(frames) < 2:
        return None

    observed: set[str] = set()
    frame_ids: list[int] = []
    used_zone: str | None = None
    per_class_frames: dict[str, int] = {e: 0 for e in expected}
    for fr in frames:
        run = (
            db.query(InferenceRun)
            .filter(InferenceRun.frame_id == fr.id, InferenceRun.status == "COMPLETED")
            .order_by(InferenceRun.id.desc())
            .first()
        )
        if not run:
            continue
        obs = db.query(Observation).filter(Observation.inference_run_id == run.id).one_or_none()
        if not obs:
            continue
        quality = json.loads(obs.quality_json or "{}")
        zones_map = quality.get("zones") or {}
        vec: dict[str, float] = {}
        if zone_keys and zones_map:
            for zk in zone_keys:
                zvec = zones_map.get(zk) or {}
                for k, v in zvec.items():
                    if float(v) > 0:
                        vec[k] = max(vec.get(k, 0.0), float(v))
                        used_zone = zk
        elif zone_keys and not zones_map:
            continue
        elif building and zone_keys:
            continue
        else:
            # без корпуса — whole-frame допустим только как слабый кандидат
            vec = {k: float(v) for k, v in (json.loads(obs.equipment_vector_json or "{}")).items() if float(v) > 0}
        for k, v in vec.items():
            if float(v) > 0:
                observed.add(k)
                if k in per_class_frames:
                    per_class_frames[k] += 1
        if vec:
            frame_ids.append(fr.id)

    if not frame_ids:
        return None

    missing = [e for e in expected if e not in observed]
    if not missing:
        return None
    if not any(e in observed for e in expected):
        return None

    coverage = {}
    for e in expected:
        if per_class_frames.get(e, 0) > 0:
            coverage[e] = "VISIBLE"
        elif frame_ids:
            coverage[e] = "NOT_VISIBLE"
        else:
            coverage[e] = "UNKNOWN"

    hyp_text = (
        f"возможное нарушение согласованного состава"
        + (f" в зоне {used_zone or building}" if (used_zone or building) else "")
        + f": есть {', '.join(sorted(set(expected) & observed) or list(observed))}, "
        f"не подтверждены {', '.join(missing)} "
        f"({len(frame_ids)} пригодных кадров в окне)"
    )
    finding_code = (
        CODE_REQUIRED_EQUIPMENT_GAP
        if profile_kind == "required"
        else CODE_EQUIPMENT_COMPOSITION_ANOMALY
    )
    return {
        "status": finding_code,
        "profile_kind": profile_kind,
        "expected": expected,
        "observed": sorted(observed),
        "missing": missing,
        "hypothesis": hyp_text
        if profile_kind == "required"
        else (
            f"состав техники отличается от типового профиля"
            + (f" в зоне {used_zone or building}" if (used_zone or building) else "")
            + f": не подтверждены {', '.join(missing)}"
        ),
        "suggested_check": f"проверить наличие {', '.join(missing)} и организацию работ",
        "frame_ids": frame_ids[:20],
        "zone_key": used_zone or (next(iter(zone_keys)) if zone_keys else None),
        "usable_frames": len(frame_ids),
        "equipment_coverage": coverage,
    }


def build_daily_summary(db: Session, project_id: int, day: str) -> dict[str, Any]:
    """Параметр day = YYYY-MM-DD — фильтрует кадры/гипотезы/инциденты по этой дате (P0-06 / REG-15)."""
    from datetime import datetime as dt

    try:
        day_start = dt.strptime(day, "%Y-%m-%d")
    except ValueError:
        day_start = dt.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    items = list_schedule_items(db, project_id)
    deviations = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project_id,
            Deviation.lifecycle.in_(["OPEN", "ACKNOWLEDGED"]),
            Deviation.last_seen.isnot(None),
            Deviation.last_seen >= day_start,
            Deviation.last_seen < day_end,
        )
        .all()
    )
    # также OPEN без last_seen но first_seen в день
    extra = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project_id,
            Deviation.lifecycle.in_(["OPEN", "ACKNOWLEDGED"]),
            Deviation.first_seen >= day_start,
            Deviation.first_seen < day_end,
        )
        .all()
    )
    seen_ids = {d.id for d in deviations}
    for d in extra:
        if d.id not in seen_ids:
            deviations.append(d)

    hyps = (
        db.query(ActivityHypothesis)
        .join(Camera, Camera.id == ActivityHypothesis.camera_id)
        .filter(
            Camera.project_id == project_id,
            ActivityHypothesis.interval_start >= day_start,
            ActivityHypothesis.interval_start < day_end,
        )
        .all()
    )
    frames_n = (
        db.query(Frame)
        .filter(
            Frame.project_id == project_id,
            Frame.captured_at >= day_start,
            Frame.captured_at < day_end,
        )
        .count()
    )
    version = get_active_schedule(db, project_id)
    from app.db.models import WorkType

    wt = {w.id: w for w in db.query(WorkType).all()}
    obs_counts: dict[str, int] = {}
    for i in items:
        mode = getattr(i, "observability_mode", None) or "UNKNOWN"
        obs_counts[mode] = obs_counts.get(mode, 0) + 1
    return {
        "date": day,
        "schedule_version_id": version.id if version else None,
        "schedule_items": len(items),
        "observability_coverage": obs_counts,
        "frames_that_day": frames_n,
        "hypotheses": [
            {
                "id": h.id,
                "work_type": wt[h.work_type_id].code if h.work_type_id in wt else None,
                "activity_score": h.activity_score,
                "score_kind": h.score_kind,
                "ui_status": h.ui_status,
                "interval_start": h.interval_start.isoformat() if h.interval_start else None,
            }
            for h in hyps[-100:]
        ],
        "deviations": [
            {
                "id": d.id,
                "code": d.code,
                "schedule_item_id": d.schedule_item_id,
                "heuristic_score": d.heuristic_score if d.heuristic_score is not None else d.risk_score,
                "lifecycle": d.lifecycle,
                "details": json.loads(d.details_json or "{}"),
            }
            for d in deviations
        ],
        "caveats": [
            "Баллы — некалиброванные оценки модели, не статистические вероятности.",
            "Отсутствие техники не трактуется как подтверждённый простой или «завершено».",
            "Физический % готовности на уровне L0 не считается.",
            "Ненаблюдаемые работы не порождают тревог «не начата» из камер.",
            "Сводка ограничена запрошенной календарной датой (captured_at / last_seen).",
        ],
    }


def explain_deviation(d: Deviation) -> str:
    details = json.loads(d.details_json or "{}")
    note = details.get("note", "")
    score = d.heuristic_score if d.heuristic_score is not None else d.risk_score
    return f"{d.code} heuristic={score}: {note}".strip()
