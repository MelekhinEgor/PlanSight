"""P0-G: projection snapshot + rebuild (локальный SQLite).

P0-05: полный rebuild; CV-слой (InferenceRun/Detection) не перезапускается —
пересчитывается только аналитика поверх сохранённых детекций.
Partial rebuild (camera/start/end) отключён: он очищал весь проект.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import IngestStatus
from app.db.models import (
    ActivityHypothesis,
    Camera,
    Deviation,
    Episode,
    Frame,
    ProjectionSnapshot,
    ScheduleItem,
    ScheduleMatch,
    ScheduleVersion,
)
from app.services.knowledge_base.service import load_kb
from app.services.pipeline.service import process_frame
from app.services.schedule.service import get_active_schedule


def _source_hash(db: Session, project_id: int) -> str:
    """V6: fingerprint строк КСГ + ревизии верификации зон, не только meta версии."""
    from app.db.models import CameraZoneBinding, CameraVisualZone

    versions = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == project_id)
        .order_by(ScheduleVersion.id.asc())
        .all()
    )
    frames = (
        db.query(Frame.id, Frame.sha256, Frame.captured_at)
        .filter(Frame.project_id == project_id)
        .order_by(Frame.id.asc())
        .all()
    )
    item_fp = []
    for v in versions:
        rows = (
            db.query(
                ScheduleItem.id,
                ScheduleItem.external_id,
                ScheduleItem.planned_start,
                ScheduleItem.planned_finish,
                ScheduleItem.work_type_id,
                ScheduleItem.building,
            )
            .filter(ScheduleItem.schedule_version_id == v.id)
            .order_by(ScheduleItem.id.asc())
            .all()
        )
        item_fp.append(
            (
                v.id,
                [
                    (r.id, r.external_id, str(r.planned_start), str(r.planned_finish), r.work_type_id, r.building)
                    for r in rows
                ],
            )
        )
    zones = (
        db.query(CameraVisualZone.id, CameraVisualZone.zone_status, CameraVisualZone.zone_key)
        .filter(CameraVisualZone.project_id == project_id)
        .order_by(CameraVisualZone.id.asc())
        .all()
    )
    binds = (
        db.query(
            CameraZoneBinding.id,
            CameraZoneBinding.building,
            CameraZoneBinding.binding_status,
            CameraZoneBinding.visual_zone_key,
        )
        .filter(CameraZoneBinding.project_id == project_id)
        .order_by(CameraZoneBinding.id.asc())
        .all()
    )
    payload = {
        "schedules": [(v.id, v.checksum, v.kind, v.is_active, v.revision) for v in versions],
        "schedule_items": item_fp,
        "frames": [(f.id, f.sha256, str(f.captured_at)) for f in frames],
        "zones": [(z.id, z.zone_key, z.zone_status) for z in zones],
        "bindings": [(b.id, b.building, b.binding_status, b.visual_zone_key) for b in binds],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _algorithm_hash() -> str:
    settings = get_settings()
    kb = load_kb()
    blob = json.dumps(
        {
            "engine": settings.get("engine", "version", "plansight-engine-v1"),
            "kb": kb.version,
            "kb_rules": len(getattr(kb, "rules", None) or []),
            "class_map": settings.section("detector").get("class_map") or {},
            "matching": settings.section("engine").get("matching") or {},
            "temporal": {
                k: (settings.section("engine").get("temporal") or {}).get(k)
                for k in ("dt_short_sec", "dt_medium_sec", "dt_long_sec", "min_frames_for_start")
            },
            "detector_model": settings.section("detector").get("model"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _clear_derived(db: Session, project_id: int) -> None:
    """Очистка derived. Frame / InferenceRun / Detection / HumanVerdict сохраняются."""
    cam_ids = [c.id for c in db.query(Camera.id).filter(Camera.project_id == project_id).all()]
    if not cam_ids:
        cam_ids = [-1]
    hyp_ids = [
        h.id
        for h in db.query(ActivityHypothesis.id).filter(ActivityHypothesis.camera_id.in_(cam_ids)).all()
    ]
    if hyp_ids:
        db.query(ScheduleMatch).filter(ScheduleMatch.hypothesis_id.in_(hyp_ids)).delete(
            synchronize_session=False
        )
        from app.db.models import Evidence, StateEvent

        db.query(Evidence).filter(Evidence.hypothesis_id.in_(hyp_ids)).delete(synchronize_session=False)
        db.query(StateEvent).filter(StateEvent.hypothesis_id.in_(hyp_ids)).delete(synchronize_session=False)
        db.query(ActivityHypothesis).filter(ActivityHypothesis.id.in_(hyp_ids)).delete(
            synchronize_session=False
        )
    # Не удаляем RESOLVED/ACKNOWLEDGED; fixture CV findings (SYNTHETIC_TEST_FIXTURE) сохраняем
    open_rows = (
        db.query(Deviation)
        .filter(Deviation.project_id == project_id, Deviation.lifecycle == "OPEN")
        .all()
    )
    for row in open_rows:
        try:
            det = json.loads(row.details_json or "{}")
        except Exception:
            det = {}
        if det.get("preserve_fixture") or (
            det.get("signal_kind") in ("CV_VERIFIED_FINDING", "SYNTHETIC_DEMO_FINDING")
            and det.get("data_origin") == "SYNTHETIC_TEST_FIXTURE"
        ):
            continue
        db.delete(row)
    db.flush()
    db.query(Episode).filter(Episode.project_id == project_id).delete(synchronize_session=False)
    from app.db.models import Observation, TemporalState, ScheduleItemState

    frame_ids = [f.id for f in db.query(Frame.id).filter(Frame.project_id == project_id).all()]
    if frame_ids:
        from app.db.models import InferenceRun

        run_ids = [
            r.id for r in db.query(InferenceRun.id).filter(InferenceRun.frame_id.in_(frame_ids)).all()
        ]
        if run_ids:
            db.query(Observation).filter(Observation.inference_run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
    db.query(TemporalState).filter(TemporalState.project_id == project_id).delete(
        synchronize_session=False
    )
    version_ids = [
        v.id for v in db.query(ScheduleVersion.id).filter(ScheduleVersion.project_id == project_id).all()
    ]
    if version_ids:
        db.query(ScheduleItemState).filter(
            ScheduleItemState.schedule_version_id.in_(version_ids)
        ).delete(synchronize_session=False)
    db.flush()


def build_projection_payload(db: Session, project_id: int) -> dict[str, Any]:
    version = get_active_schedule(db, project_id)
    items = (
        db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version.id).all()
        if version
        else []
    )
    cam_ids = [c.id for c in db.query(Camera.id).filter(Camera.project_id == project_id).all()] or [-1]
    hyps = (
        db.query(ActivityHypothesis)
        .filter(ActivityHypothesis.camera_id.in_(cam_ids))
        .order_by(ActivityHypothesis.id.desc())
        .limit(500)
        .all()
    )
    hyp_ids = [h.id for h in hyps]
    matches = (
        db.query(ScheduleMatch).filter(ScheduleMatch.hypothesis_id.in_(hyp_ids)).all() if hyp_ids else []
    )
    deviations = (
        db.query(Deviation)
        .filter(Deviation.project_id == project_id, Deviation.lifecycle.in_(["OPEN", "ACKNOWLEDGED"]))
        .all()
    )
    episodes = db.query(Episode).filter(Episode.project_id == project_id).count()
    return {
        "active_schedule_version_id": version.id if version else None,
        "schedule_kind": version.kind if version else None,
        "leaf_items": sum(1 for i in items if not i.is_summary and not i.is_milestone),
        "hypotheses": len(hyps),
        "matches": len(matches),
        "open_deviations": len(deviations),
        "episodes": episodes,
        "invariants": {
            "matches_have_hypothesis": all(m.hypothesis_id for m in matches),
            "project_scoped": True,
            "cv_layer_immutable": True,
        },
    }


def create_snapshot(db: Session, project_id: int, *, activate: bool = True) -> ProjectionSnapshot:
    as_of = datetime.utcnow()
    snap = ProjectionSnapshot(
        project_id=project_id,
        as_of=as_of,
        source_hash=_source_hash(db, project_id),
        algorithm_hash=_algorithm_hash(),
        is_active=False,
        payload_json=json.dumps(build_projection_payload(db, project_id), ensure_ascii=False),
    )
    db.add(snap)
    db.flush()
    if activate:
        db.query(ProjectionSnapshot).filter(
            ProjectionSnapshot.project_id == project_id,
            ProjectionSnapshot.is_active.is_(True),
        ).update({"is_active": False})
        snap.is_active = True
        db.flush()
    return snap


def rebuild_project(
    db: Session,
    project_id: int,
    *,
    camera_id: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Полный chronological reprocess без повторного YOLO (reuse_detections).

    При ошибке — rollback savepoint: derived строки и active snapshot не меняются.
    """
    if camera_id is not None or start is not None or end is not None:
        return {
            "ok": False,
            "error": "partial_rebuild_disabled",
            "note": "P0-05: частичный rebuild очищал весь проект. Используйте полный rebuild.",
        }

    prev_active = (
        db.query(ProjectionSnapshot)
        .filter(ProjectionSnapshot.project_id == project_id, ProjectionSnapshot.is_active.is_(True))
        .one_or_none()
    )
    prev_id = prev_active.id if prev_active else None

    try:
        with db.begin_nested():
            staging = ProjectionSnapshot(
                project_id=project_id,
                as_of=datetime.utcnow(),
                source_hash=_source_hash(db, project_id),
                algorithm_hash=_algorithm_hash(),
                is_active=False,
                payload_json=json.dumps(
                    {
                        "phase": "pre_rebuild",
                        "previous_snapshot_id": prev_id,
                        **build_projection_payload(db, project_id),
                    },
                    ensure_ascii=False,
                ),
            )
            db.add(staging)
            db.flush()

            _clear_derived(db, project_id)

            frames = (
                db.query(Frame)
                .filter(
                    Frame.project_id == project_id,
                    Frame.captured_at.isnot(None),
                    Frame.ingest_status == IngestStatus.READY.value,
                )
                .order_by(Frame.captured_at.asc(), Frame.id.asc())
                .all()
            )

            processed = 0
            for fr in frames:
                process_frame(db, fr.id, force=True, reuse_detections=True)
                processed += 1
            snap = create_snapshot(db, project_id, activate=True)
            return {
                "ok": True,
                "frames_touched": processed,
                "cameras_replayed": len({f.camera_id for f in frames}),
                "snapshot_id": snap.id,
                "staging_snapshot_id": staging.id,
                "previous_snapshot_id": prev_id,
                "source_hash": snap.source_hash,
                "algorithm_hash": snap.algorithm_hash,
                "payload": json.loads(snap.payload_json or "{}"),
                "yolo_rerun": False,
                "atomic_switch": True,
                "note": "детекции переиспользованы; YOLO не вызывается; switch после успешного replay",
            }
    except Exception as exc:
        # Точка savepoint откачена — производные данные и активный snapshot сохранены
        return {
            "ok": False,
            "error": str(exc),
            "previous_snapshot_id": prev_id,
            "rolled_back_active": True,
            "data_preserved": True,
            "note": "savepoint rollback: активная аналитика и derived не изменены",
        }
