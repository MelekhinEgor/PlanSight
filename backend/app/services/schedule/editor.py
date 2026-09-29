"""Редактор графика: fork / recalc / save / publish (V4 P2)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Project, ScheduleDependency, ScheduleItem, ScheduleVersion
from app.services.product.portfolio import list_schedule_versions_v2
from app.services.schedule.service import get_active_schedule


def _parse_day(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10])
    except ValueError:
        return None


def _day(dt: datetime | None) -> str | None:
    return dt.date().isoformat() if dt else None


def _duration_days(start: datetime | None, finish: datetime | None, fallback: int = 1) -> int:
    if start and finish:
        return max(1, (finish.date() - start.date()).days + 1)
    return max(1, fallback)


def creates_cycle(deps: list[dict[str, Any]]) -> bool:
    adj: dict[str, list[str]] = {}
    for d in deps:
        a = str(d["predecessor_activity_id"])
        b = str(d["successor_activity_id"])
        if a == b:
            return True
        adj.setdefault(a, []).append(b)
    for start in list(adj.keys()):
        stack = list(adj.get(start, []))
        seen: set[str] = set()
        while stack:
            n = stack.pop()
            if n == start:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(adj.get(n, []))
    return False


def recalculate_activities(
    activities: list[dict[str, Any]],
    deps: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Прямая пропагация дат по связям. НЕ перезаписывает forecast_end через planned_end (V6).

    При strict=True висячие ID / циклы / плохие типы → HTTP 422.
    """
    from app.services.schedule.network import validate_network

    errors = validate_network(activities, deps)
    if strict and errors:
        raise HTTPException(422, {"detail": "schedule_network_invalid", "errors": errors})

    by_id = {str(a["id"]): dict(a) for a in activities}
    indegree = {aid: 0 for aid in by_id}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    incoming: dict[str, list[dict[str, Any]]] = {}
    for d in deps:
        pred = str(d["predecessor_activity_id"])
        succ = str(d["successor_activity_id"])
        if pred not in by_id or succ not in by_id:
            if strict:
                raise HTTPException(
                    422,
                    {"detail": "dangling_dependency", "predecessor": pred, "successor": succ},
                )
            continue
        outgoing.setdefault(pred, []).append(d)
        incoming.setdefault(succ, []).append(d)
        indegree[succ] = indegree.get(succ, 0) + 1

    if creates_cycle(deps):
        if strict:
            raise HTTPException(422, {"detail": "cycle_detected"})
        return list(by_id.values()), []

    changed: list[str] = []
    q = [aid for aid, deg in indegree.items() if deg == 0]
    while q:
        aid = q.pop(0)
        a = by_id[aid]
        start = _parse_day(a.get("planned_start"))
        end = _parse_day(a.get("planned_end"))
        dur = _duration_days(start, end, int(a.get("planned_duration") or 1))
        requirements: list[datetime] = []
        for d in incoming.get(aid, []):
            p = by_id[str(d["predecessor_activity_id"])]
            lag = int(d.get("lag_days") or 0)
            rel = (d.get("relation_type") or "FS").upper()
            ps = _parse_day(p.get("planned_start"))
            pe = _parse_day(p.get("planned_end"))
            req = None
            if rel == "FS" and pe:
                req = pe + timedelta(days=1 + lag)
            elif rel == "SS" and ps:
                req = ps + timedelta(days=lag)
            elif rel == "FF" and pe:
                req = pe + timedelta(days=lag - (dur - 1))
            elif rel == "SF" and ps:
                req = ps + timedelta(days=lag - (dur - 1))
            if req is not None:
                requirements.append(req)
        if requirements:
            required = max(requirements)
            cur_start = _parse_day(a.get("planned_start"))
            if cur_start is None or cur_start.date() < required.date():
                a["planned_start"] = required.date().isoformat()
                a["planned_end"] = (required + timedelta(days=dur - 1)).date().isoformat()
                # V6: сохраняем существующий forecast, если не пуст
                if not a.get("forecast_end"):
                    a["forecast_end"] = a["planned_end"]
                a["planned_duration"] = dur
                changed.append(aid)
        for d in outgoing.get(aid, []):
            nxt = str(d["successor_activity_id"])
            indegree[nxt] = indegree.get(nxt, 1) - 1
            if indegree[nxt] == 0:
                q.append(nxt)
    return list(by_id.values()), changed


