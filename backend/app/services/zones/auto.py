"""Автономное создание зон — оператор не обязателен, но привязка корпуса ≠ доказана.

P0-01/P0-02:
- корпуса только из явных полей КСГ (не из «Ключевые»/«Конкурс»);
- равные полосы = PROPOSED_UNVERIFIED геометрия, без авто-присвоения К1/К2;
- binding корпуса только после human_verified / imported_verified.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    Camera,
    CameraVisualZone,
    CameraZoneBinding,
    Detection,
    Frame,
    InferenceRun,
)
from app.services.schedule.building import canonicalize_building_token
from app.services.schedule.service import list_schedule_items
from app.services.zones.service import list_active_zones, parse_polygon, upsert_zone


def _norm_building(raw: str) -> str:
    from app.services.schedule.building import parse_building_from_text

    p = parse_building_from_text(raw)
    if p.confident and p.normalized:
        return p.normalized
    t = " ".join((raw or "").strip().split())
    if re.fullmatch(r"[KkКк]\d+[A-Za-zА-Яа-я]?", t):
        return canonicalize_building_token(t)
    # Не нормализуем произвольный текст в «корпус»
    return ""


def collect_schedule_buildings(db: Session, project_id: int) -> list[str]:
    """Только явные/подтверждённые корпуса листовых наблюдаемых работ."""
    items = list_schedule_items(db, project_id)
    seen: list[str] = []
    for it in items:
        if getattr(it, "is_summary", False) or getattr(it, "is_milestone", False):
            continue
        if (getattr(it, "observability_mode", "") or "") == "NOT_OBSERVABLE":
            continue
        if (getattr(it, "normalized_operation", None) or "") == "documentation":
            continue
        src = (getattr(it, "building_source", None) or "unknown").lower()
        # Корпус building задан явно при импорте/CSV или human
        b = None
        if it.building:
            # доверяем полю building только если source не unknown, либо это уже канон КN
            if src in ("schedule_explicit", "wbs_parent", "human_verified", "imported_verified"):
                b = _norm_building(it.building) or canonicalize_building_token(it.building)
            elif re.fullmatch(r"[KkКк]?\d+[A-Za-zА-Яа-я]?", (it.building or "").strip()):
                b = canonicalize_building_token(it.building)
            else:
                # устаревшая строка: перепроверим raw_name строгим парсером
                from app.services.schedule.building import parse_building_from_text

                p = parse_building_from_text(it.raw_name or "")
                if p.confident:
                    b = p.normalized
                else:
                    # если building уже «К1» — ок; иначе отбрасываем фантомы
                    cand = _norm_building(it.building)
                    b = cand or None
        if b and b not in seen:
            seen.append(b)
    return seen


def _strip_polygon(i: int, n: int, gap: float = 0.02) -> list[list[float]]:
    """Равные вертикальные полосы с небольшим зазором (не overlap)."""
    width = 1.0 / n
    x0 = i * width + (gap / 2 if i > 0 else 0.0)
    x1 = (i + 1) * width - (gap / 2 if i < n - 1 else 0.0)
    x0 = max(0.0, min(1.0, x0))
    x1 = max(0.0, min(1.0, x1))
    if x1 <= x0:
        x1 = min(1.0, x0 + 0.01)
    return [[x0, 0.0], [x1, 0.0], [x1, 1.0], [x0, 1.0]]


def _is_manual(zone: CameraVisualZone) -> bool:
    notes = (zone.notes or "").lower()
    if notes.startswith("manual"):
        return True
    return (getattr(zone, "geometry_source", None) or "") == "manual" and (zone.created_by or "") not in (
        "auto",
        "system",
    )


def _is_verified_binding(bind: CameraZoneBinding | None) -> bool:
    if bind is None:
        return False
    status = (getattr(bind, "binding_status", None) or "").upper()
    source = (getattr(bind, "binding_source", None) or "").lower()
    return status == "VERIFIED" or source in ("human_verified", "imported_verified")


def auto_bind_camera(db: Session, camera: Camera, buildings: list[str]) -> dict[str, Any]:
    """Один корпус в КСГ → предложенная (не VERIFIED) привязка WHOLE_FRAME."""
    if len(buildings) != 1:
        return {"bound": False}
    b = buildings[0]
    changed = False
    # Подсказка hint — предложение, не доказательство
    if camera.building_hint != b:
        camera.building_hint = b
        changed = True
    existing = (
        db.query(CameraZoneBinding)
        .filter(
            CameraZoneBinding.camera_id == camera.id,
            CameraZoneBinding.visual_zone_key == "WHOLE_FRAME",
        )
        .order_by(CameraZoneBinding.id.desc())
        .first()
    )
    if existing and _is_verified_binding(existing):
        return {"bound": True, "building": existing.building, "bind_mode": "WHOLE_FRAME", "binding_status": "VERIFIED"}
    if existing is None or existing.building != b:
        db.add(
            CameraZoneBinding(
                project_id=camera.project_id,
                camera_id=camera.id,
                visual_zone_key="WHOLE_FRAME",
                building=b,
                notes="auto single-building PROPOSED (не доказано камерой)",
                created_by="auto",
                binding_source="unknown",
                binding_status="PROPOSED",
            )
        )
        changed = True
    elif existing is not None:
        existing.binding_status = existing.binding_status or "PROPOSED"
        existing.binding_source = existing.binding_source or "unknown"
    if changed:
        db.flush()
    return {
        "bound": True,
        "building": b,
        "bind_mode": "WHOLE_FRAME",
        "binding_status": "PROPOSED",
        "note": "привязка предложена из КСГ; требуется подтверждение оператора для адресных алертов",
    }


def auto_create_strip_zones(
    db: Session,
    camera: Camera,
    buildings: list[str],
) -> list[CameraVisualZone]:
    """N известных корпусов → N полос ROI БЕЗ присвоения building (P0-02).

    Полосы — геометрия-предложение. Identity К1/К2 слева/справа не выводится автоматически.
    """
    n = max(len(buildings), 2)
    # если buildings заданы — число полос = число корпусов, но без binding
    n = len(buildings) if buildings else n
    created: list[CameraVisualZone] = []
    for i in range(n):
        zkey = f"ZONE{i+1}"
        poly = _strip_polygon(i, n)
        label = buildings[i] if i < len(buildings) else f"Зона {i+1}"
        row = upsert_zone(
            db,
            project_id=camera.project_id,
            camera_id=camera.id,
            name=f"Предложено · участок {i+1}" + (f" (кандидат {label})" if i < len(buildings) else ""),
            zone_key=zkey,
            polygon=poly,
            building=None,  # НЕ привязываем к корпусу
            user="auto",
            geometry_source="auto_strips",
            zone_status="PROPOSED",
        )
        row.notes = "PROPOSED_UNVERIFIED auto strips; корпус не назначен"
        row.created_by = "auto"
        row.geometry_source = "auto_strips"
        row.zone_status = "PROPOSED"
        created.append(row)
    db.flush()
    return created


def _detection_centroids_for_camera(
    db: Session,
    camera_id: int,
    limit_frames: int = 80,
    *,
    as_of=None,
) -> list[float]:
    """X-центроиды. as_of ограничивает «будущее» (P0-05/06)."""
    q = db.query(Frame).filter(Frame.camera_id == camera_id, Frame.captured_at.isnot(None))
    if as_of is not None:
        q = q.filter(Frame.captured_at <= as_of)
    frames = q.order_by(Frame.id.desc()).limit(limit_frames).all()
    xs: list[float] = []
    for fr in frames:
        run = (
            db.query(InferenceRun)
            .filter(InferenceRun.frame_id == fr.id, InferenceRun.status == "COMPLETED")
            .order_by(InferenceRun.id.desc())
            .first()
        )
        if not run:
            continue
        for det in db.query(Detection).filter(Detection.inference_run_id == run.id).all():
            try:
                bbox = json.loads(det.bbox_norm_json or "{}")
                x1, x2 = float(bbox["x1"]), float(bbox["x2"])
                xs.append((x1 + x2) / 2.0)
            except (KeyError, TypeError, ValueError):
                continue
    return xs


def _kmeans_1d(xs: list[float], k: int, iters: int = 12) -> list[float]:
    if not xs or k <= 0:
        return []
    if k == 1:
        return [sum(xs) / len(xs)]
    xs_sorted = sorted(xs)
    centers = [xs_sorted[min(len(xs_sorted) - 1, int((i + 0.5) * len(xs_sorted) / k))] for i in range(k)]
    for _ in range(iters):
        buckets: list[list[float]] = [[] for _ in range(k)]
        for x in xs:
            j = min(range(k), key=lambda i: abs(centers[i] - x))
            buckets[j].append(x)
        new_centers = []
        for i, b in enumerate(buckets):
            new_centers.append(sum(b) / len(b) if b else centers[i])
        centers = new_centers
    return sorted(centers)


def refine_auto_zones_from_detections(
    db: Session,
    camera: Camera,
    buildings: list[str],
    *,
    as_of=None,
) -> bool:
    """Уточняет геометрию полос по X. Не назначает корпуса."""
    zones = [z for z in list_active_zones(db, camera.id) if not _is_manual(z)]
    if len(zones) < 2 or len(buildings) < 2:
        return False
    xs = _detection_centroids_for_camera(db, camera.id, as_of=as_of)
    if len(xs) < max(8, len(buildings) * 3):
        return False
    centers = _kmeans_1d(xs, len(buildings))
    if len(centers) != len(buildings):
        return False
    bounds = [0.0]
    for i in range(len(centers) - 1):
        bounds.append((centers[i] + centers[i + 1]) / 2.0)
    bounds.append(1.0)
    zones_sorted = sorted(
        zones, key=lambda z: parse_polygon(z.polygon_norm_json)[0][0] if parse_polygon(z.polygon_norm_json) else 0
    )
    gap = 0.015
    for i, z in enumerate(zones_sorted):
        if (getattr(z, "zone_status", None) or "").upper() == "VERIFIED":
            continue  # геометрию verified не трогаем
        x0 = bounds[i] + (gap if i > 0 else 0)
        x1 = bounds[i + 1] - (gap if i < len(zones_sorted) - 1 else 0)
        x0, x1 = max(0.0, x0), min(1.0, x1)
        if x1 <= x0:
            continue
        z.polygon_norm_json = json.dumps(
            [[x0, 0.0], [x1, 0.0], [x1, 1.0], [x0, 1.0]],
            ensure_ascii=False,
        )
        z.notes = "auto refined geometry; корпус по-прежнему не назначен"
        z.geometry_source = "auto_activity_cluster"
        z.zone_status = "PROPOSED"
        z.created_by = "auto"
    db.flush()
    return True


def auto_ensure_zones(
    db: Session,
    *,
    project_id: int,
    camera_id: int,
    refine: bool = True,
    as_of=None,
) -> dict[str, Any]:
    camera = db.get(Camera, camera_id)
    if camera is None or camera.project_id != project_id:
        return {"ok": False, "reason": "camera_not_found"}

    buildings = collect_schedule_buildings(db, project_id)
    existing = list_active_zones(db, camera_id)
    # частичный manual: не останавливаем весь auto — обновляем только non-manual
    manual = [z for z in existing if _is_manual(z)]
    auto_existing = [z for z in existing if not _is_manual(z)]

    if not buildings:
        return {
            "ok": True,
            "mode": "no_buildings",
            "zones": len(existing),
            "buildings": [],
            "note": "в КСГ нет явных корпусов — автополосы не создаём",
        }

    if len(buildings) == 1:
        for z in auto_existing:
            if (z.created_by or "") == "auto":
                z.status = "archived"
        bind = auto_bind_camera(db, camera, buildings)
        db.flush()
        return {"ok": True, "mode": "single_building", "buildings": buildings, **bind}

    # ≥2: полосы без binding; manual зоны сохраняем
    if not auto_existing:
        created = auto_create_strip_zones(db, camera, buildings)
        refined = False
        if refine:
            refined = refine_auto_zones_from_detections(db, camera, buildings, as_of=as_of)
        return {
            "ok": True,
            "mode": "auto_strips",
            "zones": len(created) + len(manual),
            "buildings": buildings,
            "refined": refined,
            "binding_status": "UNASSIGNED",
            "note": "зоны предложены; к корпусам не привязаны — требуется подтверждение",
        }

    if len(auto_existing) != len(buildings):
        for z in auto_existing:
            if (z.created_by or "") == "auto":
                z.status = "archived"
        created = auto_create_strip_zones(db, camera, buildings)
        refined = refine_auto_zones_from_detections(db, camera, buildings, as_of=as_of) if refine else False
        return {
            "ok": True,
            "mode": "auto_strips_resync",
            "zones": len(created) + len(manual),
            "buildings": buildings,
            "refined": refined,
            "binding_status": "UNASSIGNED",
        }

    refined = refine_auto_zones_from_detections(db, camera, buildings, as_of=as_of) if refine else False
    return {
        "ok": True,
        "mode": "auto_existing" if not manual else "auto_existing_with_manual",
        "zones": len(existing),
        "buildings": buildings,
        "refined": refined,
        "binding_status": "UNASSIGNED",
    }


def auto_ensure_project(db: Session, project_id: int) -> dict[str, Any]:
    cams = db.query(Camera).filter(Camera.project_id == project_id, Camera.enabled.is_(True)).all()
    results = []
    for c in cams:
        results.append({"camera_id": c.id, **auto_ensure_zones(db, project_id=project_id, camera_id=c.id)})
    return {"cameras": results, "buildings": collect_schedule_buildings(db, project_id)}
