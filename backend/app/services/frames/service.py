from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from dateutil import parser as dtparser
from sqlalchemy.orm import Session

from app.core.config import bytes_sha256, get_settings
from app.core.enums import FrameQualityStatus, IngestStatus
from app.db.models import Frame


@dataclass(frozen=True)
class QualityResult:
    status: str
    reasons: tuple[str, ...]
    blur: float
    brightness: float
    contrast: float
    observability: float


def parse_captured_at(raw: str | None, *, timezone: str | None = None) -> datetime | None:
    """Разобрать время съёмки → naive UTC для SQLite.

    Если задан ``timezone`` и ``raw`` naive — интерпретируем wall-clock в этой зоне,
    затем конвертируем в UTC. Aware datetime всегда приводим к UTC.
    """
    if raw is None or not str(raw).strip():
        return None
    try:
        dt = dtparser.isoparse(str(raw).strip())
    except (ValueError, TypeError):
        try:
            dt = dtparser.parse(str(raw).strip())
        except (ValueError, TypeError):
            return None
    from datetime import timezone as dt_tz
    from zoneinfo import ZoneInfo

    if dt.tzinfo is not None:
        return dt.astimezone(dt_tz.utc).replace(tzinfo=None)
    tz_name = (timezone or "").strip() or None
    if tz_name:
        try:
            local = dt.replace(tzinfo=ZoneInfo(tz_name))
            return local.astimezone(dt_tz.utc).replace(tzinfo=None)
        except Exception:
            pass
    # Дата/время без tz (naive): считаем как UTC wall-clock (legacy)
    return dt.replace(tzinfo=None)


def estimate_quality(image_bgr: np.ndarray | None) -> QualityResult:
    cfg = get_settings().section("engine").get("quality") or {}
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return QualityResult(FrameQualityStatus.UNUSABLE.value, ("DECODE_FAIL",), 0, 0, 0, 0.0)

    h, w = image_bgr.shape[:2]
    reasons: list[str] = []
    if min(h, w) < 64:
        reasons.append("RESOLUTION_LOW")

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if len(image_bgr.shape) == 3 else image_bgr
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    if blur < float(cfg.get("blur_min", 18)):
        reasons.append("BLUR")
    if brightness < float(cfg.get("brightness_min", 18)):
        reasons.append("TOO_DARK")
    if brightness > float(cfg.get("brightness_max", 245)):
        reasons.append("OVEREXPOSED")
    if contrast < float(cfg.get("contrast_min", 5)):
        reasons.append("BLANK_OR_FLAT")

    if contrast < 2.5 and blur < 8:
        status = FrameQualityStatus.UNUSABLE.value
        obs = float(cfg.get("observability_unusable", 0.0))
    elif blur < 6 or brightness < 8:
        status = FrameQualityStatus.UNUSABLE.value
        obs = float(cfg.get("observability_unusable", 0.0))
    elif reasons:
        status = FrameQualityStatus.DEGRADED.value
        obs = float(cfg.get("observability_degraded", 0.55))
    else:
        status = FrameQualityStatus.VALID.value
        obs = float(cfg.get("observability_full", 1.0))

    return QualityResult(status, tuple(reasons), blur, brightness, contrast, obs)