def _copy_items(db: Session, source: ScheduleVersion, target: ScheduleVersion) -> dict[int, int]:
    """Копировать строки графика; вернуть old_id → new_id."""
    id_map: dict[int, int] = {}
    items = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == source.id).all()
    for it in items:
        clone = ScheduleItem(
            schedule_version_id=target.id,
            external_id=it.external_id,
            raw_name=it.raw_name,
            work_type_id=it.work_type_id,
            planned_start=it.planned_start,
            planned_finish=it.planned_finish,
            building=it.building,
            building_raw=it.building_raw,
            building_normalized=it.building_normalized,
            building_source=it.building_source,
            workface=it.workface,
            floor=it.floor,
            observability_mode=it.observability_mode,
            observability_reason=it.observability_reason,
            is_summary=it.is_summary,
            is_milestone=it.is_milestone,
            wbs=it.wbs,
            normalized_operation=it.normalized_operation,
            unit=getattr(it, "unit", None),
            planned_quantity=getattr(it, "planned_quantity", None),
            planned_progress=getattr(it, "planned_progress", None),
            actual_progress=getattr(it, "actual_progress", None),
            forecast_end=getattr(it, "forecast_end", None),
            actual_start=getattr(it, "actual_start", None),
            sort_order=getattr(it, "sort_order", 0) or 0,
            mapping_status=getattr(it, "mapping_status", None) or "UNMAPPED",
            canonical_work_code=getattr(it, "canonical_work_code", None),
            canonical_work_name=getattr(it, "canonical_work_name", None),
            wbs_node_id=getattr(it, "wbs_node_id", None),
        )
        db.add(clone)
        db.flush()
        id_map[it.id] = clone.id
    deps = db.query(ScheduleDependency).filter(ScheduleDependency.schedule_version_id == source.id).all()
    for d in deps:
        if d.predecessor_item_id not in id_map or d.successor_item_id not in id_map:
            continue
        db.add(
            ScheduleDependency(
                schedule_version_id=target.id,
                successor_item_id=id_map[d.successor_item_id],
                predecessor_item_id=id_map[d.predecessor_item_id],
                link_type=d.link_type,
                lag_minutes=d.lag_minutes,
                predecessor_uid=d.predecessor_uid,
                successor_uid=d.successor_uid,
            )
        )
    return id_map


def fork_working_copy(db: Session, project_id: int, source_version_id: int | None = None) -> dict[str, Any]:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    source = None
    if source_version_id:
        source = db.get(ScheduleVersion, source_version_id)
        if not source or source.project_id != project_id:
            raise HTTPException(404, "source version not found")
    if source is None:
        source = get_active_schedule(db, project_id)
    if source is None:
        raise HTTPException(400, "нет исходной версии графика")

    now = datetime.utcnow()
    target = ScheduleVersion(
        project_id=project_id,
        source_path=f"working_copy_of_{source.id}",
        checksum=f"working-{source.id}-{int(now.timestamp())}",
        imported_at=now,
        is_active=False,
        kind=source.kind or "CURRENT",
        source_file_sha=source.source_file_sha,
        version_state="WORKING",
        parent_version_id=source.id,
        revision=1,
        published_at=None,
        updated_at=now,
        wbs_json=getattr(source, "wbs_json", None) or "[]",
        source_filename=f"Рабочая копия v{source.id}",
        network_recovery_json=getattr(source, "network_recovery_json", None),
    )
    db.add(target)
    db.flush()
    _copy_items(db, source, target)
    db.commit()
    versions = list_schedule_versions_v2(db, project_id)
    meta = next((v for v in versions if v["id"] == str(target.id)), None)
    if meta is None:
        raise HTTPException(500, "fork failed")
    return meta


