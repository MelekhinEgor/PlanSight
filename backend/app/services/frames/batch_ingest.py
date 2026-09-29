"""Пакетный ingest наблюдений: фото / ZIP / video → тот же pipeline кадров."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
from sqlalchemy.orm import Session

from app.db.models import Camera
from app.services.frames.service import ingest_frame, parse_captured_at
from app.services.pipeline.service import process_frame
from app.services.zones.auto import auto_ensure_zones


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def ensure_camera(
    db: Session,
    *,
    project_id: int,
    camera_id: int | None,
    camera_name: str | None,
    building_hint: str | None,
) -> Camera:
    if camera_id is not None:
        cam = db.get(Camera, camera_id)
        if cam is None or cam.project_id != project_id:
            raise ValueError("invalid camera_id")
        if building_hint and not cam.building_hint:
            cam.building_hint = building_hint
        return cam
    name = (camera_name or "").strip() or "Камера"
    cam = Camera(
        project_id=project_id,
        name=name,
        building_hint=building_hint,
        expected_interval_sec=300,
    )
    db.add(cam)
    db.flush()
    auto_ensure_zones(db, project_id=project_id, camera_id=cam.id)
    return cam


def _decode_images_from_zip(content: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = sorted(n for n in zf.namelist() if not n.endswith("/") and not Path(n).name.startswith("."))
        for name in names:
            if Path(name).suffix.lower() not in IMAGE_EXTS:
                continue
            out.append((Path(name).name, zf.read(name)))
    return out


def _extract_video_frames(
    content: bytes,
    *,
    start_at: datetime,
    interval_sec: float,
    max_frames: int = 40,
) -> list[tuple[str, bytes, datetime]]:
    tmp = Path("_tmp_obs_video.mp4")
    # Эквивалент NamedTemporaryFile: пишем в память через буфер
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
        tf.write(content)
        path = Path(tf.name)
    try:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError("cannot open video")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(fps * max(1.0, interval_sec))))
        out: list[tuple[str, bytes, datetime]] = []
        idx = 0
        frame_i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_i % step == 0:
                ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                if ok_enc:
                    ts = start_at + timedelta(seconds=idx * interval_sec)
                    out.append((f"video_frame_{idx:04d}.jpg", buf.tobytes(), ts))
                    idx += 1
                    if idx >= max_frames:
                        break
            frame_i += 1
            if total and frame_i > total + 5:
                break
        cap.release()
        if not out:
            raise ValueError("no frames extracted from video")
        return out
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _parse_ts_from_name(name: str) -> datetime | None:
    """Частые шаблоны даты: 2026-09-17T12-00-00, 20260917_120000, 2026-09-17_12:00:00."""
    import re

    stem = Path(name).stem
    patterns = [
        r"(20\d{2}-\d{2}-\d{2}[T_\s]\d{2}[-:]\d{2}[-:]\d{2})",
        r"(20\d{2}\d{2}\d{2}[_T]\d{6})",
        r"(20\d{2}-\d{2}-\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, stem)
        if not m:
            continue
        raw = m.group(1).replace("_", "T").replace("-", ":", 2) if False else m.group(1)
        raw = m.group(1)
        raw2 = raw.replace("_", "T")
        # Нормализация 20260917_120000
        if re.fullmatch(r"20\d{12}", raw.replace("_", "").replace("T", "")):
            digits = raw.replace("_", "").replace("T", "")
            raw2 = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}T{digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
        else:
            raw2 = raw.replace("_", "T")
            # 2026-09-17T12-00-00 → двоеточия во времени
            if "T" in raw2 and raw2.count("-") >= 4:
                date, time = raw2.split("T", 1)
                raw2 = f"{date}T{time.replace('-', ':')}"
        try:
            return datetime.fromisoformat(raw2)
        except ValueError:
            continue
    return None


def expand_upload(
    *,
    filename: str,
    content: bytes,
    captured_at: datetime,
    video_interval_sec: float = 30.0,
    zip_mode: str = "manifest_or_name",
    zip_interval_sec: float | None = None,
) -> list[tuple[str, bytes, datetime | None]]:
    """Вернуть (name, bytes, captured_at|None). None → NEEDS_TIMESTAMP при ingest."""
    ext = Path(filename or "frame.jpg").suffix.lower()
    if ext == ".zip":
        images = _decode_images_from_zip(content)
        if not images:
            raise ValueError("ZIP не содержит JPG/PNG")
        # Опциональный manifest.json внутри zip
        manifest_map: dict[str, str] = {}
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for cand in ("manifest.json", "manifest.csv", "timestamps.json"):
                    if cand in zf.namelist():
                        raw = zf.read(cand).decode("utf-8", errors="ignore")
                        if cand.endswith(".json"):
                            data = json.loads(raw)
                            if isinstance(data, dict):
                                manifest_map = {str(k): str(v) for k, v in data.items()}
                            elif isinstance(data, list):
                                for row in data:
                                    if isinstance(row, dict) and row.get("file"):
                                        manifest_map[str(row["file"])] = str(row.get("captured_at") or "")
                        break
        except Exception:
            manifest_map = {}
        out: list[tuple[str, bytes, datetime | None]] = []
        for i, (name, blob) in enumerate(images):
            ts: datetime | None = None
            if name in manifest_map and manifest_map[name]:
                try:
                    ts = datetime.fromisoformat(manifest_map[name].replace("Z", ""))
                except ValueError:
                    ts = None
            if ts is None:
                ts = _parse_ts_from_name(name)
            if ts is None and zip_interval_sec is not None and zip_mode == "start_interval":
                ts = captured_at + timedelta(seconds=float(zip_interval_sec) * i)
            out.append((name, blob, ts))
        return out
    if ext in VIDEO_EXTS:
        return [
            (n, b, t)
            for n, b, t in _extract_video_frames(
                content, start_at=captured_at, interval_sec=video_interval_sec
            )
        ]
    if ext in IMAGE_EXTS or not ext:
        return [(filename or "frame.jpg", content, captured_at)]
    raise ValueError(f"unsupported file type: {ext or filename}")


def ingest_observation_batch(
    db: Session,
    *,
    project_id: int,
    camera: Camera,
    items: list[tuple[str, bytes, datetime | None]],
    process: bool = True,
    run_deviations: bool = True,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    frame_ids: list[int] = []
    for name, blob, ts in items:
        frame = ingest_frame(
            db,
            project_id=project_id,
            camera_id=camera.id,
            content=blob,
            filename=name,
            captured_at_raw=ts.isoformat(sep="T", timespec="seconds") if ts else None,
        )
        db.flush()
        row: dict[str, Any] = {
            "frame_id": frame.id,
            "filename": name,
            "captured_at": frame.captured_at.isoformat() if frame.captured_at else None,
            "ingest_status": frame.ingest_status,
            "image_quality": frame.image_quality,
        }
        if process and frame.ingest_status != "NEEDS_TIMESTAMP":
            run = process_frame(db, frame.id)
            db.flush()
            row["inference_run_id"] = run.id
            row["run_status"] = run.status
        results.append(row)
        if frame.ingest_status != "NEEDS_TIMESTAMP":
            frame_ids.append(frame.id)

    deviations_created = 0
    if run_deviations and frame_ids:
        from app.services.deviations.service import detect_deviations

        times = [parse_captured_at(r["captured_at"]) for r in results if r.get("captured_at")]
        times = [t for t in times if t]
        end = as_of or (max(times) if times else datetime.utcnow())
        created = detect_deviations(db, project_id, as_of=end)
        deviations_created = len(created or [])

    return {
        "camera_id": camera.id,
        "camera_name": camera.name,
        "frames": results,
        "frame_ids": frame_ids,
        "frame_count": len(results),
        "processed_count": len(frame_ids),
        "needs_timestamp_count": sum(1 for r in results if r.get("ingest_status") == "NEEDS_TIMESTAMP"),
        "deviations_touched": deviations_created,
    }
