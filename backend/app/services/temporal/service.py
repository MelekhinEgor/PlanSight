from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import EventType, PhysicalState
from app.db.models import Episode, ScheduleItemState, TemporalState


STATES = [
    PhysicalState.NOT_STARTED.value,
    PhysicalState.ACTIVE.value,
    PhysicalState.PAUSED.value,
    PhysicalState.COMPLETED.value,
]

# P0-D: не стартуем с равномерного 0.25 — prior «ещё не начато»
_PRIOR = {
    PhysicalState.NOT_STARTED.value: 0.82,
    PhysicalState.ACTIVE.value: 0.10,
    PhysicalState.PAUSED.value: 0.05,
    PhysicalState.COMPLETED.value: 0.03,
}


def _prior() -> dict[str, float]:
    return dict(_PRIOR)


def _uniform() -> dict[str, float]:
    return {s: 1.0 / len(STATES) for s in STATES}


def _normalize(dist: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, dist.get(s, 0.0)) for s in STATES)
    if total <= 0:
        return _prior()
    return {s: max(0.0, dist.get(s, 0.0)) / total for s in STATES}


def _identity() -> dict[str, dict[str, float]]:
    return {s: {d: (1.0 if d == s else 0.0) for d in STATES} for s in STATES}


def _blend_mats(a: dict[str, dict[str, float]], b: dict[str, dict[str, float]], w: float) -> dict[str, dict[str, float]]:
    """w=0 → a, w=1 → b."""
    w = max(0.0, min(1.0, w))
    out: dict[str, dict[str, float]] = {}
    for src in STATES:
        out[src] = {}
        for dst in STATES:
            out[src][dst] = (1 - w) * float(a.get(src, {}).get(dst, 0.0)) + w * float(b.get(src, {}).get(dst, 0.0))
        # ренормализация строки
        row_sum = sum(out[src].values()) or 1.0
        out[src] = {d: out[src][d] / row_sum for d in STATES}
    return out


def transition_matrix_for_dt(dt_seconds: float | None) -> dict[str, dict[str, float]]:
    """Δt-aware: короткий gap ≈ identity, длинный → полная матрица из конфига."""
    cfg = get_settings().section("engine").get("temporal") or {}
    base = cfg.get("transition") or {}
    full = {s: {d: float((base.get(s) or {}).get(d, 0.0)) for d in STATES} for s in STATES}
    # нормализация строк полной матрицы
    for s in STATES:
        rs = sum(full[s].values()) or 1.0
        full[s] = {d: full[s][d] / rs for d in STATES}

    if dt_seconds is None or dt_seconds < 0:
        return full

    short = float(cfg.get("dt_short_sec", 300))
    medium = float(cfg.get("dt_medium_sec", 1200))
    long = float(cfg.get("dt_long_sec", 3600))
    ident = _identity()

    if dt_seconds <= short:
        # почти без перехода
        return _blend_mats(ident, full, dt_seconds / max(short, 1.0) * 0.25)
    if dt_seconds <= medium:
        return _blend_mats(ident, full, 0.25 + 0.5 * (dt_seconds - short) / max(medium - short, 1.0))
    if dt_seconds <= long:
        return _blend_mats(full, full, 1.0)  # already full; mild further toward sticky COMPLETED kept in base
    # длинный gap: сильнее stay / меньше persistence ACTIVE — к identity+NOT_STARTED
    sticky = _blend_mats(full, ident, 0.35)
    return sticky


