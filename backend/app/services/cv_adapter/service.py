from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import file_sha256, get_settings
from app.db.models import ModelVersion


@dataclass
class DetectionResult:
    class_name: str
    raw_class_name: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    bbox_norm: tuple[float, float, float, float]


def canonicalize_class_name(raw: str, class_map: dict[str, str]) -> str | None:
    key = raw.strip().lower()
    underscored = key.replace("-", "_").replace(" ", "_")
    spaced = key.replace("_", " ").replace("-", " ")
    if key in class_map:
        return class_map[key]
    if underscored in class_map:
        return class_map[underscored]
    if spaced in class_map:
        return class_map[spaced]
    return class_map.get(underscored) or class_map.get(spaced)


def confidence_threshold_for(
    mapped: str,
    raw: str,
    default: float,
    class_confidence: dict[str, float],
) -> float:
    return float(
        class_confidence.get(mapped)
        or class_confidence.get(raw.lower())
        or class_confidence.get("default")
        or default
    )


class YoloAdapter:
    """Адаптер над обученными весами — не выдумывает детекции."""

    def __init__(self, model_path: Path | None = None) -> None:
        settings = get_settings()
        det = settings.section("detector")
        self.threshold = float(det["confidence_threshold"])
        self.imgsz = int(det.get("imgsz") or 960)
        self.max_det = int(det.get("max_det") or 100)
        self.class_map = {str(k).lower(): str(v) for k, v in (det.get("class_map") or {}).items()}
        self.class_confidence = {
            str(k).lower(): float(v) for k, v in (det.get("class_confidence") or {}).items()
        }
        path = model_path or settings.model_path()
        if not path.exists():
            raise FileNotFoundError(f"CV weights missing: {path}")
        self.model_path = path
        self.weights_sha256 = file_sha256(path)
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Ultralytics is not installed") from exc
        self._model = YOLO(str(path))
        self.class_names = dict(getattr(self._model, "names", {}) or {})

    def infer(self, image_bgr: np.ndarray) -> list[DetectionResult]:
        if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
            raise ValueError("empty image for inference")
        h, w = image_bgr.shape[:2]
        floor = min([self.threshold, *self.class_confidence.values()]) if self.class_confidence else self.threshold
        results = self._model.predict(
            image_bgr,
            verbose=False,
            conf=max(0.05, floor * 0.8),
            imgsz=self.imgsz,
            max_det=self.max_det,
        )
        out: list[DetectionResult] = []
        if not results:
            return out
        result = results[0]
        names = result.names or self.class_names
        boxes = result.boxes
        if boxes is None:
            return out
        for box in boxes:
            cls_id = int(box.cls.item())
            raw_name = str(names.get(cls_id, cls_id))
            mapped = canonicalize_class_name(raw_name, self.class_map)
            if mapped is None:
                continue
            conf = float(box.conf.item())
            need = confidence_threshold_for(mapped, raw_name, self.threshold, self.class_confidence)
            if conf < need:
                continue
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
            out.append(
                DetectionResult(
                    class_name=mapped,
                    raw_class_name=raw_name,
                    confidence=conf,
                    bbox_xyxy=(x1, y1, x2, y2),
                    bbox_norm=(x1 / w, y1 / h, x2 / w, y2 / h),
                )
            )
        return out

    def validate_output(self, detections: list[DetectionResult]) -> list[str]:
        warnings: list[str] = []
        for d in detections:
            if not (0.0 <= d.confidence <= 1.0):
                warnings.append(f"confidence out of range: {d.confidence}")
            x1, y1, x2, y2 = d.bbox_norm
            if not (0 <= x1 <= 1 and 0 <= y1 <= 1 and 0 <= x2 <= 1 and 0 <= y2 <= 1):
                warnings.append(f"bbox_norm out of range for {d.class_name}")
        return warnings


_ADAPTER: YoloAdapter | None = None


def get_adapter(force: bool = False) -> YoloAdapter:
    global _ADAPTER
    if _ADAPTER is None or force:
        _ADAPTER = YoloAdapter()
    return _ADAPTER


def ensure_model_version(db: Session) -> ModelVersion:
    adapter = get_adapter()
    settings = get_settings()
    existing = (
        db.query(ModelVersion)
        .filter(ModelVersion.weights_sha256 == adapter.weights_sha256)
        .one_or_none()
    )
    if existing:
        return existing
    row = ModelVersion(
        name=adapter.model_path.name,
        weights_path=str(adapter.model_path),
        weights_sha256=adapter.weights_sha256,
        class_map_json=json.dumps(settings.section("detector").get("class_map") or {}),
        config_json=json.dumps(
            {
                "confidence_threshold": settings.require("detector", "confidence_threshold"),
                "class_names": adapter.class_names,
            }
        ),
    )
    db.add(row)
    db.flush()
    return row


def draw_overlay(image_bgr: np.ndarray, detections: list[DetectionResult]) -> np.ndarray:
    canvas = image_bgr.copy()
    for d in detections:
        x1, y1, x2, y2 = [int(v) for v in d.bbox_xyxy]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (40, 180, 80), 2)
        label = f"{d.class_name} {d.confidence:.2f}"
        cv2.putText(canvas, label, (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 180, 80), 1)
    return canvas
