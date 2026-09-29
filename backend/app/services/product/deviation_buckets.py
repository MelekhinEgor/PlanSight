"""V7.2 — группировка отклонений: внимание vs качество данных."""

from __future__ import annotations

from typing import Any

from app.services.product.health import DATA_QUALITY_CODES, PRODUCTION_CODES


def bucket_for_code(code: str | None) -> str:
    c = code or ""
    if c in DATA_QUALITY_CODES:
        return "needs_data"
    if c in PRODUCTION_CODES:
        return "attention"
    return "other"


def group_coverage_gaps(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Схлопнуть повторы CAMERA_COVERAGE_GAP по (camera, zone, day)."""
    out: list[dict[str, Any]] = []
    seen: dict[tuple, dict[str, Any]] = {}
    for it in items:
        if it.get("code") != "CAMERA_COVERAGE_GAP":
            out.append(it)
            continue
        details = it.get("details") or {}
        cam = details.get("camera_id") or it.get("camera_id")
        zone = details.get("camera_visual_zone_id") or details.get("zone_key")
        day = (it.get("created_at") or "")[:10]
        key = (cam, zone, day, it.get("schedule_item_id"))
        if key in seen:
            seen[key]["group_count"] = int(seen[key].get("group_count") or 1) + 1
            seen[key]["grouped_ids"] = list(seen[key].get("grouped_ids") or [seen[key]["id"]]) + [it["id"]]
            continue
        row = dict(it)
        row["group_count"] = 1
        row["grouped_ids"] = [it["id"]]
        seen[key] = row
        out.append(row)
    return out


def decorate_deviation_list(items: list[dict[str, Any]]) -> dict[str, Any]:
    decorated = []
    for it in items:
        row = dict(it)
        row["bucket"] = bucket_for_code(it.get("code"))
        decorated.append(row)
    grouped = group_coverage_gaps(decorated)
    attention = [i for i in grouped if i.get("bucket") == "attention"]
    needs_data = [i for i in grouped if i.get("bucket") == "needs_data"]
    other = [i for i in grouped if i.get("bucket") not in ("attention", "needs_data")]
    return {
        "items": grouped,
        "buckets": {
            "attention": attention,
            "needs_data": needs_data,
            "other": other,
        },
        "counts": {
            "attention": len(attention),
            "needs_data": len(needs_data),
            "other": len(other),
            "raw": len(items),
            "grouped": len(grouped),
        },
    }
