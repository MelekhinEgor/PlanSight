"""Smoke-проверки wiring V4.2 (object FK, форма deviations, apply recovery, mapping)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"


def req(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(r, timeout=15) as resp:
        raw = resp.read().decode()
        return resp.status, json.loads(raw) if raw else {}


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.db.models import Project, ScheduleItem, ScheduleVersion
    from app.services.product.portfolio import resolve_schedule_item_objects

    init_db()
    db = SessionLocal()
    p = db.query(Project).first()
    if not p:
        print("SKIP: no project — create one via API first")
        return 0
    v = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == p.id, ScheduleVersion.is_active.is_(True))
        .first()
    ) or db.query(ScheduleVersion).filter(ScheduleVersion.project_id == p.id).first()
    if not v:
        print("SKIP: no schedule version")
        return 0
    n = resolve_schedule_item_objects(db, p.id, v.id)
    db.commit()
    linked = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == v.id, ScheduleItem.project_object_id.isnot(None))
        .count()
    )
    print(f"OK resolve updated={n} linked={linked} project={p.id} version={v.id}")

    st, ws = req("GET", f"/api/projects/{p.id}/schedules/workspace")
    assert st == 200 and "activities" in ws, ws
    print(f"OK workspace activities={len(ws.get('activities') or [])}")

    st, dev = req("GET", f"/api/projects/{p.id}/deviations")
    assert st == 200 and isinstance(dev, dict) and "items" in dev, dev
    print(f"OK deviations items={len(dev['items'])}")

    payload = {
        "proposed": [
            {
                "id": "smoke-prop-1",
                "predecessor_activity_id": str((ws.get("activities") or [{}])[0].get("id") or ""),
                "successor_activity_id": str((ws.get("activities") or [{}, {}])[1].get("id") or "")
                if len(ws.get("activities") or []) > 1
                else str((ws.get("activities") or [{}])[0].get("id") or ""),
                "relation_type": "FS",
                "lag_days": 0,
                "status": "proposed",
                "source": "rule",
            }
        ]
    }
    # confirm только при двух разных activities
    acts = ws.get("activities") or []
    if len(acts) >= 2 and acts[0]["id"] != acts[1]["id"]:
        payload["proposed"][0]["status"] = "confirmed"
        st, nr = req("PATCH", f"/api/projects/{p.id}/schedules/{v.id}/network-recovery", payload)
        assert st == 200 and nr.get("ok"), nr
        print(f"OK recovery apply applied={nr.get('applied_dependencies')}")
    else:
        print("SKIP recovery apply (need >=2 activities)")

    st, ms = req("POST", "/api/ai/mapping/suggest", {"names": ["Земляные работы котлован"], "catalog": [{"code": "EARTH", "name": "Земляные работы"}]})
    assert st == 200 and "candidates" in ms, ms
    print(f"OK mapping suggest candidates={len(ms['candidates'])} fallback={ms.get('fallback')}")

    st, pf = req("GET", "/api/portfolio")
    assert st == 200
    meta = (pf.get("meta") or {})
    print(f"OK portfolio trend_kind={meta.get('trend_kind')} projects={len(pf.get('projects') or [])}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as e:
        print("FAIL: API not reachable on :8010", e)
        raise SystemExit(1)
    except Exception as e:
        print("FAIL", e)
        raise SystemExit(1)