def update_episode(
    db: Session,
    *,
    project_id: int,
    camera_id: int,
    captured_at: datetime,
    equipment_vector: dict[str, float],
    expected_interval_sec: int | None = None,
    visual_zone_id: int | None = None,
) -> Episode:
    cfg = get_settings().section("engine").get("episode") or {}
    gap_intervals = float(cfg.get("gap_intervals", 1.5))
    min_gap = float(cfg.get("min_gap_seconds", 300))
    cadence = float(expected_interval_sec or 300)
    gap = timedelta(seconds=max(min_gap, cadence * gap_intervals))
    q = db.query(Episode).filter(Episode.project_id == project_id, Episode.camera_id == camera_id)
    if visual_zone_id is None:
        q = q.filter(Episode.visual_zone_id.is_(None))
    else:
        q = q.filter(Episode.visual_zone_id == visual_zone_id)
    last = q.order_by(Episode.end_at.desc()).first()
    composition = {k: float(v) for k, v in equipment_vector.items() if v > 0}
    if last is not None and captured_at - last.end_at <= gap:
        prev = json.loads(last.composition_json or "{}")
        prev_keys = set(prev.keys())
        new_keys = set(composition.keys())
        if prev_keys and new_keys and prev_keys != new_keys:
            pass
        elif prev_keys and not new_keys:
            pass  # пустой кадр после техники → новый эпизод
        else:
            merged = {**prev}
            for k, v in composition.items():
                merged[k] = max(float(merged.get(k, 0)), float(v))
            last.end_at = max(last.end_at, captured_at)
            last.composition_json = json.dumps(merged, ensure_ascii=False)
            last.frame_count = int(last.frame_count or 1) + 1
            db.flush()
            return last

    ep = Episode(
        project_id=project_id,
        camera_id=camera_id,
        visual_zone_id=visual_zone_id,
        start_at=captured_at,
        end_at=captured_at,
        composition_json=json.dumps(composition, ensure_ascii=False),
        frame_count=1,
    )
    db.add(ep)
    db.flush()
    return ep


def episode_repeat_weight(episode: Episode) -> float:
    """Стоящая техника на похожих кадрах — НЕ независимые доказательства."""
    cfg = get_settings().section("engine").get("episode") or {}
    decay = float(cfg.get("repeat_decay", 0.35))
    n = max(1, int(episode.frame_count or 1))
    return max(decay, 1.0 / (n ** 0.5))


def predict_state(prev: dict[str, float], dt_seconds: float | None = None) -> dict[str, float]:
    transitions = transition_matrix_for_dt(dt_seconds)
    pred = {s: 0.0 for s in STATES}
    for src in STATES:
        p_src = prev.get(src, 0.0)
        row = transitions.get(src) or {}
        for dst in STATES:
            pred[dst] += p_src * float(row.get(dst, 0.0))
    return _normalize(pred)


def emission_likelihood(activity_score: float, observability: float) -> dict[str, float]:
    """Прокси P(O|z) — отсутствующий кадр НЕ должен давать negative evidence (caller пропускает)."""
    boost = float(
        get_settings().section("engine").get("temporal", {}).get("emission_active_boost", 0.55)
    )
    a = max(0.0, min(1.0, activity_score)) * max(0.0, min(1.0, observability))
    return {
        PhysicalState.NOT_STARTED.value: max(0.05, 0.7 - a),
        PhysicalState.ACTIVE.value: 0.15 + boost * a,
        PhysicalState.PAUSED.value: 0.25 + 0.2 * (1 - a) * (1 if a < 0.4 else 0.3),
        # Статус COMPLETED никогда не выводим из отсутствия техники
        PhysicalState.COMPLETED.value: 0.05,
    }


def update_state_filter(
    db: Session,
    *,
    project_id: int,
    camera_id: int,
    work_type_id: int,
    at: datetime,
    activity_score: float,
    observability: float,
    visual_zone_key: str = "WHOLE_FRAME",
) -> dict[str, float]:
    """Состояние activity_type_state(camera, visual_zone, work_type) — не путать с schedule_item_state."""
    row = (
        db.query(TemporalState)
        .filter(
            TemporalState.project_id == project_id,
            TemporalState.camera_id == camera_id,
            TemporalState.work_type_id == work_type_id,
            TemporalState.visual_zone_key == visual_zone_key,
        )
        .one_or_none()
    )
    prev = json.loads(row.distribution_json) if row else _prior()
    dt = None
    if row is not None and row.as_of is not None:
        dt = max(0.0, (at - row.as_of).total_seconds())
    pred = predict_state(prev, dt_seconds=dt)
    like = emission_likelihood(activity_score, observability)
    post = _normalize({s: pred[s] * like[s] for s in STATES})

    if row is None:
        row = TemporalState(
            project_id=project_id,
            camera_id=camera_id,
            work_type_id=work_type_id,
            visual_zone_key=visual_zone_key,
            as_of=at,
            distribution_json=json.dumps(post),
            frame_support=1,
            last_activity_score=activity_score,
            last_dt_sec=0.0,
        )
        db.add(row)
    else:
        row.last_dt_sec = float(dt or 0.0)
        row.as_of = at if (row.as_of is None or at >= row.as_of) else row.as_of
        row.distribution_json = json.dumps(post)
        row.frame_support = int(row.frame_support or 0) + 1
        row.last_activity_score = activity_score
    db.flush()
    return post


