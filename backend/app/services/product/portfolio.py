"""Адаптеры portfolio и schedule workspace для фронта PlanSight_v2 (V4 P1 / V4.2)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    Camera,
    Deviation,
    Frame,
    InferenceRun,
    Project,
    ProjectObject,
    ScheduleDependency,
    ScheduleItem,
    ScheduleVersion,
    WorkEquipmentProfile,
    WorkType,
)
from app.services.product.v42_api import (
    developer_payload,
    display_building_name,
    list_objects_from_table,
    parse_network_recovery,
    serialize_project_object,
    settings_of,
)
from app.services.product.slugs import is_visible_in_portfolio
from app.services.product.demo_clock import demo_as_of_iso
from app.services.product.health import compute_project_health, health_to_dict
from app.services.schedule.service import get_active_schedule

# Совместимый alias (на import; в call sites лучше demo_as_of_iso()).
DEMO_AS_OF = demo_as_of_iso()


def is_lab_project(project: Project | None = None, settings: dict[str, Any] | None = None) -> bool:
    """Технический стенд CV Lab — скрыт из пользовательского портфеля (V7.1)."""
    from app.services.product.slugs import is_lab_slug

    s = settings if settings is not None else (_settings(project) if project else {})
    if is_lab_slug(s):
        return True
    name = (project.name if project else "") or ""
    return "cv lab" in name.lower()


def _settings(p: Project) -> dict[str, Any]:
    return settings_of(p)


def _analysis_source(
    *,
    has_schedule: bool,
    has_obs: bool,
    expert_confirmed: bool,
) -> str:
    if expert_confirmed:
        return "EXPERT"
    if has_schedule and has_obs:
        return "COMBINED"
    if has_obs:
        return "OBSERVATION"
    return "SCHEDULE"


def _iso_day(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.date().isoformat()


def _parse_as_of(as_of: str | None) -> datetime:
    if not as_of:
        return datetime.fromisoformat(demo_as_of_iso())
    try:
        raw = as_of.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return datetime.fromisoformat(demo_as_of_iso())


def _diff_days(a: str, b: str) -> int:
    da = datetime.fromisoformat(a[:10])
    db = datetime.fromisoformat(b[:10])
    return (db.date() - da.date()).days


def Path_name(path: str) -> str:
    from pathlib import Path

    return Path(path).name if path else "schedule"


def _version_state(v: ScheduleVersion) -> str:
    state = (getattr(v, "version_state", None) or "").upper()
    if state in ("IMPORTED", "WORKING", "PUBLISHED", "ARCHIVED"):
        return state
    if v.is_active:
        return "PUBLISHED"
    return "IMPORTED"


def _portfolio_objects(db: Session, project_id: int, settings: dict[str, Any]) -> list[dict[str, Any]]:
    table_objs = list_objects_from_table(db, project_id)
    if table_objs:
        # Карта / фильтры: только листовые корпуса (без этапов)
        parent_ids = {str(o["parent_id"]) for o in table_objs if o.get("parent_id") is not None}
        leaves = [
            o
            for o in table_objs
            if str(o["id"]) not in parent_ids
            and (o.get("object_type") or o.get("type") or "building") != "stage"
        ]
        if not leaves:
            leaves = [o for o in table_objs if (o.get("object_type") or "") != "stage"] or table_objs
        return [
            {
                "id": str(o["id"]),
                "name": o["name"],
                "type": o.get("object_type") or o.get("type") or "building",
                "lat": float(o["lat"]) if o.get("lat") is not None else float(settings.get("lat") or 55.75),
                "lng": float(o["lng"]) if o.get("lng") is not None else float(settings.get("lng") or 37.62),
            }
            for o in leaves
        ]
    names = settings.get("objects")
    base_lat = float(settings.get("lat") or 55.75)
    base_lng = float(settings.get("lng") or 37.62)
    if isinstance(names, list) and names:
        return [
            {
                "id": f"{project_id}-obj-{i + 1}",
                "name": str(name),
                "type": "building",
                "lat": base_lat,
                "lng": base_lng,
            }
            for i, name in enumerate(names)
        ]
    return []


def build_portfolio(
    db: Session,
    as_of: str | None = None,
    *,
    include_lab: bool = False,
) -> dict[str, Any]:
    """Показатели KPI портфеля — единственный источник статуса/KPI: ProjectHealthService (V7.2)."""
    ao = _parse_as_of(as_of or demo_as_of_iso())
    projects = db.query(Project).order_by(Project.id.asc()).all()
    rows: list[dict[str, Any]] = []
    for p in projects:
        settings = _settings(p)
        if not is_visible_in_portfolio(settings, include_lab=include_lab):
            continue
        health = compute_project_health(db, p, as_of=as_of or demo_as_of_iso())
        version = get_active_schedule(db, p.id)
        acts_n = 0
        if version:
            acts_n = (
                db.query(ScheduleItem)
                .filter(
                    ScheduleItem.schedule_version_id == version.id,
                    ScheduleItem.is_summary.is_(False),
                )
                .count()
            )
        developer = developer_payload(settings)
        group_id = (developer or {}).get("groupId") if developer else None
        group_id = group_id or settings.get("companyGroupId") or settings.get("group_id")
        group_name = settings.get("companyGroup") or settings.get("company_group")
        if not group_name and group_id:
            group_name = {
                "pik": "ПИК",
                "krost": "Концерн КРОСТ",
                "dars-development": "DARS Development",
            }.get(str(group_id))
        lat = float(settings.get("lat") if settings.get("lat") is not None else 55.75)
        lng = float(settings.get("lng") if settings.get("lng") is not None else 37.62)
        objects = _portfolio_objects(db, p.id, settings)
        badge_schedule = settings.get("badge_schedule")
        if badge_schedule and any(x in str(badge_schedule).lower() for x in ("учеб", "демо", "demo", "synth")):
            badge_schedule = None
        badge_photos = settings.get("badge_photos")
        if badge_photos and any(x in str(badge_photos).lower() for x in ("учеб", "демо", "demo", "synth")):
            badge_photos = None
        last_analysis_date = health.as_of
        if health.last_cv_analysis_at:
            last_analysis_date = health.last_cv_analysis_at[:10]
        elif health.last_observation_at:
            last_analysis_date = health.last_observation_at[:10]
        elif version and version.imported_at:
            last_analysis_date = version.imported_at.date().isoformat()
        rows.append(
            {
                "id": str(p.id),
                "developer": (developer or {}).get("name") if developer else (settings.get("developer") or "—"),
                "companyGroupId": group_id,
                "companyGroup": group_name,
                "name": p.name,
                "region": settings.get("region") or "—",
                "address": settings.get("address") or "",
                "status": health.status,
                "status_reason": health.status_reason,
                "problemWorks": health.problem_works,
                "openFindings": health.open_production_findings,
                "openFindingsTotal": health.open_findings,
                "openDataQualityFindings": health.open_data_quality_findings,
                "maxDeviation": health.max_deviation,
                "maxDeviation_kind": "SCHEDULE_DAYS",
                "severityWorks": {
                    "critical": health.works_critical,
                    "high": health.works_high,
                    "medium": health.works_medium,
                    "normal": health.works_normal,
                },
                "change": int(settings.get("change") or 0),
                "change_source": "SCHEDULE" if acts_n else "NONE",
                "lastAnalysis": health.last_analysis,
                "lastAnalysisDate": last_analysis_date,
                "lastAnalysis_kind": health.last_analysis_kind,
                "lastObservationAt": health.last_observation_at,
                "lastCvAnalysisAt": health.last_cv_analysis_at,
                "lastScheduleUpdate": version.imported_at.isoformat() if version and version.imported_at else None,
                "totalWorks": acts_n,
                "progress": health.progress,
                "progress_source": health.progress_source,
                "status_source": health.status_source,
                "analysis_source": health.analysis_source,
                "data_freshness": health.data_freshness,
                "kpi_kind": "SERVER_COMPUTED",
                "lat": lat,
                "lng": lng,
                "objects": objects,
                "slug": settings.get("slug"),
                "imageUrl": settings.get("imageUrl") or settings.get("image_url"),
                "commissioning": settings.get("commissioning"),
                "metro": settings.get("metro"),
                "metroWalk": settings.get("metroWalk") or settings.get("metro_walk"),
                "has_schedule": version is not None,
                "data_status": "OK" if acts_n else "NO_DATA",
                "is_demo": False,
                "data_origin": settings.get("data_origin"),
                "source_graph": settings.get("source_graph"),
                "badge_schedule": badge_schedule,
                "badge_photos": badge_photos,
                "as_of": settings.get("as_of") or health.as_of,
                "source_flags": {
                    "status": health.status_source,
                    "analysis": health.analysis_source,
                    "progress": health.progress_source,
                    "kpi": "SERVER_COMPUTED",
                    "last_analysis": health.last_analysis_kind,
                    "schedule": settings.get("source_graph") or "UNKNOWN",
                    "photos": "OBSERVATION" if health.last_observation_at else "NONE",
                },
            }
        )
    total_problems = sum(r["problemWorks"] for r in rows)
    trend = [{"day": ao.strftime("%d %b"), "deviations": total_problems}]
    return {
        "as_of": ao.date().isoformat(),
        "projects": rows,
        "trend": trend,
        "include_lab": include_lab,
        "meta": {
            "as_of": ao.date().isoformat(),
            "project_count": len(rows),
            "note": "KPI from ProjectHealthService; lab/test projects hidden; openFindings=production",
            "trend_kind": "as_of_snapshot",
            "kpi_kind": "SERVER_COMPUTED",
        },
    }



def _norm_building(name: str | None) -> str:
    key = " ".join((name or "").strip().lower().split())
    # Алиасы одного и того же узла площадки
    if key in {"common", "общие работы", "общие", "без корпуса"}:
        if key in {"common", "общие работы", "общие"}:
            return "общие работы"
    return key


def _object_subtree_ids(db: Session, project_id: int, root_id: int) -> set[int]:
    """Идентификатор object_id и все потомки в project_object (этап → корпуса)."""
    rows = (
        db.query(ProjectObject.id, ProjectObject.parent_id)
        .filter(ProjectObject.project_id == project_id)
        .all()
    )
    children: dict[int | None, list[int]] = {}
    for oid, parent_id in rows:
        children.setdefault(parent_id, []).append(int(oid))
    out: set[int] = set()
    stack = [int(root_id)]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children.get(cur, []))
    return out


def _is_short_building_alias(name: str | None) -> bool:
    """Короткие коды камеры (К1/К2), не имена корпусов из КСГ Строгино."""
    key = _norm_building(name)
    if not key:
        return False
    if key in {"к1", "к2", "k1", "k2"}:
        return True
    # «К1», «К-2» без слова «корпус»
    compact = key.replace(" ", "").replace("-", "")
    return len(compact) <= 3 and compact[:1] in {"к", "k"} and compact[1:].isdigit()


def cleanup_orphan_project_objects(db: Session, project_id: int) -> int:
    """Удаляет листья без работ в активном графике (мусор от camera hint / старых сидов)."""
    version = get_active_schedule(db, project_id)
    used: set[int] = set()
    schedule_names: set[str] = set()
    if version:
        for (oid,) in (
            db.query(ScheduleItem.project_object_id)
            .filter(
                ScheduleItem.schedule_version_id == version.id,
                ScheduleItem.project_object_id.isnot(None),
            )
            .distinct()
            .all()
        ):
            if oid is not None:
                used.add(int(oid))
        for (b,) in (
            db.query(ScheduleItem.building)
            .filter(
                ScheduleItem.schedule_version_id == version.id,
                ScheduleItem.building.isnot(None),
                ScheduleItem.building != "",
            )
            .distinct()
            .all()
        ):
            if b:
                schedule_names.add(_norm_building(b))

    rows = (
        db.query(ProjectObject)
        .filter(ProjectObject.project_id == project_id)
        .order_by(ProjectObject.id.asc())
        .all()
    )
    by_parent: dict[int | None, list[ProjectObject]] = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)

    def has_used_descendant(node: ProjectObject) -> bool:
        if node.id in used:
            return True
        return any(has_used_descendant(ch) for ch in by_parent.get(node.id, []))

    removed = 0
    # Сначала листья без работ и без детей; плюс короткие алиасы К1/К2 вне графика
    changed = True
    while changed:
        changed = False
        rows = (
            db.query(ProjectObject)
            .filter(ProjectObject.project_id == project_id)
            .order_by(ProjectObject.id.desc())
            .all()
        )
        by_parent = {}
        for r in rows:
            by_parent.setdefault(r.parent_id, []).append(r)
        for r in rows:
            kids = by_parent.get(r.id, [])
            if kids:
                continue
            name_key = _norm_building(r.name)
            junk_alias = (
                _is_short_building_alias(r.name)
                and name_key not in schedule_names
                and (r.object_type or "") in ("building", "site", "")
            )
            if r.id in used and not junk_alias:
                continue
            if r.id not in used or junk_alias:
                db.delete(r)
                removed += 1
                changed = True
        if changed:
            db.flush()

    # Пустые этапы без используемых потомков
    rows = db.query(ProjectObject).filter(ProjectObject.project_id == project_id).all()
    by_parent = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r)
    for r in list(rows):
        if (r.object_type or "") != "stage":
            continue
        if has_used_descendant(r):
            continue
        if by_parent.get(r.id):
            continue
        db.delete(r)
        removed += 1
    if removed:
        db.flush()
    return removed


def ensure_project_objects_from_buildings(db: Session, project_id: int) -> dict[str, ProjectObject]:
    """Операция upsert листовых project_object по корпусам графика; вернуть name→row.

    Камерные building_hint больше не создают отдельные узлы дерева (давали «К1»/дубли).
    """
    by_norm: dict[str, ProjectObject] = {}
    existing = (
        db.query(ProjectObject)
        .filter(ProjectObject.project_id == project_id)
        .order_by(ProjectObject.sort_order.asc(), ProjectObject.id.asc())
        .all()
    )
    for row in existing:
        key = _norm_building(row.name)
        # При дубликатах предпочитаем узел с родителем (в иерархии этапов)
        prev = by_norm.get(key)
        if prev is None or (prev.parent_id is None and row.parent_id is not None):
            by_norm[key] = row

    names: list[str] = []
    version = get_active_schedule(db, project_id)
    if version:
        for (b,) in (
            db.query(ScheduleItem.building)
            .filter(
                ScheduleItem.schedule_version_id == version.id,
                ScheduleItem.building.isnot(None),
                ScheduleItem.building != "",
            )
            .distinct()
            .all()
        ):
            if b and b not in names:
                names.append(b)

    # Найти этап-контейнер для «общих» / без корпуса, если есть этап 2 / site-родитель
    site_parent_id: int | None = None
    for row in existing:
        if (row.object_type or "") == "stage" and "2" in (row.name or ""):
            site_parent_id = row.id
            break

    sort_base = max((r.sort_order for r in existing), default=-1) + 1
    for i, name in enumerate(names):
        key = _norm_building(name)
        if not key:
            continue
        if key in by_norm:
            continue
        parent_id = None
        otype = "building"
        if key == "common":
            parent_id = site_parent_id
            otype = "site"
        row = ProjectObject(
            project_id=project_id,
            parent_id=parent_id,
            name=name.strip(),
            object_type=otype,
            sort_order=sort_base + i,
        )
        db.add(row)
        db.flush()
        by_norm[key] = row
    return by_norm


def resolve_schedule_item_objects(db: Session, project_id: int, version_id: int | None = None) -> int:
    """Проставить schedule_item.project_object_id по имени корпуса. Число обновлений."""
    by_norm = ensure_project_objects_from_buildings(db, project_id)
    q = db.query(ScheduleItem)
    if version_id is not None:
        q = q.filter(ScheduleItem.schedule_version_id == version_id)
    else:
        version = get_active_schedule(db, project_id)
        if not version:
            return 0
        q = q.filter(ScheduleItem.schedule_version_id == version.id)
    updated = 0
    for it in q.all():
        key = _norm_building(it.building_normalized or it.building)
        row = by_norm.get(key) if key else None
        oid = row.id if row else None
        if it.project_object_id != oid:
            it.project_object_id = oid
            updated += 1
    if updated:
        db.flush()
    return updated


def _profile_id_for_item(db: Session, it: ScheduleItem, cache: dict[str, str | None]) -> str | None:
    """Поле expected_equipment_profile_id из work_type / canonical → work_equipment_profile."""
    keys: list[str] = []
    if it.canonical_work_code:
        keys.append(str(it.canonical_work_code))
    if it.work_type_id:
        wt = db.get(WorkType, it.work_type_id)
        if wt:
            keys.append(wt.code)
            keys.append(str(wt.id))
    for k in keys:
        if k in cache:
            return cache[k]
    for k in keys:
        row = (
            db.query(WorkEquipmentProfile)
            .filter(WorkEquipmentProfile.work_type_key == k)
            .order_by(WorkEquipmentProfile.id.asc())
            .first()
        )
        if row:
            for kk in keys:
                cache[kk] = k
            return k
    for k in keys:
        cache[k] = None
    return None


def list_project_objects(db: Session, project_id: int) -> list[dict[str, Any]]:
    """Предпочитать таблицу project_object; синк из buildings если пусто; дроп orphan."""
    p = db.get(Project, project_id)
    if not p:
        return []
    ensure_project_objects_from_buildings(db, project_id)
    resolve_schedule_item_objects(db, project_id)
    cleanup_orphan_project_objects(db, project_id)
    # Камера с коротким hint вроде «К1» не должна плодить узлы — подчистим hint к реальному корпусу при возможности
    _normalize_camera_hints(db, project_id)
    db.commit()
    table_rows = (
        db.query(ProjectObject)
        .filter(ProjectObject.project_id == project_id)
        .order_by(ProjectObject.sort_order.asc(), ProjectObject.id.asc())
        .all()
    )
    if table_rows:
        return [serialize_project_object(r) for r in table_rows]

    settings = _settings(p)
    names = settings.get("objects")
    if isinstance(names, list) and names:
        return [
            {
                "id": f"{project_id}-obj-{i + 1}",
                "project_id": str(project_id),
                "parent_id": None,
                "name": str(name),
                "object_type": "building",
                "type": "building",
                "lat": settings.get("lat"),
                "lng": settings.get("lng"),
                "sort_order": i,
            }
            for i, name in enumerate(names)
        ]
    return [
        {
            "id": f"{project_id}-obj-1",
            "project_id": str(project_id),
            "parent_id": None,
            "name": "Объект (без корпусов в графике)",
            "object_type": "building",
            "type": "building",
            "lat": settings.get("lat"),
            "lng": settings.get("lng"),
            "sort_order": 0,
        }
    ]


def _normalize_camera_hints(db: Session, project_id: int) -> None:
    """Не оставляем коротких алиасов (К1) как building_hint, если в графике есть нормальные корпуса."""
    version = get_active_schedule(db, project_id)
    schedule_names: set[str] = set()
    if version:
        for (b,) in (
            db.query(ScheduleItem.building)
            .filter(
                ScheduleItem.schedule_version_id == version.id,
                ScheduleItem.building.isnot(None),
                ScheduleItem.building != "",
            )
            .distinct()
            .all()
        ):
            if b:
                schedule_names.add(_norm_building(b))

    for cam in db.query(Camera).filter(Camera.project_id == project_id).all():
        hint = (cam.building_hint or "").strip()
        if not hint:
            continue
        key = _norm_building(hint)
        if key in schedule_names:
            continue
        # Короткий код корпуса без точки — сбрасываем, чтобы не плодить мусор в дереве
        if _is_short_building_alias(hint) or key not in schedule_names:
            if _is_short_building_alias(hint) or len(hint) <= 3:
                cam.building_hint = None
                db.flush()

    # Статус PROPOSED/устаревшие привязки К1/К2, которых нет в КСГ — удаляем (building NOT NULL)
    from app.db.models import CameraZoneBinding

    for bind in (
        db.query(CameraZoneBinding)
        .filter(CameraZoneBinding.project_id == project_id)
        .all()
    ):
        bname = (bind.building or "").strip()
        if not bname:
            db.delete(bind)
            continue
        if _norm_building(bname) in schedule_names:
            continue
        if not _is_short_building_alias(bname):
            continue
        db.delete(bind)
    db.flush()

def list_schedule_versions_v2(db: Session, project_id: int) -> list[dict[str, Any]]:
    versions = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == project_id)
        .order_by(ScheduleVersion.id.desc())
        .all()
    )
    out = []
    for v in versions:
        fname = getattr(v, "source_filename", None) or Path_name(v.source_path)
        out.append(
            {
                "id": str(v.id),
                "version": v.id,
                "uploaded_at": v.imported_at.isoformat() if v.imported_at else datetime.utcnow().isoformat(),
                "is_active": v.is_active,
                "source_filename": fname,
                "row_count": db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == v.id).count(),
                "warning_count": 0,
                "version_state": _version_state(v),
                "parent_version_id": str(v.parent_version_id) if getattr(v, "parent_version_id", None) else None,
                "updated_at": (v.updated_at or v.imported_at).isoformat()
                if (getattr(v, "updated_at", None) or v.imported_at)
                else None,
                "published_at": v.published_at.isoformat() if getattr(v, "published_at", None) else None,
                "plan_kind": v.kind,
                "revision": int(getattr(v, "revision", 1) or 1),
            }
        )
    return out


def build_schedule_workspace(
    db: Session,
    project_id: int,
    version_id: int | None = None,
    object_id: int | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    settings = _settings(project) if project else {}
    # Демо: по умолчанию срез = сегодня (Москва). Явный ?as_of= и старый settings.as_of
    # не должны «замораживать» кнопку «К актуальной дате» на дату сида.
    ao = _parse_as_of(as_of or demo_as_of_iso())
    ao_day = ao.date().isoformat()
    versions = list_schedule_versions_v2(db, project_id)
    version: ScheduleVersion | None = None
    if version_id is not None:
        version = db.get(ScheduleVersion, version_id)
        if version and version.project_id != project_id:
            version = None
    if version is None:
        version = get_active_schedule(db, project_id)
    if version is None:
        return {
            "project_id": str(project_id),
            "active_version": None,
            "wbs": [],
            "activities": [],
            "dependencies": [],
            "network_recovery": None,
            "selected_object_id": str(object_id) if object_id else None,
            "analysis": {"as_of": ao_day, "status": "NO_SCHEDULE"},
            "meta": {
                "as_of": ao_day,
                "is_demo": bool(settings.get("is_demo")),
                "badge_schedule": settings.get("badge_schedule"),
                "data_origin": settings.get("data_origin"),
                "source_graph": settings.get("source_graph"),
            },
        }

    resolve_schedule_item_objects(db, project_id, version.id)
    db.commit()

    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == version.id)
        .order_by(ScheduleItem.sort_order.asc(), ScheduleItem.planned_start.asc(), ScheduleItem.id.asc())
        .all()
    )
    if object_id is not None:
        allowed = _object_subtree_ids(db, project_id, int(object_id))
        items = [it for it in items if it.project_object_id in allowed]

    wbs: list[dict[str, Any]] = []
    try:
        raw_wbs = json.loads(getattr(version, "wbs_json", None) or "[]")
        if isinstance(raw_wbs, list) and raw_wbs:
            wbs = raw_wbs
    except Exception:
        wbs = []

    if not wbs:
        buildings: dict[str, str] = {}
        root_id = f"wbs-{version.id}-root"
        wbs = [
            {
                "id": root_id,
                "parent_id": None,
                "name": "График",
                "code": "1",
                "level": 0,
                "sort_order": 1,
            }
        ]
        for it in items:
            b = display_building_name((it.building or "").strip() or None)
            if b not in buildings:
                nid = f"wbs-{version.id}-b-{len(buildings) + 1}"
                buildings[b] = nid
                wbs.append(
                    {
                        "id": nid,
                        "parent_id": root_id,
                        "name": b,
                        "code": f"1.{len(buildings)}",
                        "level": 1,
                        "sort_order": len(buildings),
                    }
                )
        for it in items:
            if not it.wbs_node_id:
                b = display_building_name((it.building or "").strip() or None)
                it.wbs_node_id = buildings.get(b, root_id)

    # При фильтре по объекту — только WBS-узлы оставшихся работ
    if object_id is not None and wbs:
        used = {it.wbs_node_id for it in items if it.wbs_node_id}
        by_id = {n["id"]: n for n in wbs if isinstance(n, dict) and n.get("id")}
        keep: set[str] = set()
        for nid in used:
            cur = nid
            while cur and cur in by_id and cur not in keep:
                keep.add(cur)
                cur = by_id[cur].get("parent_id")
        if keep:
            wbs = [n for n in wbs if n.get("id") in keep]

    # Человекочитаемые имена узлов WBS (COMMON → Общие работы)
    for n in wbs:
        if not isinstance(n, dict):
            continue
        nm = n.get("name")
        if isinstance(nm, str) and nm.strip():
            mapped = display_building_name(nm)
            if mapped != nm:
                n["name"] = mapped

    profile_cache: dict[str, str | None] = {}
    activities = []
    for i, it in enumerate(items):
        if it.is_summary:
            continue
        start = _iso_day(it.planned_start)
        end = _iso_day(it.planned_finish)
        dur = None
        if it.planned_start and it.planned_finish:
            dur = max(1, (it.planned_finish.date() - it.planned_start.date()).days + 1)
        code = it.external_id or str(it.id)
        activities.append(
            {
                "id": str(it.id),
                "wbs_node_id": it.wbs_node_id,
                "external_id": it.external_id,
                "code": code,
                "name": it.raw_name,
                "canonical_work_id": f"cw-{it.canonical_work_code}" if it.canonical_work_code else None,
                "canonical_work_code": it.canonical_work_code,
                "canonical_work_name": it.canonical_work_name,
                "mapping_status": it.mapping_status or it.observability_mode or "UNMAPPED",
                "expected_equipment_profile_id": _profile_id_for_item(db, it, profile_cache),
                "unit": it.unit,
                "actual_start": _iso_day(it.actual_start),
                "planned_start": start,
                "planned_end": end,
                "planned_duration": dur,
                "planned_quantity": it.planned_quantity,
                "planned_progress": it.planned_progress,
                "actual_progress": it.actual_progress,
                "forecast_end": _iso_day(it.forecast_end) or end,
                "activity_type": "MILESTONE" if it.is_milestone else "TASK",
                "sort_order": it.sort_order or (i + 1),
                "building": display_building_name(it.building),
                "project_object_id": str(it.project_object_id) if it.project_object_id else None,
                "observability_mode": it.observability_mode,
            }
        )

    act_ids = {a["id"] for a in activities}
    deps_rows = (
        db.query(ScheduleDependency)
        .filter(ScheduleDependency.schedule_version_id == version.id)
        .all()
    )
    dependencies = []
    for d in deps_rows:
        if object_id is not None:
            if str(d.successor_item_id) not in act_ids or str(d.predecessor_item_id) not in act_ids:
                continue
        lag_days = int(round((d.lag_minutes or 0) / (60 * 24)))
        dependencies.append(
            {
                "id": str(d.id),
                "successor_activity_id": str(d.successor_item_id),
                "predecessor_activity_id": str(d.predecessor_item_id),
                "predecessor_reference": str(d.predecessor_uid or d.predecessor_item_id),
                "relation_type": (d.link_type or "FS").upper(),
                "lag_text": f"{lag_days}d" if lag_days else None,
                "lag_days": lag_days,
                "raw_expression": f"{d.predecessor_uid or d.predecessor_item_id}{d.link_type or 'FS'}",
            }
        )

    active_meta = next((v for v in versions if v["id"] == str(version.id)), None)
    if active_meta is None:
        active_meta = {
            "id": str(version.id),
            "version": version.id,
            "uploaded_at": version.imported_at.isoformat() if version.imported_at else datetime.utcnow().isoformat(),
            "is_active": version.is_active,
            "source_filename": getattr(version, "source_filename", None) or Path_name(version.source_path),
            "row_count": len(activities),
            "warning_count": 0,
            "version_state": _version_state(version),
            "parent_version_id": None,
            "updated_at": version.imported_at.isoformat() if version.imported_at else None,
            "published_at": version.imported_at.isoformat() if version.is_active and version.imported_at else None,
            "plan_kind": version.kind,
        }

    network_recovery = parse_network_recovery(getattr(version, "network_recovery_json", None))

    return {
        "project_id": str(project_id),
        "active_version": active_meta,
        "wbs": wbs,
        "activities": activities,
        "dependencies": dependencies,
        "network_recovery": network_recovery,
        "selected_object_id": str(object_id) if object_id else None,
        "analysis": {
            "as_of": ao_day,
            "status": "OK" if activities else "NO_SCHEDULE",
        },
        "meta": {
            "as_of": ao_day,
            "is_demo": bool(settings.get("is_demo")),
            "badge_schedule": settings.get("badge_schedule") or ("Учебный график" if settings.get("is_demo") else None),
            "badge_photos": settings.get("badge_photos"),
            "data_origin": settings.get("data_origin"),
            "source_graph": settings.get("source_graph"),
        },
    }
