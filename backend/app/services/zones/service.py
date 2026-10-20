"""Визуальные зоны (ROI) камеры: геометрия + назначение bbox."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import CameraVisualZone, CameraZoneBinding


Point = tuple[float, float]
Polygon = list[Point]


def point_in_polygon(x: float, y: float, polygon: Polygon) -> bool:
    """Алгоритм ray casting; полигон в нормализованных координатах."""
    if len(polygon) < 3:
        return False
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def parse_polygon(raw: str | list | None) -> Polygon:
    if raw is None:
        return []
    data = json.loads(raw) if isinstance(raw, str) else raw
    out: Polygon = []
    for p in data or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append((float(p[0]), float(p[1])))
        elif isinstance(p, dict) and "x" in p and "y" in p:
            out.append((float(p["x"]), float(p["y"])))
    return out


def bbox_centroid(bbox_norm: dict | list | tuple) -> Point:
    if isinstance(bbox_norm, dict):
        x1, y1 = float(bbox_norm["x1"]), float(bbox_norm["y1"])
        x2, y2 = float(bbox_norm["x2"]), float(bbox_norm["y2"])
    else:
        x1, y1, x2, y2 = map(float, bbox_norm[:4])
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def list_active_zones(db: Session, camera_id: int) -> list[CameraVisualZone]:
    return (
        db.query(CameraVisualZone)
        .filter(
            CameraVisualZone.camera_id == camera_id,
            CameraVisualZone.status == "active",
        )
        .order_by(CameraVisualZone.id.asc())
        .all()
    )


def assign_zone(
    zones: list[CameraVisualZone],
    bbox_norm: dict | list | tuple,
) -> tuple[CameraVisualZone | None, bool]:
    """Возвращает (zone|None, ambiguous). При пересечении ROI — ambiguous, zone=None (не двойное подтверждение)."""
    if not zones:
        return None, False
    cx, cy = bbox_centroid(bbox_norm)
    hits: list[CameraVisualZone] = []
    for z in zones:
        poly = parse_polygon(z.polygon_norm_json)
        if point_in_polygon(cx, cy, poly):
            hits.append(z)
    if len(hits) == 1:
        return hits[0], False
    if len(hits) > 1:
        return None, True
    return None, False


def building_for_zone(
    db: Session,
    camera_id: int,
    zone: CameraVisualZone | None,
    *,
    require_verified: bool = False,
) -> str | None:
    """Корпус зоны. По умолчанию — любой binding; require_verified=True — только VERIFIED."""

    def _ok(bind: CameraZoneBinding | None) -> str | None:
        if not bind:
            return None
        status = (getattr(bind, "binding_status", None) or "PROPOSED").upper()
        source = (getattr(bind, "binding_source", None) or "").lower()
        if require_verified and status != "VERIFIED" and source not in (
            "human_verified",
            "imported_verified",
        ):
            return None
        return bind.building

    if zone is not None:
        bind = (
            db.query(CameraZoneBinding)
            .filter(
                CameraZoneBinding.camera_id == camera_id,
                CameraZoneBinding.visual_zone_id == zone.id,
            )
            .order_by(CameraZoneBinding.id.desc())
            .first()
        )
        b = _ok(bind)
        if b:
            return b
        bind2 = (
            db.query(CameraZoneBinding)
            .filter(
                CameraZoneBinding.camera_id == camera_id,
                CameraZoneBinding.visual_zone_key == zone.zone_key,
            )
            .order_by(CameraZoneBinding.id.desc())
            .first()
        )
        b = _ok(bind2)
        if b:
            return b
        # Несколько ROI: не падать на WHOLE_FRAME (P0-02)
        active = list_active_zones(db, camera_id)
        if len(active) >= 2:
            return None
    bind_cam = (
        db.query(CameraZoneBinding)
        .filter(
            CameraZoneBinding.camera_id == camera_id,
            CameraZoneBinding.visual_zone_key == "WHOLE_FRAME",
        )
        .order_by(CameraZoneBinding.id.desc())
        .first()
    )
    return _ok(bind_cam)


def upsert_zone(
    db: Session,
    *,
    project_id: int,
    camera_id: int,
    name: str,
    zone_key: str,
    polygon: list,
    building: str | None = None,
    user: str = "operator",
    geometry_source: str = "manual",
    zone_status: str = "PROPOSED",
    binding_status: str = "PROPOSED",
    binding_source: str = "unknown",
) -> CameraVisualZone:
    row = (
        db.query(CameraVisualZone)
        .filter(
            CameraVisualZone.camera_id == camera_id,
            CameraVisualZone.zone_key == zone_key,
            CameraVisualZone.status == "active",
        )
        .one_or_none()
    )
    poly_json = json.dumps(polygon, ensure_ascii=False)
    if row is None:
        row = CameraVisualZone(
            project_id=project_id,
            camera_id=camera_id,
            name=name,
            zone_key=zone_key,
            polygon_norm_json=poly_json,
            status="active",
            created_by=user,
            geometry_source=geometry_source,
            zone_status=zone_status,
        )
        db.add(row)
        db.flush()
    else:
        row.name = name
        row.polygon_norm_json = poly_json
        if geometry_source:
            row.geometry_source = geometry_source
        if zone_status:
            row.zone_status = zone_status
        db.flush()
    if building:
        # ручной upsert с building → verified если operator
        src = binding_source
        st = binding_status
        if user not in ("auto", "system") and src == "unknown":
            src = "human_verified"
            st = "VERIFIED"
            row.zone_status = "VERIFIED"
        if st == "VERIFIED" and row.name and "не подтвержд" in row.name.lower():
            row.name = f"Зона {zone_key}"
            row.zone_status = "VERIFIED"
        existing_bind = (
            db.query(CameraZoneBinding)
            .filter(
                CameraZoneBinding.project_id == project_id,
                CameraZoneBinding.camera_id == camera_id,
                CameraZoneBinding.visual_zone_key == zone_key,
            )
            .order_by(CameraZoneBinding.id.desc())
            .first()
        )
        if existing_bind:
            existing_bind.visual_zone_id = row.id
            existing_bind.building = building
            existing_bind.binding_source = src
            existing_bind.binding_status = st
            existing_bind.notes = "from zone upsert"
            existing_bind.created_by = user
        else:
            db.add(
                CameraZoneBinding(
                    project_id=project_id,
                    camera_id=camera_id,
                    visual_zone_key=zone_key,
                    visual_zone_id=row.id,
                    building=building,
                    notes="from zone upsert",
                    created_by=user,
                    binding_source=src,
                    binding_status=st,
                )
            )
        db.flush()
    return row


def zones_payload(zones: list[CameraVisualZone], db: Session | None = None) -> list[dict[str, Any]]:
    out = []
    for z in zones:
        building = None
        binding_status = None
        if db is not None:
            building = building_for_zone(db, z.camera_id, z, require_verified=False)
            bind = (
                db.query(CameraZoneBinding)
                .filter(
                    CameraZoneBinding.camera_id == z.camera_id,
                    CameraZoneBinding.visual_zone_id == z.id,
                )
                .order_by(CameraZoneBinding.id.desc())
                .first()
            )
            if bind:
                binding_status = getattr(bind, "binding_status", None)
        out.append(
            {
                "id": z.id,
                "name": z.name,
                "zone_key": z.zone_key,
                "polygon_norm": parse_polygon(z.polygon_norm_json),
                "status": z.status,
                "geometry_source": getattr(z, "geometry_source", None),
                "zone_status": getattr(z, "zone_status", None),
                "building": building,
                "binding_status": binding_status or "UNASSIGNED",
            }
        )
    return out