def update_schedule_item_state(
    db: Session,
    *,
    schedule_version_id: int,
    schedule_item_id: int,
    at: datetime,
    observed_activity: float,
    match_score: float,
    ui_status: str = "UNCONFIRMED",
) -> ScheduleItemState:
    """Отдельное состояние строки КСГ — два корпуса с одной работой не сливаются."""
    row = (
        db.query(ScheduleItemState)
        .filter(
            ScheduleItemState.schedule_version_id == schedule_version_id,
            ScheduleItemState.schedule_item_id == schedule_item_id,
        )
        .one_or_none()
    )
    payload = {
        "observed_activity": observed_activity,
        "match_score": match_score,
        "ui_status": ui_status,
        "as_of": at.isoformat(),
        # Статус COMPLETED только HUMAN_CONFIRMED — здесь максимум UNCONFIRMED_FINISH
        "confirmed_completed": False,
        "possibly_paused": ui_status == "POSSIBLY_PAUSED",
    }
    if row is None:
        row = ScheduleItemState(
            schedule_version_id=schedule_version_id,
            schedule_item_id=schedule_item_id,
            as_of=at,
            observed_activity=observed_activity,
            match_score=match_score,
            ui_status=ui_status,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        db.add(row)
    else:
        if row.as_of is None or at >= row.as_of:
            row.as_of = at
            row.observed_activity = observed_activity
            row.match_score = match_score
            row.ui_status = ui_status
            row.payload_json = json.dumps(payload, ensure_ascii=False)
    db.flush()
    return row


def derive_events(
    *,
    prev_dist: dict[str, float] | None,
    post_dist: dict[str, float],
    activity_score: float,
    frame_support: int,
    process_changed: bool,
) -> list[dict]:
    cfg = get_settings().section("engine").get("temporal") or {}
    active_thr = float(get_settings().section("engine").get("activity", {}).get("active_threshold", 0.45))
    min_start = int(cfg.get("min_frames_for_start", 2))
    events: list[dict] = []

    prev_mode = max(prev_dist or _prior(), key=lambda s: (prev_dist or _prior())[s])
    post_mode = max(post_dist, key=lambda s: post_dist[s])

    if (
        post_mode == PhysicalState.ACTIVE.value
        and post_dist[PhysicalState.ACTIVE.value] >= active_thr
        and frame_support >= min_start
        and prev_mode in (PhysicalState.NOT_STARTED.value, PhysicalState.PAUSED.value)
    ):
        code = EventType.LIKELY_START.value if prev_mode == PhysicalState.NOT_STARTED.value else EventType.RESUME.value
        events.append({"event_type": code, "status": "model_estimate"})
    elif post_mode == PhysicalState.ACTIVE.value and activity_score >= active_thr:
        events.append({"event_type": EventType.CONTINUE.value, "status": "model_estimate"})
    elif (
        prev_mode == PhysicalState.ACTIVE.value
        and post_mode == PhysicalState.PAUSED.value
        and frame_support >= int(cfg.get("min_frames_for_pause", 2))
    ):
        events.append(
            {
                "event_type": EventType.POSSIBLE_PAUSE.value,
                "status": "model_estimate",
                "note": "not asserting equipment idle",
            }
        )

    if cfg.get("likely_finish_requires_process_change", True):
        if process_changed and post_dist[PhysicalState.COMPLETED.value] > 0.35:
            # возможное завершение — не HUMAN_CONFIRMED
            events.append(
                {
                    "event_type": EventType.LIKELY_FINISH.value,
                    "status": "model_estimate",
                    "note": "UNCONFIRMED_FINISH — смена процесса, не подтверждённый факт",
                }
            )
        elif post_dist.get(PhysicalState.ACTIVE.value, 0) < 0.2 and prev_mode == PhysicalState.ACTIVE.value:
            events.append({"event_type": EventType.UNCONFIRMED.value, "status": "model_estimate"})
    return events
