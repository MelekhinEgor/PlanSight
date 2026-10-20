from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import cv2
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import IngestStatus, RunStatus, ScoreKind, UiStatus
from app.db.models import (
    ActivityHypothesis,
    Camera,
    Detection,
    Episode,
    Evidence,
    Frame,
    InferenceRun,
    Observation,
    ScheduleMatch,
    StateEvent,
    TemporalState,
    WorkType,
)
from app.services.activity.service import (
    calendar_prior,
    equipment_feature_score,
    infer_multi_label,
    select_work_types,
)
from app.services.cv_adapter.service import draw_overlay, ensure_model_version, get_adapter
from app.services.deviations.service import detect_deviations
from app.services.frames.service import build_equipment_counts, build_equipment_vector, load_frame_image
from app.services.knowledge_base.service import load_kb, sync_kb_to_db
from app.services.matching.service import rank_schedule_items
from app.services.schedule.service import get_active_schedule, list_candidates, list_schedule_items
from app.services.temporal.service import (
    derive_events,
    episode_repeat_weight,
    update_episode,
    update_schedule_item_state,
    update_state_filter,
)
from app.services.zones.service import assign_zone, building_for_zone, list_active_zones
from app.services.zones.auto import auto_ensure_zones


def _run_zone_analytics(
    db: Session,
    *,
    frame,
    run: InferenceRun,
    kb,
    camera: Camera | None,
    zone_id: int | None,
    zone_key: str,
    building: str | None,
    zone_detections: list,
    equipment_vector: dict[str, float],
    observability: float,
    overlay_path: Path,
    schedule_items: list,
    wt_by_id: dict,
    wt_by_code: dict,
    schedule_codes: list[str],
) -> None:
    """Аналитика для одной визуальной зоны (или WHOLE_FRAME)."""
    prev_q = db.query(Episode).filter(
        Episode.project_id == frame.project_id,
        Episode.camera_id == frame.camera_id,
    )
    if zone_id is None:
        prev_q = prev_q.filter(Episode.visual_zone_id.is_(None))
    else:
        prev_q = prev_q.filter(Episode.visual_zone_id == zone_id)
    prev_episode = prev_q.order_by(Episode.end_at.desc()).first()
    prev_comp = set(json.loads(prev_episode.composition_json or "{}").keys()) if prev_episode else set()
    episode = update_episode(
        db,
        project_id=frame.project_id,
        camera_id=frame.camera_id,
        captured_at=frame.captured_at,
        equipment_vector=equipment_vector,
        expected_interval_sec=camera.expected_interval_sec if camera else 300,
        visual_zone_id=zone_id,
    )
    new_comp = set(json.loads(episode.composition_json or "{}").keys())
    process_changed = bool(prev_comp and new_comp and prev_comp != new_comp and episode.frame_count == 1)
    if prev_comp and not new_comp and episode.frame_count == 1:
        process_changed = True
    repeat_w = episode_repeat_weight(episode)

    candidate_types = select_work_types(equipment_vector, schedule_codes, kb)
    match_cfg = get_settings().section("engine").get("matching") or {}
    before_days = int(match_cfg.get("before_days", 7))
    after_days = int(match_cfg.get("after_days", 7))
    cal_eps = float(get_settings().section("engine").get("calendar", {}).get("epsilon", 0.05))
    # Типы работ, у которых есть строки КСГ рядом с датой кадра — приоритет сопоставления
    nearby_type_ids: set[int] = set()
    for _code, _wt in wt_by_code.items():
        near = list_candidates(
            db,
            frame.project_id,
            _wt.id,
            frame.captured_at,
            building=building,
            before_days=before_days,
            after_days=after_days,
        )
        if near:
            nearby_type_ids.add(_wt.id)
    nearby_codes = {
        code for code, wt in wt_by_code.items() if wt.id in nearby_type_ids
    }
    # Если рядом есть подходящие типы из equipment — не раздуваем гипотезы по кровле/фасаду 2028
    if nearby_codes:
        preferred = [c for c in candidate_types if c in nearby_codes]
        if preferred:
            candidate_types = preferred

    for work_code in candidate_types:
        wt = wt_by_code.get(work_code)
        if wt is None:
            continue
        related = [i for i in schedule_items if i.work_type_id == wt.id]
        if building:
            related_b = [i for i in related if i.building and i.building.lower() == building.lower()]
            if related_b:
                related = related_b
        # Календарный prior только по работам в окне даты кадра — не по далёкому будущему
        win_lo = frame.captured_at - timedelta(days=before_days)
        win_hi = frame.captured_at + timedelta(days=after_days)
        related_near = [
            i
            for i in related
            if i.planned_start
            and i.planned_finish
            and not (i.planned_finish < win_lo or i.planned_start > win_hi)
        ]
        if related_near:
            prior = max(
                calendar_prior(i.planned_start, i.planned_finish, frame.captured_at)
                for i in related_near
            )
        else:
            prior = cal_eps
            # Без строк КСГ рядом — гипотеза только при сильном equipment (UNMATCHED), иначе шум
            eq_keep = float(
                get_settings().section("engine").get("activity", {}).get("min_score_keep", 0.12)
            )
            strong = float(
                get_settings().section("engine").get("activity", {}).get("far_type_min_equipment", 0.35)
            )
            eq = float(equipment_feature_score(equipment_vector, work_code, kb=kb)["equipment_score"])
            if eq < max(strong, eq_keep + 0.15):
                continue

        prev_row = (
            db.query(TemporalState)
            .filter(
                TemporalState.project_id == frame.project_id,
                TemporalState.camera_id == frame.camera_id,
                TemporalState.work_type_id == wt.id,
                TemporalState.visual_zone_key == zone_key,
            )
            .one_or_none()
        )
        prev_dist = json.loads(prev_row.distribution_json) if prev_row else None
        temporal_support = min(1.0, float(prev_row.frame_support or 0) / 5.0) if prev_row else 0.0

        inferred = infer_multi_label(
            work_type=work_code,
            equipment_vector=equipment_vector,
            observability=observability,
            calendar_prior_value=prior,
            episode_repeat_weight=repeat_w,
            temporal_support=temporal_support,
            kb=kb,
        )
        post_dist = update_state_filter(
            db,
            project_id=frame.project_id,
            camera_id=frame.camera_id,
            work_type_id=wt.id,
            at=frame.captured_at,
            activity_score=float(inferred["activity_score"]),
            observability=observability,
            visual_zone_key=zone_key,
        )
        hyp = ActivityHypothesis(
            inference_run_id=run.id,
            work_type_id=wt.id,
            camera_id=frame.camera_id,
            visual_zone_id=zone_id,
            episode_id=episode.id,
            interval_start=frame.captured_at,
            interval_end=frame.captured_at,
            activity_score=float(inferred["activity_score"]),
            score_kind=ScoreKind.UNCALIBRATED_SCORE.value,
            state_distribution_json=json.dumps(post_dist),
            ui_status=UiStatus.UNKNOWN.value,
            explanation_json=json.dumps(
                {
                    "band": inferred["band"],
                    "calendar_prior": inferred["calendar_prior"],
                    "feature_breakdown": inferred.get("feature_breakdown"),
                    "engine_mode": inferred.get("engine_mode"),
                    "episode_id": episode.id,
                    "zone_key": zone_key,
                    "zone_id": zone_id,
                    "building": building,
                    "process_changed": process_changed,
                    "overlay_path": str(overlay_path),
                    "note": inferred.get("note")
                    or "предварительный балл модели (не калиброванная вероятность)",
                },
                ensure_ascii=False,
            ),
        )
        db.add(hyp)
        db.flush()

        matches = rank_schedule_items(
            db,
            project_id=frame.project_id,
            work_type_id=wt.id,
            camera_id=frame.camera_id,
            at=frame.captured_at,
            building_override=building,
            visual_zone_key=zone_key,
        )
        for m in matches:
            db.add(
                ScheduleMatch(
                    hypothesis_id=hyp.id,
                    schedule_item_id=m["schedule_item_id"],
                    score=float(m["prob"]),
                    score_kind=ScoreKind.UNCALIBRATED_SCORE.value,
                    rank=int(m["rank"]),
                    reason_codes_json=json.dumps(m["reason_codes"], ensure_ascii=False),
                    is_unmatched=bool(m["is_unmatched"]),
                )
            )

        db.add(
            Evidence(
                hypothesis_id=hyp.id,
                frame_id=frame.id,
                kind="frame",
                weight=1.0,
                payload_json=json.dumps({"overlay_path": str(overlay_path), "zone_key": zone_key}),
            )
        )
        relevant_eq = {r.equipment_type for r in kb.rules_for_work(work_code)}
        for det in zone_detections:
            if relevant_eq and det.equipment_code not in relevant_eq:
                continue
            db.add(
                Evidence(
                    hypothesis_id=hyp.id,
                    frame_id=frame.id,
                    detection_id=det.id,
                    kind="detection",
                    weight=float(det.confidence),
                    payload_json=json.dumps(
                        {
                            "equipment": det.equipment_code,
                            "confidence": det.confidence,
                            "bbox_norm": json.loads(det.bbox_norm_json),
                            "zone_id": det.zone_id,
                        }
                    ),
                )
            )

        ts_row = (
            db.query(TemporalState)
            .filter(
                TemporalState.project_id == frame.project_id,
                TemporalState.camera_id == frame.camera_id,
                TemporalState.work_type_id == wt.id,
                TemporalState.visual_zone_key == zone_key,
            )
            .one()
        )
        events = derive_events(
            prev_dist=prev_dist,
            post_dist=post_dist,
            activity_score=float(inferred["activity_score"]),
            frame_support=int(ts_row.frame_support or 1),
            process_changed=process_changed,
        )
        top_match = next(
            (
                m
                for m in matches
                if m.get("schedule_item_id")
                and not m.get("is_unmatched")
                and not m.get("is_other")
                and not m.get("assignment_blocked")
                and str(m.get("assignment_status") or "").upper() == "ACCEPTED"
            ),
            None,
        )
        active_threshold = float(
            (get_settings().section("engine").get("activity") or {}).get("active_threshold", 0.45)
        )
        work_obs = str((inferred.get("feature_breakdown") or {}).get("work_observability") or "DIRECT")
        has_visual = bool(inferred.get("hypothesis_allowed", True))
        can_mutate = (
            top_match is not None
            and float(inferred.get("activity_score") or 0) >= active_threshold
            and has_visual
            and work_obs != "NOT_OBSERVABLE"
            and run.schedule_version_id
        )
        if can_mutate:
            update_schedule_item_state(
                db,
                schedule_version_id=int(run.schedule_version_id),
                schedule_item_id=int(top_match["schedule_item_id"]),
                at=frame.captured_at,
                observed_activity=float(inferred["activity_score"]),
                match_score=float(top_match.get("match_score") or top_match.get("prob") or 0),
                ui_status="MODEL_ESTIMATE",
            )
        for ev in events:
            db.add(
                StateEvent(
                    hypothesis_id=hyp.id,
                    schedule_item_id=(top_match or {}).get("schedule_item_id"),
                    event_type=ev["event_type"],
                    event_at=frame.captured_at,
                    status=ev.get("status", "model_estimate"),
                    source="temporal_filter",
                    details_json=json.dumps({**ev, "zone_key": zone_key}, ensure_ascii=False),
                )
            )
        if any("AMBIGUOUS_LOCATION" in (m.get("reason_codes") or []) for m in matches):
            db.add(
                StateEvent(
                    hypothesis_id=hyp.id,
                    schedule_item_id=None,
                    event_type="AMBIGUOUS_MATCH",
                    event_at=frame.captured_at,
                    status="model_estimate",
                    source="matching",
                    details_json=json.dumps(
                        {"note": "assignment_blocked", "zone_key": zone_key},
                        ensure_ascii=False,
                    ),
                )
            )


