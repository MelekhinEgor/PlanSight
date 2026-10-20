"""Лёгкие ALTER для SQLite при расширении схемы (без Alembic)."""

from __future__ import annotations

from sqlalchemy import text

from app.db.models import get_engine


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def ensure_schema_patches() -> list[str]:
    engine = get_engine()
    applied: list[str] = []
    patches: dict[str, list[tuple[str, str]]] = {
        "schedule_dependency": [
            ("link_source", "VARCHAR(32) DEFAULT 'UNKNOWN'"),
        ],
        "schedule_item": [
            ("observability_mode", "VARCHAR(32) DEFAULT 'UNKNOWN'"),
            ("observability_reason", "VARCHAR(255)"),
            ("is_summary", "BOOLEAN DEFAULT 0"),
            ("is_milestone", "BOOLEAN DEFAULT 0"),
            ("wbs", "VARCHAR(128)"),
            ("normalized_operation", "VARCHAR(255)"),
            ("building_raw", "VARCHAR(128)"),
            ("building_normalized", "VARCHAR(64)"),
            ("building_source", "VARCHAR(32) DEFAULT 'unknown'"),
            ("unit", "VARCHAR(64)"),
            ("planned_quantity", "FLOAT"),
            ("planned_progress", "FLOAT"),
            ("actual_progress", "FLOAT"),
            ("forecast_end", "DATETIME"),
            ("actual_start", "DATETIME"),
            ("sort_order", "INTEGER DEFAULT 0"),
            ("mapping_status", "VARCHAR(32) DEFAULT 'UNMAPPED'"),
            ("canonical_work_code", "VARCHAR(64)"),
            ("canonical_work_name", "VARCHAR(255)"),
            ("wbs_node_id", "VARCHAR(128)"),
            ("project_object_id", "INTEGER"),
        ],
        "schedule_version": [
            ("kind", "VARCHAR(32) DEFAULT 'CURRENT'"),
            ("source_file_sha", "VARCHAR(64)"),
            ("version_state", "VARCHAR(32) DEFAULT 'IMPORTED'"),
            ("parent_version_id", "INTEGER"),
            ("revision", "INTEGER DEFAULT 1"),
            ("published_at", "DATETIME"),
            ("updated_at", "DATETIME"),
            ("wbs_json", "TEXT DEFAULT '[]'"),
            ("source_filename", "VARCHAR(512)"),
            ("network_recovery_json", "TEXT"),
        ],
        "organization": [
            ("group_id", "VARCHAR(128)"),
            ("created_at", "DATETIME"),
        ],
        "project_object": [
            ("parent_id", "INTEGER"),
            ("object_type", "VARCHAR(64) DEFAULT 'building'"),
            ("lat", "FLOAT"),
            ("lng", "FLOAT"),
            ("sort_order", "INTEGER DEFAULT 0"),
        ],
        "evidence_comment": [
            ("deviation_id", "INTEGER"),
            ("role", "VARCHAR(128) DEFAULT ''"),
            ("initials", "VARCHAR(16) DEFAULT ''"),
            ("kind", "VARCHAR(16) DEFAULT 'user'"),
            ("created_at", "DATETIME"),
        ],
        "kb_catalog_item": [
            ("group_name", "VARCHAR(255)"),
            ("payload_json", "TEXT DEFAULT '{}'"),
            ("revision", "INTEGER DEFAULT 1"),
            ("updated_at", "DATETIME"),
        ],
        "work_equipment_profile": [
            ("role", "VARCHAR(32) DEFAULT 'expected'"),
            ("min_qty", "INTEGER DEFAULT 1"),
            ("confirmed", "BOOLEAN DEFAULT 0"),
            ("payload_json", "TEXT DEFAULT '{}'"),
            ("revision", "INTEGER DEFAULT 1"),
        ],
        "camera_visual_zone": [
            ("geometry_source", "VARCHAR(32) DEFAULT 'manual'"),
            ("zone_status", "VARCHAR(32) DEFAULT 'PROPOSED'"),
        ],
        "camera_zone_binding": [
            ("visual_zone_id", "INTEGER"),
            ("binding_source", "VARCHAR(32) DEFAULT 'unknown'"),
            ("binding_status", "VARCHAR(32) DEFAULT 'PROPOSED'"),
        ],
        "deviation": [
            ("event_key", "VARCHAR(255)"),
            ("heuristic_score", "FLOAT"),
            ("lifecycle", "VARCHAR(32) DEFAULT 'OPEN'"),
            ("first_seen", "DATETIME"),
            ("last_seen", "DATETIME"),
            ("resolved_at", "DATETIME"),
            ("schedule_version_id", "INTEGER"),
            ("evidence_ids_json", "TEXT DEFAULT '[]'"),
        ],
        "temporal_state": [
            ("visual_zone_key", "VARCHAR(64) DEFAULT 'WHOLE_FRAME'"),
            ("last_dt_sec", "FLOAT DEFAULT 0"),
        ],
        "detection": [
            ("zone_id", "INTEGER"),
            ("zone_ambiguous", "BOOLEAN DEFAULT 0"),
        ],
        "estimate_staging": [],
    }
    with engine.begin() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        for table, cols in patches.items():
            if table not in tables:
                continue
            existing = _columns(conn, table)
            for name, decl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {decl}"))
                    applied.append(f"{table}.{name}")
        # Дозаполнение visual_zone_key
        if "temporal_state" in tables:
            conn.execute(
                text(
                    "UPDATE temporal_state SET visual_zone_key='WHOLE_FRAME' "
                    "WHERE visual_zone_key IS NULL OR visual_zone_key=''"
                )
            )
        if "schedule_version" in tables:
            cols = _columns(conn, "schedule_version")
            if "version_state" in cols:
                conn.execute(
                    text(
                        "UPDATE schedule_version SET version_state='PUBLISHED' "
                        "WHERE is_active=1 AND (version_state IS NULL OR version_state='' OR version_state='IMPORTED')"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE schedule_version SET version_state='IMPORTED' "
                        "WHERE is_active=0 AND (version_state IS NULL OR version_state='')"
                    )
                )
            if "revision" in cols:
                conn.execute(text("UPDATE schedule_version SET revision=1 WHERE revision IS NULL OR revision<1"))
    return applied
