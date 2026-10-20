"""Миграция абсолютных Windows Frame.file_path → относительные ключи для portable ZIP."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.migrate import ensure_schema_patches
from app.db.models import Frame, SessionLocal, init_db

ROOT = Path(__file__).resolve().parents[2]


def relativize(path: str) -> str:
    raw = path.replace("\\", "/")
    # Предпочитаем портативный ключ под data/frames
    m = re.search(r"(?:^|/)(frames/.+)$", raw, re.I)
    if m:
        return m.group(1)
    # Устаревшие ошибочные ключи: backend/frames/...
    if raw.startswith("backend/frames/"):
        return raw[len("backend/") :]
    m = re.search(r"(data/uploads/.+)$", raw, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(uploads/.+)$", raw, re.I)
    if m:
        return "data/" + m.group(1)
    p = Path(path)
    try:
        rel = str(p.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
        if rel.startswith("data/"):
            return rel[5:]  # frames/... or uploads/...
        if rel.startswith("backend/frames/"):
            return rel[len("backend/") :]
        return rel
    except Exception:
        return path


def main() -> None:
    get_settings.cache_clear()
    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    n = 0
    try:
        for fr in db.query(Frame).all():
            if not fr.file_path:
                continue
            new = relativize(fr.file_path)
            if new != fr.file_path:
                fr.file_path = new
                n += 1
        db.commit()
        print("PASS", {"updated": n})
    finally:
        db.close()


if __name__ == "__main__":
    main()
