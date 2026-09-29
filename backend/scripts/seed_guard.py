"""Гарды для деструктивных демо-сидов (V5 P0)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROD_DB = (REPO_ROOT / "data" / "plansight.db").resolve()
DEFAULT_DEMO_DB = (REPO_ROOT / "data" / "demo_plansight.db").resolve()


def is_production_db(path: Path) -> bool:
    p = path.resolve()
    name = p.name.lower()
    if "demo" in name or "fixture" in str(p).lower():
        return False
    if p == DEFAULT_PROD_DB:
        return True
    return name == "plansight.db"


def apply_db_path(path: Path) -> Path:
    """Форсирует путь SQLite до SessionLocal/init_db. Сбрасывает кэш engine."""
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    os.environ["PLANSIGHT_DATABASE_PATH"] = str(resolved)
    try:
        from app.core.config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass
    try:
        import app.db.models as models

        models._ENGINE = None
        models._SessionLocal = None
    except Exception:
        pass
    return resolved


def require_destructive_reset(*, db_path: Path, allow: bool, script: str) -> None:
    if not allow:
        print(
            f"REFUSED: {script} would wipe projects in {db_path}.\n"
            "Pass --allow-destructive-demo-reset and prefer --db-path data/demo_plansight.db",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if is_production_db(db_path) and allow:
        print(
            f"WARNING: destructive reset on production-like DB {db_path} "
            "(flag --allow-destructive-demo-reset set).",
            file=sys.stderr,
        )


def add_seed_cli_args(parser: argparse.ArgumentParser, *, default_db: Path | None = None) -> None:
    parser.add_argument(
        "--db-path",
        type=Path,
        default=default_db or DEFAULT_DEMO_DB,
        help="SQLite path (default: data/demo_plansight.db)",
    )
    parser.add_argument(
        "--allow-destructive-demo-reset",
        action="store_true",
        help="Required to wipe projects before reseeding",
    )