def save_schedule_edits(
    db: Session,
    project_id: int,
    *,
    version_id: int,
    activities: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    recalculate: bool = True,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    version = db.get(ScheduleVersion, version_id)
    if not version or version.project_id != project_id:
        raise HTTPException(404, "version not found")
    state = (getattr(version, "version_state", None) or "").upper()
    if state == "PUBLISHED" or (version.is_active and state not in ("WORKING", "IMPORTED")):
        # Версия published только для чтения, пока явно не WORKING
        if state == "PUBLISHED":
            raise HTTPException(409, "опубликованная версия только для чтения — создайте рабочую копию")
    if state not in ("WORKING", "IMPORTED"):
        # Статус IMPORTED → WORKING при первом save
        pass
    if expected_revision is not None and int(getattr(version, "revision", 1) or 1) != int(expected_revision):
        raise HTTPException(409, f"конфликт ревизии: ожидалась {expected_revision}, сейчас {version.revision}")

    # Нормализация deps
    norm_deps = []
    for d in dependencies:
        pred = d.get("predecessor_activity_id")
        succ = d.get("successor_activity_id")
        if not pred or not succ:
            continue
        norm_deps.append(
            {
                "predecessor_activity_id": str(pred),
                "successor_activity_id": str(succ),
                "relation_type": (d.get("relation_type") or "FS").upper(),
                "lag_days": int(d.get("lag_days") or 0),
            }
        )
    if creates_cycle(norm_deps):
        raise HTTPException(422, "циклическая зависимость — сохранение отклонено")

    acts = [dict(a) for a in activities]
    changed: list[str] = []
    if recalculate:
        acts, changed = recalculate_activities(acts, norm_deps)

    # Обновления работ (даты + editorial поля v2)
    by_id = {str(a["id"]): a for a in acts}
    items = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version.id).all()
    updated = 0
    for it in items:
        patch = by_id.get(str(it.id))
        if not patch:
            continue
        if patch.get("name"):
            it.raw_name = str(patch["name"])
        if patch.get("code") is not None:
            it.external_id = str(patch["code"])
        ps = _parse_day(patch.get("planned_start"))
        pe = _parse_day(patch.get("planned_end"))
        if ps:
            it.planned_start = ps
        if pe:
            it.planned_finish = pe
        if "unit" in patch:
            it.unit = patch.get("unit")
        if "planned_quantity" in patch:
            it.planned_quantity = patch.get("planned_quantity")
        if "planned_progress" in patch:
            it.planned_progress = patch.get("planned_progress")
        if "actual_progress" in patch:
            it.actual_progress = patch.get("actual_progress")
        if "forecast_end" in patch:
            it.forecast_end = _parse_day(patch.get("forecast_end"))
        if "actual_start" in patch:
            it.actual_start = _parse_day(patch.get("actual_start"))
        if "wbs_node_id" in patch:
            it.wbs_node_id = patch.get("wbs_node_id")
        updated += 1

    # Замена зависимостей
    db.query(ScheduleDependency).filter(ScheduleDependency.schedule_version_id == version.id).delete(
        synchronize_session=False
    )
    item_ids = {it.id for it in items}
    for d in norm_deps:
        pred = int(d["predecessor_activity_id"])
        succ = int(d["successor_activity_id"])
        if pred not in item_ids or succ not in item_ids:
            continue
        db.add(
            ScheduleDependency(
                schedule_version_id=version.id,
                predecessor_item_id=pred,
                successor_item_id=succ,
                link_type=d["relation_type"],
                lag_minutes=int(d["lag_days"]) * 24 * 60,
            )
        )

    now = datetime.utcnow()
    version.version_state = "WORKING"
    version.is_active = False
    version.revision = int(getattr(version, "revision", 1) or 1) + 1
    version.updated_at = now
    db.commit()
    return {
        "version_id": str(version.id),
        "updated_activities": updated,
        "dependency_count": len(norm_deps),
        "recalculated_activities": len(changed),
        "updated_at": now.isoformat(),
        "revision": version.revision,
        "changed_activity_ids": changed,
    }


def publish_version(db: Session, project_id: int, version_id: int) -> dict[str, Any]:
    version = db.get(ScheduleVersion, version_id)
    if not version or version.project_id != project_id:
        raise HTTPException(404, "version not found")
    deps = (
        db.query(ScheduleDependency)
        .filter(ScheduleDependency.schedule_version_id == version.id)
        .all()
    )
    norm = [
        {
            "predecessor_activity_id": str(d.predecessor_item_id),
            "successor_activity_id": str(d.successor_item_id),
            "relation_type": d.link_type,
            "lag_days": int(round((d.lag_minutes or 0) / (60 * 24))),
        }
        for d in deps
    ]
    if creates_cycle(norm):
        raise HTTPException(422, "нельзя опубликовать версию с циклом")

    now = datetime.utcnow()
    others = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == project_id, ScheduleVersion.id != version.id)
        .all()
    )
    for o in others:
        if o.is_active:
            o.is_active = False
            if (getattr(o, "version_state", None) or "").upper() == "PUBLISHED":
                o.version_state = "ARCHIVED"
    version.is_active = True
    version.version_state = "PUBLISHED"
    version.published_at = now
    version.updated_at = now
    db.commit()
    versions = list_schedule_versions_v2(db, project_id)
    meta = next((v for v in versions if v["id"] == str(version.id)), None)
    if meta is None:
        raise HTTPException(500, "publish failed")
    return meta


def dry_run_recalculate(
    db: Session,
    project_id: int,
    version_id: int,
    activities: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    version = db.get(ScheduleVersion, version_id)
    if not version or version.project_id != project_id:
        raise HTTPException(404, "version not found")
    norm_deps = [
        {
            "predecessor_activity_id": str(d["predecessor_activity_id"]),
            "successor_activity_id": str(d["successor_activity_id"]),
            "relation_type": (d.get("relation_type") or "FS").upper(),
            "lag_days": int(d.get("lag_days") or 0),
        }
        for d in dependencies
        if d.get("predecessor_activity_id") and d.get("successor_activity_id")
    ]
    violations = []
    if creates_cycle(norm_deps):
        violations.append({"code": "CYCLE", "message": "обнаружен цикл зависимостей"})
        return {
            "ok": False,
            "violations": violations,
            "changed_activities": [],
            "activities": activities,
            "revision": getattr(version, "revision", 1),
        }
    new_acts, changed = recalculate_activities(activities, norm_deps)
    return {
        "ok": True,
        "violations": [],
        "changed_activities": changed,
        "activities": new_acts,
        "revision": getattr(version, "revision", 1),
        "as_of": datetime.utcnow().isoformat(),
        "assumptions": ["календарные дни UTC", "не эквивалент MS Project"],
    }