def _config_hash(kb_version: str, model_sha: str, schedule_version_id: int | None) -> str:
    from app.core.config import file_sha256

    settings = get_settings()
    engine = settings.get("engine", "version", "plansight-engine-v1")
    class_map = settings.section("detector").get("class_map") or {}
    try:
        kb_sha = file_sha256(settings.kb_path())[:16]
    except OSError:
        kb_sha = kb_version
    payload = {
        "engine": engine,
        "kb": kb_version,
        "kb_sha": kb_sha,
        "model": model_sha,
        "class_map_sha": hashlib.sha256(
            json.dumps(class_map, sort_keys=True).encode()
        ).hexdigest()[:16],
        "mapping_version": settings.get("detector", "mapping_version"),
        "schedule_version_id": schedule_version_id,
        "thresholds": settings.section("engine"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def process_frame(
    db: Session,
    frame_id: int,
    force: bool = False,
    *,
    reuse_detections: bool = False,
) -> InferenceRun:
    """Сквозной поток: фото → CV → observation → hypotheses → match → deviations.

    reuse_detections=True (rebuild): не вызывать YOLO, взять bbox из последнего COMPLETED run.
    """
    frame = db.get(Frame, frame_id)
    if frame is None:
        raise ValueError(f"frame {frame_id} not found")

    if frame.ingest_status == IngestStatus.NEEDS_TIMESTAMP.value or frame.captured_at is None:
        raise ValueError("frame captured_at is missing or ambiguous — will not use upload time")

    sync_kb_to_db(db)
    kb = load_kb()
    model = ensure_model_version(db)
    schedule_version = get_active_schedule(db, frame.project_id)
    engine_version = str(get_settings().get("engine", "version", "plansight-engine-v1"))
    cfg_hash = _config_hash(kb.version, model.weights_sha256, schedule_version.id if schedule_version else None)

    existing = (
        db.query(InferenceRun)
        .filter(
            InferenceRun.frame_id == frame.id,
            InferenceRun.config_hash == cfg_hash,
            InferenceRun.status.in_([RunStatus.COMPLETED.value, RunStatus.SKIPPED_IDEMPOTENT.value]),
        )
        .order_by(InferenceRun.id.desc())
        .first()
    )
    if existing and not force:
        return existing

    # CV cache: COMPLETED run (включая zero detections) — не вызывать YOLO повторно
    cached_dets: list[Detection] = []
    cache_hit = False
    if reuse_detections:
        prev = (
            db.query(InferenceRun)
            .filter(
                InferenceRun.frame_id == frame.id,
                InferenceRun.status == RunStatus.COMPLETED.value,
            )
            .order_by(InferenceRun.id.desc())
            .first()
        )
        if prev:
            cached_dets = (
                db.query(Detection).filter(Detection.inference_run_id == prev.id).all()
            )
            cache_hit = True

    run = InferenceRun(
        frame_id=frame.id,
        model_version_id=model.id,
        schedule_version_id=schedule_version.id if schedule_version else None,
        kb_version=kb.version,
        engine_version=engine_version,
        config_hash=cfg_hash,
        status=RunStatus.RUNNING.value,
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()

    try:
        image = load_frame_image(frame)
        if image is None:
            raise ValueError(f"cannot read frame file: {frame.file_path}")

        quality = json.loads(frame.quality_json or "{}")
        observability = float(quality.get("observability", 1.0))
        if frame.image_quality == "UNUSABLE" or observability <= 0:
            db.add(
                Observation(
                    inference_run_id=run.id,
                    quality_json=frame.quality_json,
                    equipment_vector_json="{}",
                    observability=0.0,
                )
            )
            run.status = RunStatus.COMPLETED.value
            run.finished_at = datetime.utcnow()
            db.flush()
            return run

        from app.services.cv_adapter.service import DetectionResult

        if cache_hit:
            detections = []
            for d in cached_dets:
                bbox = json.loads(d.bbox_norm_json or "{}")
                x1, y1 = float(bbox.get("x1", 0)), float(bbox.get("y1", 0))
                x2, y2 = float(bbox.get("x2", 0)), float(bbox.get("y2", 0))
                detections.append(
                    DetectionResult(
                        class_name=d.equipment_code,
                        raw_class_name=d.raw_class_name or d.equipment_code,
                        confidence=float(d.confidence),
                        bbox_xyxy=(x1, y1, x2, y2),
                        bbox_norm=(x1, y1, x2, y2),
                    )
                )
            run.error = "cv_reused:zero_detections" if not detections else "cv_reused:no_yolo"
        elif reuse_detections:
            run.status = RunStatus.FAILED.value
            run.error = "NEEDS_CV_REPROCESS: no cached COMPLETED inference run"
            run.finished_at = datetime.utcnow()
            db.flush()
            raise ValueError(run.error)
        else:
            adapter = get_adapter()
            detections = adapter.infer(image)
            warnings = adapter.validate_output(detections)
            if warnings:
                run.error = "validation_warnings: " + "; ".join(warnings)

        zones = list_active_zones(db, frame.camera_id)
        auto_info = auto_ensure_zones(
            db,
            project_id=frame.project_id,
            camera_id=frame.camera_id,
            refine=True,
            as_of=frame.captured_at,
        )
        zones = list_active_zones(db, frame.camera_id)
        det_rows = []
        zone_buckets: dict[str, list] = {}
        ambiguous_dets = 0
        for d in detections:
            bbox = {
                "x1": d.bbox_norm[0],
                "y1": d.bbox_norm[1],
                "x2": d.bbox_norm[2],
                "y2": d.bbox_norm[3],
            }
            zone, amb = assign_zone(zones, bbox)
            if amb:
                ambiguous_dets += 1
            row = Detection(
                inference_run_id=run.id,
                equipment_code=d.class_name,
                raw_class_name=d.raw_class_name,
                confidence=d.confidence,
                bbox_norm_json=json.dumps(bbox),
                zone_id=zone.id if zone else None,
                zone_ambiguous=bool(amb),
            )
            db.add(row)
            db.flush()
            det_rows.append(row)
            key = zone.zone_key if zone else ("AMBIGUOUS" if amb else "WHOLE_FRAME")
            zone_buckets.setdefault(key, []).append(row)

        overlay = draw_overlay(image, detections)
        overlay_dir = get_settings().overlays_dir() / f"project_{frame.project_id}"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        overlay_path = overlay_dir / f"frame_{frame.id}_run_{run.id}.jpg"
        cv2.imwrite(str(overlay_path), overlay)

        equipment_vector = build_equipment_vector(detections)
        equipment_counts = build_equipment_counts(detections)
        camera = db.get(Camera, frame.camera_id)

        zone_summary: dict[str, dict[str, float]] = {}
        for k, rows in zone_buckets.items():
            vec: dict[str, float] = {}
            for r in rows:
                code = r.equipment_code
                if str(code).startswith("ppe_") or code in ("person", "safety_cone"):
                    continue
                vec[code] = max(vec.get(code, 0.0), float(r.confidence))
            zone_summary[k] = vec

        obs = Observation(
            inference_run_id=run.id,
            quality_json=json.dumps(
                {
                    **(json.loads(frame.quality_json or "{}") if frame.quality_json else {}),
                    "equipment_counts": equipment_counts,
                    "zones": zone_summary,
                    "ambiguous_detections": ambiguous_dets,
                    "active_zones": [z.zone_key for z in zones],
                    "auto_zones": auto_info,
                },
                ensure_ascii=False,
            ),
            equipment_vector_json=json.dumps(equipment_vector, ensure_ascii=False),
            observability=observability,
        )
        db.add(obs)
        db.flush()

        schedule_items = list_schedule_items(db, frame.project_id)
        wt_by_id = {w.id: w for w in db.query(WorkType).all()}
        wt_by_code = {w.code: w for w in wt_by_id.values()}
        schedule_codes = []
        for item in schedule_items:
            if item.work_type_id and item.work_type_id in wt_by_id:
                schedule_codes.append(wt_by_id[item.work_type_id].code)

        if zones:
            for z in zones:
                rows = zone_buckets.get(z.zone_key, [])
                vec = zone_summary.get(z.zone_key, {})
                bld = building_for_zone(db, frame.camera_id, z)
                _run_zone_analytics(
                    db,
                    frame=frame,
                    run=run,
                    kb=kb,
                    camera=camera,
                    zone_id=z.id,
                    zone_key=z.zone_key,
                    building=bld,
                    zone_detections=rows,
                    equipment_vector=vec,
                    observability=observability,
                    overlay_path=overlay_path,
                    schedule_items=schedule_items,
                    wt_by_id=wt_by_id,
                    wt_by_code=wt_by_code,
                    schedule_codes=schedule_codes,
                )
        else:
            _run_zone_analytics(
                db,
                frame=frame,
                run=run,
                kb=kb,
                camera=camera,
                zone_id=None,
                zone_key="WHOLE_FRAME",
                building=camera.building_hint if camera else None,
                zone_detections=det_rows,
                equipment_vector=equipment_vector,
                observability=observability,
                overlay_path=overlay_path,
                schedule_items=schedule_items,
                wt_by_id=wt_by_id,
                wt_by_code=wt_by_code,
                schedule_codes=schedule_codes,
            )

        detect_deviations(db, frame.project_id, as_of=frame.captured_at)
        run.status = RunStatus.COMPLETED.value
        run.finished_at = datetime.utcnow()
        db.flush()
        return run
    except Exception as exc:
        run.status = RunStatus.FAILED.value
        run.error = str(exc)
        run.finished_at = datetime.utcnow()
        db.flush()
        raise


def replay_time_range(
    db: Session,
    project_id: int,
    camera_id: int,
    start: datetime,
    end: datetime,
) -> list[InferenceRun]:
    """Переобработать кадры в порядке captured_at при поздних метках времени."""
    frames = (
        db.query(Frame)
        .filter(
            Frame.project_id == project_id,
            Frame.camera_id == camera_id,
            Frame.captured_at >= start,
            Frame.captured_at <= end,
            Frame.ingest_status == IngestStatus.READY.value,
        )
        .order_by(Frame.captured_at.asc())
        .all()
    )
    runs = []
    for fr in frames:
        runs.append(process_frame(db, fr.id, force=True))
    return runs
