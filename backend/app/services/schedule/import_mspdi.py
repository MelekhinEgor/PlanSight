"""Импорт Microsoft Project MSPDI XML (Базовый план / Текущий график)."""

from __future__ import annotations

import hashlib
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from dateutil import parser as dtparser
from sqlalchemy.orm import Session

from app.db.models import ScheduleDependency, ScheduleItem, ScheduleVersion, WorkType
from app.services.knowledge_base.service import load_kb, sync_kb_to_db
from app.services.schedule.observability import classify_observability

NS = {"m": "http://schemas.microsoft.com/project"}


def _txt(el: ET.Element | None, default: str = "") -> str:
    if el is None or el.text is None:
        return default
    return str(el.text).strip()


def _child(parent: ET.Element, tag: str) -> ET.Element | None:
    # Важно: Element без дочерних узлов bool()==False, нельзя писать find() or find()
    el = parent.find(f"m:{tag}", NS)
    if el is not None:
        return el
    return parent.find(f"{{{NS['m']}}}{tag}")


def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = dtparser.isoparse(raw)
    except (ValueError, TypeError):
        try:
            dt = dtparser.parse(raw)
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def parse_mspdi(content: bytes) -> dict:
    root = ET.fromstring(content)
    status_date = _parse_dt(_txt(_child(root, "StatusDate")))
    start_date = _parse_dt(_txt(_child(root, "StartDate")))
    finish_date = _parse_dt(_txt(_child(root, "FinishDate")))

    calendars_el = root.find("m:Calendars", NS)
    if calendars_el is None:
        calendars_el = root.find("Calendars")
    calendar_count = 0
    if calendars_el is not None:
        calendar_count = sum(1 for c in list(calendars_el) if c.tag.endswith("Calendar") or c.tag == "Calendar")

    resources_el = root.find("m:Resources", NS)
    if resources_el is None:
        resources_el = root.find("Resources")
    resource_count = 0
    if resources_el is not None:
        resource_count = sum(
            1
            for r in list(resources_el)
            if (r.tag.endswith("Resource") or r.tag == "Resource") and _txt(_child(r, "Name"))
        )

    assignments_el = root.find("m:Assignments", NS)
    if assignments_el is None:
        assignments_el = root.find("Assignments")
    assignment_count = 0
    if assignments_el is not None:
        assignment_count = sum(
            1 for a in list(assignments_el) if a.tag.endswith("Assignment") or a.tag == "Assignment"
        )

    tasks_el = root.find("m:Tasks", NS)
    if tasks_el is None:
        tasks_el = root.find("Tasks")
    tasks = []
    if tasks_el is not None:
        for t in list(tasks_el):
            if not (t.tag.endswith("Task") or t.tag == "Task"):
                continue
            uid = _txt(_child(t, "UID"))
            tid = _txt(_child(t, "ID"))
            name = _txt(_child(t, "Name"))
            if not name:
                continue
            wbs = _txt(_child(t, "WBS"))
            outline = _txt(_child(t, "OutlineLevel"), "0")
            summary = _txt(_child(t, "Summary"), "0") in ("1", "true", "True")
            milestone = _txt(_child(t, "Milestone"), "0") in ("1", "true", "True")
            start = _parse_dt(_txt(_child(t, "Start")))
            finish = _parse_dt(_txt(_child(t, "Finish")))
            actual_start = _parse_dt(_txt(_child(t, "ActualStart")))
            actual_finish = _parse_dt(_txt(_child(t, "ActualFinish")))
            tasks.append(
                {
                    "external_uid": uid or tid or str(uuid.uuid4()),
                    "external_id": tid or uid,
                    "raw_name": name,
                    "wbs": wbs or None,
                    "outline_level": int(outline or 0),
                    "is_summary": summary,
                    "is_milestone": milestone,
                    "planned_start": start,
                    "planned_finish": finish,
                    "actual_start": actual_start,
                    "actual_finish": actual_finish,
                }
            )

    # предшественники
    deps = []
    if tasks_el is not None:
        for t in list(tasks_el):
            if not (t.tag.endswith("Task") or t.tag == "Task"):
                continue
            uid = _txt(_child(t, "UID"))
            for link in t.findall("m:PredecessorLink", NS) or t.findall("PredecessorLink"):
                pred = _txt(_child(link, "PredecessorUID"))
                ltype = _txt(_child(link, "Type"), "1")
                lag = _txt(_child(link, "LinkLag"), "0")
                if pred:
                    deps.append(
                        {
                            "successor_uid": uid,
                            "predecessor_uid": pred,
                            "type": ltype,
                            "lag": lag,
                        }
                    )

    uid_set = {str(t["external_uid"]) for t in tasks}
    orphan_deps = sum(
        1
        for d in deps
        if str(d["predecessor_uid"]) not in uid_set or str(d["successor_uid"]) not in uid_set
    )
    tasks_without_dates = sum(
        1 for t in tasks if t["planned_start"] is None or t["planned_finish"] is None
    )

    missing: list[str] = []
    present: list[str] = []
    for label, ok in (
        ("StatusDate", status_date is not None),
        ("StartDate", start_date is not None),
        ("FinishDate", finish_date is not None),
        ("Calendars", calendar_count > 0),
        ("Resources", resource_count > 0),
        ("Assignments", assignment_count > 0),
        ("PredecessorLinks", len(deps) > 0),
    ):
        (present if ok else missing).append(label)

    can_import_network = len(deps) > 0 and orphan_deps < len(deps)
    can_claim_resources = resource_count > 0 and assignment_count > 0
    missing_report = {
        "missing_fields": missing,
        "present_fields": present,
        "status_date": status_date.isoformat() if status_date else None,
        "project_start": start_date.isoformat() if start_date else None,
        "project_finish": finish_date.isoformat() if finish_date else None,
        "calendar_count": calendar_count,
        "resource_count": resource_count,
        "assignment_count": assignment_count,
        "tasks_without_dates": tasks_without_dates,
        "orphan_dependency_count": orphan_deps,
        "can_import_network": can_import_network,
        "can_claim_resource_optimization": can_claim_resources,
        "message_ru": (
            "Импорт задач/связей возможен"
            if can_import_network
            else "В MSPDI нет пригодной сети зависимостей"
        )
        + (
            "; ресурсная оптимизация недоступна без Resources/Assignments"
            if not can_claim_resources
            else "; ресурсы/назначения найдены"
        ),
    }

    return {
        "task_count": len(tasks),
        "dependency_count": len(deps),
        "tasks": tasks,
        "dependencies": deps,
        "leaf_count": sum(1 for x in tasks if not x["is_summary"] and not x["is_milestone"]),
        "summary_count": sum(1 for x in tasks if x["is_summary"]),
        "milestone_count": sum(1 for x in tasks if x["is_milestone"]),
        "status_date": status_date,
        "missing_data": missing_report,
    }