def ingest_frame(
    db: Session,
    *,
    project_id: int,
    camera_id: int,
    content: bytes,
    filename: str,
    captured_at_raw: str | None,
) -> Frame:
    captured_at = parse_captured_at(captured_at_raw)
    sha = bytes_sha256(content)

    existing = (
        db.query(Frame)
        .filter(
            Frame.project_id == project_id,
            Frame.camera_id == camera_id,
            Frame.sha256 == sha,
            Frame.captured_at == captured_at,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing

    frames_dir = get_settings().frames_dir() / f"project_{project_id}" / f"camera_{camera_id}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "frame.jpg").suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png"}:
        ext = ".jpg"
    dest = frames_dir / f"{sha[:16]}{ext}"
    if not dest.exists():
        dest.write_bytes(content)

    # Портативный ключ хранения относительно data_dir (например frames/project_2/camera_4/<sha>.jpg)
    try:
        storage_key = str(dest.resolve().relative_to(get_settings().data_dir().resolve())).replace("\\", "/")
    except Exception:
        try:
            from app.core.paths import REPO_ROOT

            storage_key = str(dest.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
            if storage_key.startswith("data/"):
                storage_key = storage_key[5:]
        except Exception:
            storage_key = str(dest)

    arr = np.frombuffer(content, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    quality = estimate_quality(image)

    if captured_at is None:
        status = IngestStatus.NEEDS_TIMESTAMP.value
    elif quality.status == FrameQualityStatus.UNUSABLE.value:
        status = IngestStatus.READY.value  # still stored; pipeline may skip analysis
    else:
        status = IngestStatus.READY.value

    frame = Frame(
        project_id=project_id,
        camera_id=camera_id,
        captured_at=captured_at,
        file_path=storage_key,
        sha256=sha,
        ingest_status=status,
        image_quality=quality.status,
        quality_json=json.dumps(asdict(quality), ensure_ascii=False),
    )
    db.add(frame)
    db.flush()
    return frame


def resolve_frame_path(file_path: str | None) -> Path | None:
    """Разрешить абсолютный или repo-relative путь кадра (ZIP / Docker)."""
    if not file_path:
        return None
    raw = Path(file_path)
    if raw.is_file():
        return raw
    settings = get_settings()
    candidates: list[Path] = []
    from app.core.paths import REPO_ROOT

    root = REPO_ROOT.resolve()
    norm = file_path.replace("\\", "/")
    # Нормализация устаревших ключей вида backend/frames/...
    if norm.startswith("backend/frames/"):
        norm = norm[len("backend/") :]
    if norm.startswith("data/frames/"):
        norm = norm[len("data/") :]
    candidates.append(root / norm)
    candidates.append(settings.data_dir() / norm)
    candidates.append(root / "data" / norm)
    if norm.startswith("frames/"):
        candidates.append(settings.frames_dir().parent / norm)
        candidates.append(settings.data_dir() / norm)
        candidates.append(settings.frames_dir() / norm[len("frames/") :])
    elif "frames/" in norm:
        tail = norm[norm.index("frames/") :]
        candidates.append(settings.data_dir() / tail)
        candidates.append(root / "data" / tail)
    try:
        uploads = settings.uploads_dir() if hasattr(settings, "uploads_dir") else None
    except Exception:
        uploads = None
    if uploads:
        candidates.append(Path(uploads) / Path(file_path).name)
    if "data/uploads/" in norm:
        candidates.append(root / norm[norm.index("data/uploads/") :])
    if "uploads/" in norm:
        candidates.append(root / "data" / norm[norm.index("uploads/") :])
    for c in candidates:
        if c.is_file():
            return c
    return raw if raw.exists() else None


def load_frame_image(frame: Frame) -> np.ndarray | None:
    path = resolve_frame_path(frame.file_path)
    if path is None or not path.exists():
        return None
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def build_equipment_vector(detections: list) -> dict[str, float]:
    """Максимальная confidence по классу (для эвристики совместимости)."""
    vector: dict[str, float] = {}
    for d in detections:
        code = d.class_name if hasattr(d, "class_name") else d.get("equipment_code")
        conf = d.confidence if hasattr(d, "confidence") else float(d.get("confidence", 0))
        if not code:
            continue
        # Классы PPE / person — не производственная техника
        if str(code).startswith("ppe_") or code in ("person", "safety_cone"):
            continue
        vector[code] = max(vector.get(code, 0.0), float(conf))
    return vector


def build_equipment_counts(detections: list) -> dict[str, dict]:
    """Подсчёт count + confidences + центроиды bbox по каноническому классу (P0.6)."""
    out: dict[str, dict] = {}
    for d in detections:
        code = d.class_name if hasattr(d, "class_name") else d.get("equipment_code")
        conf = float(d.confidence if hasattr(d, "confidence") else d.get("confidence", 0))
        if not code or str(code).startswith("ppe_") or code in ("person", "safety_cone"):
            continue
        bbox = None
        if hasattr(d, "bbox_norm"):
            bbox = list(d.bbox_norm)
        elif isinstance(d, dict) and d.get("bbox_norm"):
            bbox = list(d["bbox_norm"])
        slot = out.setdefault(code, {"count": 0, "max_confidence": 0.0, "confidences": [], "centroids": []})
        slot["count"] += 1
        slot["max_confidence"] = max(slot["max_confidence"], conf)
        slot["confidences"].append(conf)
        if bbox and len(bbox) >= 4:
            cx = (float(bbox[0]) + float(bbox[2])) / 2
            cy = (float(bbox[1]) + float(bbox[3])) / 2
            slot["centroids"].append([round(cx, 4), round(cy, 4)])
    return out
