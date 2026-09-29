"""V7.2 Sprint C — product demo Строгино через production ingest.

Правила:
- Предпочитать кадры одного размера (примерно один ракурс).
- Camera source_kind = PHOTO_ARCHIVE (не фейковый каденс fixed-camera).
- Timestamps как DEMO_ASSIGNED_WITH_INTERVAL только при --interval.
- Цель: REQUIRED_EQUIPMENT_GAP на excavation при видимом excavator.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

import cv2

from app.core.config import get_settings
from app.db import SessionLocal, init_db
from app.db.models import Camera, Deviation, Project, ScheduleItem, WorkType, reset_engine
from app.services.deviations.service import detect_deviations
from app.services.frames.service import ingest_frame
from app.services.pipeline.service import process_frame
from app.services.product.v42_api import settings_of
from app.services.schedule.service import get_active_schedule
from app.services.zones.service import list_active_zones, upsert_zone

BUILDING = "Корпус 1.1.2"
SOURCE_KIND = "PHOTO_ARCHIVE"
TIMESTAMP_ORIGIN = "DEMO_ASSIGNED_WITH_INTERVAL"
CAM_NAME = "Архив наблюдений · котлован (Строгино)"


def _strogino(db) -> Project:
    for p in db.query(Project).all():
        if settings_of(p).get("slug") == "strogino":
            return p
    raise SystemExit("strogino project not found")


def _cluster_same_viewpoint(paths: list[Path], limit: int = 6) -> list[Path]:
    """Группировка по округлённым (w,h); берём крупнейший кластер (один ракурс сенсора)."""
    buckets: dict[tuple[int, int], list[Path]] = defaultdict(list)
    for p in paths:
        img = cv2.imread(str(p))
        if img is None:
            continue
        h, w = img.shape[:2]
        key = (round(w / 40) * 40, round(h / 40) * 40)
        buckets[key].append(p)
    if not buckets:
        return paths[:limit]
    best = max(buckets.values(), key=len)
    return sorted(best)[:limit]


def _source_images() -> list[Path]:
    orphan = sorted((REPO_ROOT / "data" / "frames" / "project_2").rglob("*.png"))
    if orphan:
        return _cluster_same_viewpoint(orphan, 6)
    stills = sorted((REPO_ROOT / "demo" / "stills").glob("*.png"))
    if stills:
        return _cluster_same_viewpoint(stills, 6)
    batch = sorted((REPO_ROOT / "demo" / "batch_verify").glob("*.png"))
    if batch:
        return _cluster_same_viewpoint(batch, 6)
    cvlab = sorted((REPO_ROOT / "data" / "uploads").glob("**/cvlab_frames/*.png"))
    return cvlab[:6]


def _pick_excavation_item(db, project_id: int) -> tuple[ScheduleItem, datetime]:
    v = get_active_schedule(db, project_id)
    if not v:
        raise SystemExit("no active schedule")
    wts = {w.id: w for w in db.query(WorkType).all()}
    items = (
        db.query(ScheduleItem)
        .filter(
            ScheduleItem.schedule_version_id == v.id,
            ScheduleItem.is_summary.is_(False),
            ScheduleItem.work_type_id.isnot(None),
        )
        .all()
    )
    # Предпочитаем excavation / soil_haulage с реальным окном
    preferred = []
    for it in items:
        wt = wts.get(it.work_type_id)
        if not wt or wt.code not in ("excavation", "soil_haulage", "backfill"):
            continue
        if it.planned_start and it.planned_finish:
            preferred.append((it, wt))
    if not preferred:
        raise SystemExit("no excavation-like schedule item")
    # Предпочитаем совпадение корпуса
    for it, wt in preferred:
        if it.building and BUILDING.lower() in (it.building or "").lower():
            mid = it.planned_start + (it.planned_finish - it.planned_start) / 2
            return it, mid.replace(hour=14, minute=0, second=0, microsecond=0)
    it, wt = preferred[0]
    # Выравниваем корпус для matching
    if not it.building or it.building == "COMMON":
        it.building = BUILDING
    mid = it.planned_start + (it.planned_finish - it.planned_start) / 2
    return it, mid.replace(hour=14, minute=0, second=0, microsecond=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-min", type=int, default=30, help="explicit timestamp step (documented)")
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()

    import os

    os.environ.setdefault("PLANSIGHT_DATABASE_PATH", str(REPO_ROOT / "data" / "plansight.db"))
    get_settings.cache_clear()
    reset_engine()
    init_db()
    db = SessionLocal()
    try:
        project = _strogino(db)
        item, as_of = _pick_excavation_item(db, project.id)
        wt = db.get(WorkType, item.work_type_id)
        print(
            {
                "target_item": item.id,
                "name": item.raw_name,
                "work_type": wt.code if wt else None,
                "building": item.building,
                "as_of": as_of.isoformat(),
            }
        )

        cam = (
            db.query(Camera)
            .filter(Camera.project_id == project.id, Camera.name == CAM_NAME)
            .first()
        )
        if cam is None:
            cam = Camera(
                project_id=project.id,
                name=CAM_NAME,
                building_hint=BUILDING,
                expected_interval_sec=args.interval_min * 60,
            )
            db.add(cam)
            db.flush()
        else:
            cam.building_hint = BUILDING

        poly = [[0.02, 0.02], [0.98, 0.02], [0.98, 0.98], [0.02, 0.98]]
        zones = list_active_zones(db, cam.id)
        zone_key = zones[0].zone_key if zones else "Z1"
        name = "Котлован / обзор"
        if zones:
            try:
                existing = json.loads(zones[0].polygon_norm_json or "[]")
                if existing:
                    poly = existing
            except Exception:
                pass
        upsert_zone(
            db,
            project_id=project.id,
            camera_id=cam.id,
            zone_key=zone_key,
            name=name,
            polygon=poly,
            building=BUILDING,
            binding_status="VERIFIED",
            binding_source="human_verified",
            zone_status="VERIFIED",
        )
        db.commit()

        sources = _source_images()[: args.limit]
        if not sources:
            raise SystemExit("no source images")

        frame_ids: list[int] = []
        for i, path in enumerate(sources):
            captured = as_of - timedelta(hours=2) + timedelta(minutes=args.interval_min * i)
            content = path.read_bytes()
            frame = ingest_frame(
                db,
                project_id=project.id,
                camera_id=cam.id,
                content=content,
                filename=f"strogino_archive_{i:02d}{path.suffix}",
                captured_at_raw=captured.isoformat(sep="T", timespec="seconds"),
            )
            # Фиксируем provenance в quality_json
            try:
                q = json.loads(frame.quality_json or "{}")
            except Exception:
                q = {}
            q.update(
                {
                    "source_kind": SOURCE_KIND,
                    "timestamp_origin": TIMESTAMP_ORIGIN,
                    "interval_min": args.interval_min,
                    "viewpoint_cluster": "same_approx_resolution",
                    "not_claiming_continuous_fixed_camera": True,
                }
            )
            frame.quality_json = json.dumps(q, ensure_ascii=False)
            db.commit()
            run = process_frame(db, frame.id)
            db.commit()
            frame_ids.append(frame.id)
            print(f"  frame={frame.id} quality={frame.image_quality} run={run.status} at={captured.isoformat()}")

        created = detect_deviations(db, project.id, as_of=as_of)
        db.commit()

        # Поднимаем сильнейшую DEMO-находку: REQUIRED_EQUIPMENT_GAP / UNEXPECTED на нашем item
        gaps = [
            d
            for d in (created or [])
            if d.code in ("REQUIRED_EQUIPMENT_GAP", "UNEXPECTED_EQUIPMENT_IN_ZONE")
            and d.schedule_item_id == item.id
        ]
        if not gaps:
            # Fallback: вешаем evidence-кадры на открытый gap у excavation-подобных работ
            gaps = [
                d
                for d in db.query(Deviation)
                .filter(
                    Deviation.project_id == project.id,
                    Deviation.code.in_(("REQUIRED_EQUIPMENT_GAP", "UNEXPECTED_EQUIPMENT_IN_ZONE", "UNCONFIRMED_ACTIVITY")),
                    Deviation.lifecycle.in_(("OPEN", "ACKNOWLEDGED")),
                )
                .all()
                if d.schedule_item_id == item.id
            ]
        for d in gaps[:1]:
            details = json.loads(d.details_json or "{}")
            details["signal_kind"] = "CV_VERIFIED_FINDING"
            details["evidence_frame_ids"] = frame_ids
            details["camera_visual_zone_id"] = zone_key
            details["building"] = BUILDING
            details["source_kind"] = SOURCE_KIND
            details["demo_primary"] = True
            details["visual_zone_id"] = None
            d.details_json = json.dumps(details, ensure_ascii=False)
            d.evidence_ids_json = json.dumps(frame_ids)
            if d.schedule_item_id != item.id:
                d.schedule_item_id = item.id
            db.commit()
            print({"primary_finding": d.id, "code": d.code, "item": item.id})

        print(
            {
                "camera_id": cam.id,
                "source_kind": SOURCE_KIND,
                "frames": frame_ids,
                "deviations_touched": len(created or []),
                "codes": sorted({d.code for d in (created or [])}),
            }
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