def _guess_building(name: str) -> str | None:
    """Устарело: используйте schedule.building.guess_building (P0-01)."""
    from app.services.schedule.building import guess_building

    return guess_building(name)


def import_mspdi_xml(
    db: Session,
    project_id: int,
    content: bytes,
    filename: str,
    *,
    kind: str = "CURRENT",
    activate: bool = True,
) -> tuple[ScheduleVersion, dict]:
    """Параметр kind: BASELINE | CURRENT. Не джойнит UID между разными экспортами."""
    sync_kb_to_db(db)
    kb = load_kb()
    parsed = parse_mspdi(content)
    checksum = hashlib.sha256(content).hexdigest()

    from app.core.config import get_settings

    uploads = get_settings().uploads_dir() / "schedules"
    uploads.mkdir(parents=True, exist_ok=True)
    stored = uploads / f"p{project_id}_{kind}_{checksum[:12]}_{Path(filename).name}"
    stored.write_bytes(content)

    if activate:
        db.query(ScheduleVersion).filter(
            ScheduleVersion.project_id == project_id,
            ScheduleVersion.is_active.is_(True),
        ).update({"is_active": False})

    version = ScheduleVersion(
        project_id=project_id,
        source_path=str(stored),
        checksum=checksum,
        is_active=activate,
        kind=kind,
        source_file_sha=checksum,
    )
    db.add(version)
    db.flush()

    wt_by_code = {w.code: w for w in db.query(WorkType).all()}
    warnings: list[str] = []
    imported_leaf = 0
    obs_counts: dict[str, int] = {}
    uid_to_item: dict[str, ScheduleItem] = {}

    for row in parsed["tasks"]:
        start = row["planned_start"]
        finish = row["planned_finish"]
        if start is None or finish is None:
            warnings.append(f"нет дат: {row['raw_name'][:80]}")
            continue
        if finish < start and not row["is_milestone"]:
            warnings.append(f"finish<start: {row['raw_name'][:80]}")
            continue

        mode, reason, suggested = classify_observability(
            row["raw_name"],
            is_milestone=row["is_milestone"],
            is_summary=row["is_summary"],
        )
        obs_counts[mode] = obs_counts.get(mode, 0) + 1

        mapped = None
        if not row["is_summary"] and not row["is_milestone"]:
            mapped = kb.map_work_name(row["raw_name"]) or suggested
        work_type_id = wt_by_code[mapped].id if mapped and mapped in wt_by_code else None

        # P0-01: summary/milestone/documentation — не источник визуального корпуса
        from app.services.schedule.building import parse_building_from_text

        bparse = parse_building_from_text(row["raw_name"])
        skip_visual_building = bool(
            row["is_summary"]
            or row["is_milestone"]
            or (mapped == "documentation")
            or mode == "NOT_OBSERVABLE"
        )
        building = None if skip_visual_building else bparse.normalized
        building_raw = None if skip_visual_building else bparse.raw
        building_source = "unknown" if skip_visual_building or not bparse.confident else bparse.source

        item = ScheduleItem(
            schedule_version_id=version.id,
            external_id=str(row["external_uid"]),
            raw_name=row["raw_name"],
            work_type_id=work_type_id,
            planned_start=start,
            planned_finish=finish if finish >= start else start,
            building=building,
            building_raw=building_raw,
            building_normalized=building,
            building_source=building_source,
            workface=row.get("wbs"),
            wbs=row.get("wbs"),
            observability_mode=mode,
            observability_reason=reason,
            is_summary=bool(row["is_summary"]),
            is_milestone=bool(row["is_milestone"]),
            normalized_operation=mapped,
        )
        db.add(item)
        uid_to_item[str(row["external_uid"])] = item
        if not row["is_summary"] and not row["is_milestone"]:
            imported_leaf += 1

    db.flush()

    # Преобразование PredecessorLink → ScheduleDependency (только внутри этой версии)
    LINK_TYPE = {"0": "FF", "1": "FS", "2": "SS", "3": "SF"}
    deps_saved = 0
    for d in parsed.get("dependencies") or []:
        succ = uid_to_item.get(str(d["successor_uid"]))
        pred = uid_to_item.get(str(d["predecessor_uid"]))
        if succ is None or pred is None:
            continue
        lag_raw = d.get("lag") or "0"
        try:
            # Поле MSPDI LinkLag в десятых минуты
            lag_minutes = int(float(lag_raw) / 10.0)
        except (TypeError, ValueError):
            lag_minutes = 0
        db.add(
            ScheduleDependency(
                schedule_version_id=version.id,
                successor_item_id=succ.id,
                predecessor_item_id=pred.id,
                link_type=LINK_TYPE.get(str(d.get("type", "1")), "FS"),
                lag_minutes=lag_minutes,
                predecessor_uid=str(d["predecessor_uid"]),
                successor_uid=str(d["successor_uid"]),
            )
        )
        deps_saved += 1
    db.flush()

    mapped_n = sum(
        1
        for i in db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version.id).all()
        if i.work_type_id is not None and not i.is_summary and not i.is_milestone
    )
    stats = {
        **{k: parsed[k] for k in ("task_count", "dependency_count", "leaf_count", "summary_count", "milestone_count")},
        "imported_leaf_rows": imported_leaf,
        "mapped_work_type": mapped_n,
        "dependencies_saved": deps_saved,
        "observability": obs_counts,
        "kind": kind,
        "warnings": warnings[:50],
        "warning_count": len(warnings),
        "missing_data": parsed.get("missing_data") or {},
        "status_date": parsed["status_date"].isoformat() if parsed.get("status_date") else None,
        "note": "UID разных экспортов не связываются напрямую; baseline vs current — отдельные версии",
    }
    return version, stats
