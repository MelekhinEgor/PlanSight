"""Привести весь портфель к «рабочему» виду без NO_DATA и без отставаний.

- Каталожным ЖК без КСГ — компактный график с прогрессом в норме
- Существующим графикам — fact ≈ plan (просроченные закрыты)
- Открытые findings/риски — закрыть (RESOLVED), у Строгино оставить максимум 1 мягкий

Запуск::

  cd backend
  $env:PLANSIGHT_DATABASE_PATH="..\\data\\plansight.db"
  .venv/Scripts/python.exe scripts/normalize_portfolio_healthy.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.db import SessionLocal, init_db  # noqa: E402
from app.db.migrate import ensure_schema_patches  # noqa: E402
from app.db.models import (  # noqa: E402
    Deviation,
    Project,
    ProjectObject,
    ScheduleDependency,
    ScheduleItem,
    ScheduleVersion,
    WorkType,
)
from app.services.product.demo_clock import demo_as_of_iso  # noqa: E402
from app.services.product.demo_integrity import build_alias_index, map_work_name  # noqa: E402
from app.services.product.slugs import is_catalog_project, project_slug  # noqa: E402
from app.services.product.v42_api import settings_of  # noqa: E402
from app.services.schedule.service import get_active_schedule  # noqa: E402

# Компактный шаблон КСГ: смещение дней относительно as_of (start_offset, end_offset, plan%)
HEALTHY_WORKS: list[tuple[str, str, str, str, float, int, int, float]] = [
    ("A01", "Подготовка", "Получение РД", "компл.", 1, -120, -100, 100),
    ("A02", "Подготовка", "Разработка ППР", "компл.", 1, -105, -85, 100),
    ("A03", "Подготовка", "Мобилизация техники", "компл.", 1, -90, -70, 100),
    ("A04", "Нулевой цикл", "Разработка котлована", "м3", 12000, -75, -45, 100),
    ("A05", "Нулевой цикл", "Устройство свайного поля", "шт", 180, -50, -25, 100),
    ("A06", "Нулевой цикл", "Гидроизоляция фундамента", "м2", 4200, -30, -10, 100),
    ("A07", "Каркас", "Возведение стен подземной части", "м3", 2800, -20, 5, 85),
    ("A08", "Каркас", "Перекрытия типовых этажей", "м2", 9600, -5, 40, 55),
    ("A09", "Каркас", "Монолитные работы", "м3", 3500, 0, 55, 40),
    ("A10", "Ограждающие", "Фасадные работы", "м2", 7800, 20, 90, 15),
    ("A11", "Инженерия", "Внутренние инженерные сети", "компл.", 1, 35, 110, 10),
    ("A12", "Отделка", "Черновая отделка", "м2", 15000, 50, 140, 5),
]


def _day(as_of: datetime, offset: int) -> datetime:
    return datetime(as_of.year, as_of.month, as_of.day) + timedelta(days=offset)


def _apply_on_track(db, version: ScheduleVersion, as_of: str) -> int:
    items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == version.id, ScheduleItem.is_summary.is_(False))
        .all()
    )
    n = 0
    for it in items:
        plan = float(it.planned_progress or 0)
        end = it.planned_finish.date().isoformat() if it.planned_finish else None
        overdue = bool(end and end < as_of)
        if plan >= 100 or overdue:
            target = 100.0
        elif plan > 0:
            # чуть не ниже плана, без «отставания» в health (порог plan-10)
            target = max(plan, min(100.0, plan + 2))
        else:
            target = 0.0
        if float(it.actual_progress or 0) != target:
            it.actual_progress = target
            n += 1
        # прогноз не хуже плана
        if it.planned_finish and (it.forecast_end is None or it.forecast_end > it.planned_finish):
            it.forecast_end = it.planned_finish
    return n


def _resolve_open_deviations(db, project_id: int, *, keep_open: int = 0) -> int:
    rows = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project_id,
            Deviation.lifecycle.in_(("OPEN", "ACKNOWLEDGED", "")),
        )
        .order_by(Deviation.id.asc())
        .all()
    )
    # также legacy status open без lifecycle
    extra = (
        db.query(Deviation)
        .filter(Deviation.project_id == project_id, Deviation.status.in_(("open", "OPEN")))
        .all()
    )
    seen = {r.id for r in rows}
    for r in extra:
        if r.id not in seen:
            rows.append(r)
    closed = 0
    for i, d in enumerate(rows):
        if i < keep_open:
            # оставляем мягкий DQ без производственного кода — переводим в ACKNOWLEDGED с низким риском
            details = {}
            try:
                details = json.loads(d.details_json or "{}")
            except Exception:
                details = {}
            details["note"] = "Контрольная точка наблюдения (не влияет на срок)"
            details["signal_kind"] = details.get("signal_kind") or "DATA_QUALITY"
            d.details_json = json.dumps(details, ensure_ascii=False)
            d.lifecycle = "ACKNOWLEDGED"
            d.status = "ACKNOWLEDGED"
            d.risk_score = 0.15
            d.heuristic_score = 0.15
            # чтобы health не считал production — сменим код если production
            from app.services.product.health import PRODUCTION_CODES

            if d.code in PRODUCTION_CODES or d.code == "SCHEDULE_LAG":
                d.code = "OBSERVATION_NOTE"
            continue
        d.lifecycle = "RESOLVED"
        d.status = "RESOLVED"
        d.resolved_at = datetime.utcnow()
        closed += 1
    return closed


def _ensure_healthy_schedule(db, project: Project, as_of_dt: datetime) -> bool:
    """Создать активный график, если нет. True если создан."""
    if get_active_schedule(db, project.id) is not None:
        return False

    slug = project_slug(settings_of(project)) or f"p{project.id}"
    buildings = [
        o.name
        for o in db.query(ProjectObject)
        .filter(ProjectObject.project_id == project.id, ProjectObject.object_type != "stage")
        .order_by(ProjectObject.sort_order.asc())
        .all()
    ]
    if not buildings:
        buildings = ["Корпус 1"]

    now = datetime.utcnow()
    root_id = f"{slug}-wbs-root"
    wbs = [{"id": root_id, "parent_id": None, "name": project.name, "code": "0", "level": 0, "sort_order": 0}]
    phase_ids: dict[str, str] = {}
    for i, phase in enumerate(sorted({w[1] for w in HEALTHY_WORKS})):
        nid = f"{slug}-wbs-{i+1}"
        phase_ids[phase] = nid
        wbs.append({"id": nid, "parent_id": root_id, "name": phase, "code": f"1.{i+1}", "level": 1, "sort_order": i + 1})

    version = ScheduleVersion(
        project_id=project.id,
        source_path=f"{slug}_healthy_schedule.xlsx",
        checksum=f"healthy-{slug}-{as_of_dt.date().isoformat()}",
        imported_at=now,
        is_active=True,
        kind="CURRENT",
        version_state="PUBLISHED",
        revision=1,
        published_at=now,
        updated_at=now,
        wbs_json=json.dumps(wbs, ensure_ascii=False),
        source_filename="healthy_schedule.xlsx",
    )
    db.add(version)
    db.flush()

    wt_by_code = {w.code: w.id for w in db.query(WorkType).all()}
    alias_index = build_alias_index()
    prev_id = None
    for i, (code, phase, name, unit, qty, start_off, end_off, plan) in enumerate(HEALTHY_WORKS):
        ps = _day(as_of_dt, start_off)
        pe = _day(as_of_dt, end_off)
        if pe < ps:
            pe = ps + timedelta(days=7)
        # факт: не ниже плана (для due → 100)
        as_of_s = as_of_dt.date().isoformat()
        if pe.date().isoformat() < as_of_s or plan >= 100:
            fact = 100.0
            plan_v = 100.0
        else:
            plan_v = float(plan)
            fact = float(plan)
        building = buildings[i % len(buildings)]
        wm = map_work_name(name, wt_by_code=wt_by_code, alias_index=alias_index)
        item = ScheduleItem(
            schedule_version_id=version.id,
            external_id=code,
            raw_name=name,
            work_type_id=wm.work_type_id,
            planned_start=ps,
            planned_finish=pe,
            building=building,
            building_normalized=building,
            building_source="demo_table",
            unit=unit,
            planned_quantity=float(qty),
            planned_progress=plan_v,
            actual_progress=fact,
            forecast_end=pe,
            actual_start=ps if fact > 0 else None,
            sort_order=i + 1,
            mapping_status=wm.mapping_status,
            canonical_work_code=wm.work_type_code,
            canonical_work_name=name,
            wbs_node_id=phase_ids.get(phase, root_id),
            observability_mode=wm.observability,
            observability_reason=wm.reason,
        )
        db.add(item)
        db.flush()
        if prev_id is not None:
            db.add(
                ScheduleDependency(
                    schedule_version_id=version.id,
                    predecessor_item_id=prev_id,
                    successor_item_id=item.id,
                    link_type="FS",
                    lag_minutes=0,
                    predecessor_uid=HEALTHY_WORKS[i - 1][0],
                    successor_uid=code,
                    link_source="EXPERT_APPROVED",
                )
            )
        prev_id = item.id
    return True


def run(*, strogino_keep_open: int = 1) -> dict:
    init_db()
    ensure_schema_patches()
    as_of = demo_as_of_iso()[:10]
    as_of_dt = datetime.fromisoformat(as_of)
    db = SessionLocal()
    stats = {
        "projects": 0,
        "schedules_created": 0,
        "progress_fixed": 0,
        "deviations_closed": 0,
        "strogino_kept_open": 0,
    }
    try:
        projects = db.query(Project).order_by(Project.id.asc()).all()
        for p in projects:
            s = settings_of(p)
            slug = project_slug(s)
            if slug == "cvlab":
                continue
            stats["projects"] += 1
            created = _ensure_healthy_schedule(db, p, as_of_dt)
            if created:
                stats["schedules_created"] += 1
            version = get_active_schedule(db, p.id)
            if version:
                stats["progress_fixed"] += _apply_on_track(db, version, as_of)
            keep = strogino_keep_open if slug == "strogino" else 0
            closed = _resolve_open_deviations(db, p.id, keep_open=keep)
            stats["deviations_closed"] += closed
            if slug == "strogino":
                stats["strogino_kept_open"] = keep
            # settings: убрать ложный DELAYED/NO_DATA из карточки
            if s.get("status") in ("NO_DATA", "DELAYED", "AT_RISK") or s.get("persona") in (
                "delayed",
                "at_risk",
            ):
                s["status"] = "ON_TRACK"
                s["persona"] = "on_track"
                s["status_source"] = "HEALTHY_NORMALIZE"
                p.settings_json = json.dumps(s, ensure_ascii=False)
        db.commit()
    finally:
        db.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize portfolio to ON_TRACK healthy state")
    parser.add_argument(
        "--strogino-keep-open",
        type=int,
        default=0,
        help="сколько мягких открытых сигналов оставить у Строгино (0 = все закрыть)",
    )
    args = parser.parse_args(argv)
    stats = run(strogino_keep_open=max(0, args.strogino_keep_open))
    print("NORMALIZED", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
