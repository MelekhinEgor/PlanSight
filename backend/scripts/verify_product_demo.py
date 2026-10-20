#!/usr/bin/env python3
"""Проверки целостности product demo V7.3. Ненулевой exit при любой ошибке."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("PLANSIGHT_DATABASE_PATH", str(REPO / "data" / "plansight.db"))


def fail(msg: str) -> None:
    print("FAIL:", msg)
    raise SystemExit(1)


def main() -> int:
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.db import SessionLocal, init_db
    from app.db.models import Camera, Deviation, Frame, Project, ScheduleDependency, ScheduleItem, reset_engine
    from app.main import app
    from app.services.product.v42_api import settings_of
    from app.services.schedule.service import get_active_schedule

    get_settings.cache_clear()
    reset_engine()
    init_db()
    c = TestClient(app)
    pf = c.get("/api/portfolio").json()
    rows = pf.get("projects") or []
    for p in rows:
        name = (p.get("name") or "").lower()
        slug = (p.get("slug") or "").lower()
        if "cv lab" in name or slug == "cvlab":
            fail("CV Lab visible in product portfolio")
        if p.get("name") in ("T", "OV Test", "EV Test") or (p.get("name") or "").startswith("T "):
            fail(f"test project in portfolio: {p.get('name')}")

    db = SessionLocal()
    try:
        for cam in db.query(Camera).all():
            n = (cam.name or "").lower()
            # Lab-камера разрешена только на lab-проектах
            proj = db.get(Project, cam.project_id)
            s = settings_of(proj) if proj else {}
            is_lab = bool(s.get("is_lab") or (s.get("slug") or "").lower() == "cvlab")
            if "тест-камера" in n and not is_lab:
                fail(f"test camera in product project: {cam.name}")

        st = next((p for p in db.query(Project).all() if settings_of(p).get("slug") == "strogino"), None)
        if st:
            for d in (
                db.query(Deviation)
                .filter(Deviation.project_id == st.id, Deviation.lifecycle.in_(("OPEN", "ACKNOWLEDGED")))
                .all()
            ):
                details = json.loads(d.details_json or "{}")
                if details.get("signal_kind") == "CV_VERIFIED_FINDING" or d.code in (
                    "REQUIRED_EQUIPMENT_GAP",
                    "UNEXPECTED_EQUIPMENT_IN_ZONE",
                    "UNCONFIRMED_ACTIVITY",
                ):
                    eids = json.loads(d.evidence_ids_json or "[]")
                    # soft: если заявлен evidence, кадры должны принадлежать тому же проекту
                    for fid in eids:
                        fr = db.get(Frame, int(fid))
                        if fr and fr.project_id != st.id:
                            fail(f"evidence frame {fid} cross-project for deviation {d.id}")

            version = get_active_schedule(db, st.id)
            if version:
                deps = db.query(ScheduleDependency).filter(ScheduleDependency.schedule_version_id == version.id).count()
                items = (
                    db.query(ScheduleItem)
                    .filter(ScheduleItem.schedule_version_id == version.id, ScheduleItem.is_summary.is_(False))
                    .count()
                )
                if deps == 0 and items > 0:
                    print("WARN: Strogino active schedule has 0 dependencies — impact preview must show UNAVAILABLE")
                else:
                    print(f"OK strogino network deps={deps} leaves={items}")
    finally:
        db.close()

    print("PASS verify_product_demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
