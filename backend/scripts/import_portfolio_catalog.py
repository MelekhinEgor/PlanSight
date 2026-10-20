"""Импорт каталога ЖК в рабочую БД (без удаления демо-проектов).

По умолчанию читает backend/app/data/portfolio_catalog.json
(сборка из открытого датасета Betonij.ru — см. build_portfolio_catalog.py).
Пересобирает каталог при --rebuild. Заменяет только каталожные проекты
(BETONIJ_DECLARATIONS / PORTFOLIO_CATALOG / …).

Запуск::

  cd backend
  $env:PLANSIGHT_DATABASE_PATH="..\\data\\plansight.db"
  .venv/Scripts/python.exe scripts/import_portfolio_catalog.py --rebuild
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.db.migrate import ensure_schema_patches  # noqa: E402
from app.db.models import Organization, Project, ProjectObject  # noqa: E402
from app.services.product.company_groups import company_group_name  # noqa: E402
from app.services.product.slugs import CATALOG_DATA_ORIGINS  # noqa: E402
from app.services.product.v42_api import settings_of  # noqa: E402

CATALOG_PATH = ROOT / "app" / "data" / "portfolio_catalog.json"


def _load_catalog(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise SystemExit(f"bad catalog format: {path}")
    return data


def _wipe_catalog_projects(db) -> int:
    rows = db.query(Project).all()
    removed = 0
    for p in rows:
        s = settings_of(p)
        origin = str(s.get("data_origin") or "").upper()
        slug = str(s.get("slug") or "")
        if origin in CATALOG_DATA_ORIGINS or slug.startswith("cat-") or slug.startswith("domrf-"):
            db.query(ProjectObject).filter(ProjectObject.project_id == p.id).delete()
            db.delete(p)
            removed += 1
    db.flush()
    return removed


def _upsert_org(db, *, org_key: str, name: str, group_id: str) -> Organization:
    # organization.id — int PK; внешний ключ держим в settings.developer.id.
    # Ищем по имени + group_id, чтобы не плодить дубли.
    existing = (
        db.query(Organization)
        .filter(Organization.name == name, Organization.group_id == group_id)
        .order_by(Organization.id.asc())
        .first()
    )
    if existing:
        return existing
    org = Organization(name=name, group_id=group_id)
    db.add(org)
    db.flush()
    return org


def import_catalog(db, catalog: dict, *, replace: bool = True) -> dict[str, int]:
    if replace:
        wiped = _wipe_catalog_projects(db)
    else:
        wiped = 0

    created = 0
    orgs = 0
    seen_org: set[tuple[str, str]] = set()

    for group in catalog["groups"]:
        gid = str(group.get("id") or "").strip()
        gname = str(group.get("name") or company_group_name(gid) or gid)
        if not gid:
            continue
        for dev in group.get("developers") or []:
            dev_name = str(dev.get("name") or "").strip()
            dev_id = str(dev.get("id") or f"dev-{gid}-{dev_name}")
            if not dev_name:
                continue
            key = (dev_name, gid)
            if key not in seen_org:
                _upsert_org(db, org_key=dev_id, name=dev_name, group_id=gid)
                seen_org.add(key)
                orgs += 1
            for proj in dev.get("projects") or []:
                slug = str(proj.get("slug") or "").strip().lower()
                name = str(proj.get("name") or "").strip()
                if not slug or not name:
                    continue
                settings = {
                    "slug": slug,
                    "developer": {"id": dev_id, "name": dev_name, "groupId": gid},
                    "companyGroupId": gid,
                    "companyGroup": gname,
                    "region": proj.get("region") or "—",
                    "address": proj.get("address") or "",
                    "lat": float(proj.get("lat") or 55.75),
                    "lng": float(proj.get("lng") or 37.62),
                    "imageUrl": proj.get("imageUrl"),
                    "commissioning": proj.get("commissioning"),
                    "metro": proj.get("metro"),
                    "metroWalk": proj.get("metroWalk"),
                    "is_demo": False,
                    "data_origin": catalog.get("source") or "PORTFOLIO_CATALOG",
                    "source_graph": "CATALOG",
                    "source_time": "CATALOG",
                    "status_source": "CATALOG",
                    "progress_source": "NONE",
                    "kpi_kind": "CATALOG",
                    "badge_schedule": None,
                    "badge_photos": None,
                }
                p = Project(name=name, timezone="Europe/Moscow", settings_json=json.dumps(settings, ensure_ascii=False))
                db.add(p)
                db.flush()
                db.add(
                    ProjectObject(
                        project_id=p.id,
                        parent_id=None,
                        name="Корпус 1",
                        object_type="building",
                        lat=settings["lat"],
                        lng=settings["lng"],
                        sort_order=0,
                    )
                )
                created += 1
    db.commit()
    return {"wiped": wiped, "created": created, "organizations": orgs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import portfolio catalog into DB")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--from-json", type=Path, default=None, help="alternate catalog JSON")
    parser.add_argument("--rebuild", action="store_true", help="rebuild catalog JSON first")
    parser.add_argument("--keep-existing", action="store_true", help="do not wipe previous catalog rows")
    args = parser.parse_args(argv)

    if args.rebuild:
        from build_portfolio_catalog import main as build_main

        build_main([])

    path = args.from_json or args.catalog
    if not path.exists():
        from build_portfolio_catalog import main as build_main

        build_main([])
    catalog = _load_catalog(path)

    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    try:
        stats = import_catalog(db, catalog, replace=not args.keep_existing)
    finally:
        db.close()
    print("IMPORTED", stats, "from", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
