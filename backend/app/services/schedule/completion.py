"""Завершение работы КСГ и каскад предшественников (без publish графика)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ScheduleDependency, ScheduleItem, ScheduleItemState


_DONE = frozenset({"LIKELY_FINISH", "HUMAN_CONFIRMED", "CONFIRMED_COMPLETED"})


def _latest_state(db: Session, item_id: int, version_id: int) -> ScheduleItemState | None:
    return (
        db.query(ScheduleItemState)
        .filter(
            ScheduleItemState.schedule_item_id == item_id,
            ScheduleItemState.schedule_version_id == version_id,
        )
        .order_by(ScheduleItemState.as_of.desc(), ScheduleItemState.id.desc())
        .first()
    )


def _set_completed(
    db: Session,
    *,
    item: ScheduleItem,
    as_of: datetime,
    source: str,
) -> ScheduleItemState:
    row = _latest_state(db, item.id, item.schedule_version_id)
    if row is None:
        row = ScheduleItemState(
            schedule_version_id=item.schedule_version_id,
            schedule_item_id=item.id,
            as_of=as_of,
            observed_activity=1.0,
            match_score=1.0,
            ui_status="CONFIRMED_COMPLETED",
            payload_json="{}",
        )
        db.add(row)
    else:
        row.ui_status = "CONFIRMED_COMPLETED"
        row.as_of = as_of
    # Редакторский прогресс: даты плана published-КСГ не трогаем
    item.actual_progress = 1.0
    if item.actual_start is None:
        item.actual_start = item.planned_start
    # Источник закрытия пишем в payload состояния
    import json

    try:
        payload = json.loads(row.payload_json or "{}")
    except Exception:
        payload = {}
    payload["completion_source"] = source
    payload["completed_at"] = as_of.isoformat()
    row.payload_json = json.dumps(payload, ensure_ascii=False)
    db.flush()
    return row


def list_fs_predecessors(db: Session, item: ScheduleItem) -> list[ScheduleItem]:
    deps = (
        db.query(ScheduleDependency)
        .filter(
            ScheduleDependency.schedule_version_id == item.schedule_version_id,
            ScheduleDependency.successor_item_id == item.id,
            ScheduleDependency.link_type.in_(("FS", "FF", "SS", "SF")),
        )
        .all()
    )
    out: list[ScheduleItem] = []
    for d in deps:
        pred = db.get(ScheduleItem, d.predecessor_item_id)
        if pred is not None:
            out.append(pred)
    return out


def preview_complete_work(
    db: Session,
    *,
    project_id: int,
    schedule_item_id: int,
) -> dict[str, Any]:
    """
    Предпросмотр: какие предшественники ещё не CONFIRMED_COMPLETED.
    Не пишет в БД. Published КСГ не трогает.
    """
    item = db.get(ScheduleItem, schedule_item_id)
    if item is None:
        raise ValueError("schedule item not found")
    from app.db.models import ScheduleVersion

    ver = db.get(ScheduleVersion, item.schedule_version_id)
    if ver is None or ver.project_id != project_id:
        raise ValueError("schedule item not found")

    preds = list_fs_predecessors(db, item)
    open_preds: list[dict[str, Any]] = []
    already_done: list[dict[str, Any]] = []
    for p in preds:
        st = _latest_state(db, p.id, p.schedule_version_id)
        status = (st.ui_status if st else "UNCONFIRMED") or "UNCONFIRMED"
        entry = {
            "schedule_item_id": p.id,
            "name": p.raw_name,
            "building": p.building,
            "ui_status": status,
            "planned_finish": p.planned_finish.isoformat() if p.planned_finish else None,
        }
        if status in _DONE:
            already_done.append(entry)
        else:
            open_preds.append(entry)

    return {
        "schedule_item_id": item.id,
        "name": item.raw_name,
        "building": item.building,
        "open_predecessors": open_preds,
        "already_completed_predecessors": already_done,
        "cascade_recommended": len(open_preds) > 0,
        "message_ru": (
            f"Работа «{item.raw_name}» имеет {len(open_preds)} незакрытых предшественников по сети. "
            "Подтвердите список — статусы наблюдения станут CONFIRMED_COMPLETED. "
            "Опубликованный КСГ (даты плана) не изменится."
            if open_preds
            else "Предшественники по доступной сети уже закрыты или связей нет."
        ),
        "not_official_schedule": True,
        "partial_network_note": "Каскад только по импортированным/подтверждённым связям текущей версии.",
    }


def confirm_complete_work(
    db: Session,
    *,
    project_id: int,
    schedule_item_id: int,
    close_predecessor_ids: list[int] | None = None,
    close_all_open_predecessors: bool = False,
    as_of: datetime | None = None,
    user_id: str = "operator",
) -> dict[str, Any]:
    """
    Закрывает работу (+ опционально предшественников) как CONFIRMED_COMPLETED.
    Факт: статусы наблюдения. Не факт: новый срок проекта / publish.
    """
    preview = preview_complete_work(db, project_id=project_id, schedule_item_id=schedule_item_id)
    item = db.get(ScheduleItem, schedule_item_id)
    assert item is not None
    now = as_of or datetime.utcnow()

    open_ids = {p["schedule_item_id"] for p in preview["open_predecessors"]}
    if close_all_open_predecessors:
        to_close = sorted(open_ids)
    elif close_predecessor_ids is not None:
        to_close = [i for i in close_predecessor_ids if i in open_ids]
    else:
        to_close = []

    _set_completed(db, item=item, as_of=now, source=f"human:{user_id}")
    closed: list[dict[str, Any]] = []
    for pid in to_close:
        pred = db.get(ScheduleItem, pid)
        if pred is None:
            continue
        _set_completed(db, item=pred, as_of=now, source=f"cascade_from:{schedule_item_id}:{user_id}")
        closed.append({"schedule_item_id": pred.id, "name": pred.raw_name})

    db.flush()
    return {
        "status": "OK",
        "schedule_item_id": item.id,
        "ui_status": "CONFIRMED_COMPLETED",
        "predecessors_closed": closed,
        "predecessors_skipped": [p for p in preview["open_predecessors"] if p["schedule_item_id"] not in to_close],
        "published_schedule_mutated": False,
        "message_ru": (
            f"Работа закрыта. Предшественников закрыто: {len(closed)}. "
            "Даты опубликованного КСГ не изменены."
        ),
        "preview": preview,
    }
