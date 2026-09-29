"""V6 Sprint A — аудит всех демо-проектов; отчёт JSON + HTML.

Запуск (из backend/):
  .venv\\Scripts\\python.exe scripts\\audit_demo_integrity.py
  .venv\\Scripts\\python.exe scripts\\audit_demo_integrity.py --db-path ../data/plansight.db
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seed_guard import DEFAULT_DEMO_DB, apply_db_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit demo DB integrity (V6 A)")
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs" / "audit",
    )
    args = parser.parse_args(argv)

    db_path = apply_db_path((args.db_path or Path("../data/plansight.db")).resolve())
    from app.db.migrate import ensure_schema_patches
    from app.db.models import (
        Detection,
        Deviation,
        Frame,
        Project,
        ScheduleDependency,
        ScheduleItem,
        ScheduleVersion,
        SessionLocal,
        init_db,
    )
    from app.services.product.demo_integrity import (
        audit_schedule_items,
        write_html_report,
        write_json,
    )

    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    try:
        projects = db.query(Project).order_by(Project.id.asc()).all()
        out_projects = []
        tot_items = tot_deps = tot_wt_null = tot_fs = 0
        for p in projects:
            settings = {}
            try:
                settings = json.loads(p.settings_json or "{}")
            except Exception:
                pass
            version = (
                db.query(ScheduleVersion)
                .filter(ScheduleVersion.project_id == p.id, ScheduleVersion.is_active.is_(True))
                .first()
            )
            items: list = []
            deps: list = []
            if version:
                items = (
                    db.query(ScheduleItem)
                    .filter(ScheduleItem.schedule_version_id == version.id)
                    .all()
                )
                deps = (
                    db.query(ScheduleDependency)
                    .filter(ScheduleDependency.schedule_version_id == version.id)
                    .all()
                )
            sched = audit_schedule_items(items, deps)
            tot_items += sched["items"]
            tot_deps += sched["deps"]
            tot_wt_null += sched["work_type_null"]
            tot_fs += sched["fs_date_violations"]
            # выборка leaf matrix
            matrix = []
            for it in sorted(items, key=lambda x: x.sort_order or 0)[:20]:
                matrix.append(
                    {
                        "external_id": it.external_id,
                        "name": it.raw_name,
                        "work_type_id": it.work_type_id,
                        "canonical_work_code": it.canonical_work_code,
                        "observability_mode": it.observability_mode,
                        "mapping_status": it.mapping_status,
                        "building": it.building,
                        "building_source": it.building_source,
                    }
                )
            out_projects.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "slug": settings.get("slug"),
                    "is_demo": settings.get("is_demo"),
                    "data_origin": settings.get("data_origin"),
                    "badge_schedule": settings.get("badge_schedule"),
                    "badge_photos": settings.get("badge_photos"),
                    "status_settings": settings.get("status"),
                    "schedule": sched,
                    "leaf_sample": matrix,
                }
            )

        frames = db.query(Frame).count()
        dets = db.query(Detection).count()
        devs = db.query(Deviation).all()
        cv_verified = 0
        for d in devs:
            try:
                det = json.loads(d.details_json or "{}")
            except Exception:
                det = {}
            if det.get("signal_kind") == "CV_VERIFIED_FINDING":
                cv_verified += 1

        # проверки DoD A (цели после миграции)
        strogino = next((x for x in out_projects if x.get("slug") == "strogino"), None)
        cv_lab = next((x for x in out_projects if x.get("slug") == "cvlab"), None)
        dod = {
            "work_type_null_total": tot_wt_null,
            "fs_violations_total": tot_fs,
            "strogino_fs_violations": (strogino or {}).get("schedule", {}).get("fs_date_violations"),
            "strogino_approved_fs_violations": (strogino or {}).get("schedule", {}).get(
                "approved_fs_violations"
            ),
            "strogino_work_type_null": (strogino or {}).get("schedule", {}).get("work_type_null"),
            "frames": frames,
            "cv_verified_findings": cv_verified,
            "cv_lab_present": cv_lab is not None,
            "pass_zero_approved_fs_violations": tot_fs == 0
            or all(
                (p.get("schedule") or {}).get("approved_fs_violations", 0) == 0 for p in out_projects
            ),
            "pass_strogino_mapped": strogino is not None
            and (strogino.get("schedule") or {}).get("work_type_null", 999) == 0,
            "pass_no_cv_without_frames": frames > 0 or cv_verified == 0,
        }

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": str(db_path),
            "totals": {
                "projects": len(out_projects),
                "items": tot_items,
                "deps": tot_deps,
                "work_type_null": tot_wt_null,
                "fs_date_violations": tot_fs,
                "frames": frames,
                "detections": dets,
                "deviations": len(devs),
                "cv_verified_findings": cv_verified,
            },
            "dod_a": dod,
            "projects": out_projects,
        }
        out_dir = args.out_dir.resolve()
        json_path = out_dir / "demo_integrity.json"
        html_path = out_dir / "demo_integrity.html"
        write_json(json_path, report)
        write_html_report(html_path, report)
        print("WROTE", json_path)
        print("WROTE", html_path)
        print("TOTALS", report["totals"])
        print("DOD_A", json.dumps(dod, ensure_ascii=False))
        # audit всегда exit 0; pass обеспечивает verify-скрипт
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
