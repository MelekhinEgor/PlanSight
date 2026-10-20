"""Pytest fixtures: изолированная копия продуктовой БД."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _discover_product_db() -> Path | None:
    env = os.environ.get("PLANSIGHT_DATABASE_PATH")
    if env and Path(env).exists():
        return Path(env)
    candidates = [
        ROOT.parent / "data" / "plansight.db",
        ROOT.parent / "product_demo" / "plansight.db",
        ROOT / "plansight.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    # любой .db рядом с репо
    for p in (ROOT.parent / "data").glob("*.db") if (ROOT.parent / "data").exists() else []:
        return p
    return None


@pytest.fixture(scope="session")
def product_db_path() -> Path:
    src = _discover_product_db()
    if src is None:
        pytest.skip("Нет продуктовой БД для копирования (PLANSIGHT_DATABASE_PATH / data/*.db)")
    return src


@pytest.fixture()
def db_session(product_db_path: Path):
    """Временная копия БД + SessionLocal с переключением PLANSIGHT_DATABASE_PATH."""
    from app.db import models as models_mod

    tmp = Path(tempfile.mkdtemp(prefix="plansight_test_"))
    dst = tmp / "test.db"
    shutil.copy2(product_db_path, dst)
    os.environ["PLANSIGHT_DATABASE_PATH"] = str(dst)
    models_mod.reset_engine()
    Session = models_mod.SessionLocal
    db = Session()
    try:
        yield db
    finally:
        db.close()
        models_mod.reset_engine()
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def client(product_db_path: Path):
    from fastapi.testclient import TestClient

    from app.db import models as models_mod
    from app.main import app

    tmp = Path(tempfile.mkdtemp(prefix="plansight_api_"))
    dst = tmp / "test.db"
    shutil.copy2(product_db_path, dst)
    os.environ["PLANSIGHT_DATABASE_PATH"] = str(dst)
    models_mod.reset_engine()
    with TestClient(app) as c:
        yield c
    models_mod.reset_engine()
    shutil.rmtree(tmp, ignore_errors=True)
