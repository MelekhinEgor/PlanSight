"""V6 Sprint F — backup / restore SQLite без ручного редактирования БД."""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


def _db_path() -> Path:
    import os

    env = os.environ.get("PLANSIGHT_DATABASE_PATH")
    if env:
        return Path(env)
    settings = get_settings()
    return Path(settings.database_path())


def backup(dest_dir: Path) -> Path:
    src = _db_path()
    if not src.exists():
        raise SystemExit(f"db not found: {src}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"plansight_{stamp}.db"
    shutil.copy2(src, dest)
    # также копируем соседний uploads, если есть
    uploads = src.parent / "uploads"
    if uploads.is_dir():
        up_dest = dest_dir / f"uploads_{stamp}"
        if up_dest.exists():
            shutil.rmtree(up_dest)
        shutil.copytree(uploads, up_dest)
    print("BACKUP", dest)
    return dest


def restore(archive: Path, *, allow: bool) -> None:
    if not allow:
        raise SystemExit("pass --allow-destructive-restore")
    if not archive.exists():
        raise SystemExit(f"archive not found: {archive}")
    dest = _db_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        bak = dest.with_suffix(dest.suffix + ".pre_restore")
        shutil.copy2(dest, bak)
        print("SAVED_PREV", bak)
    shutil.copy2(archive, dest)
    print("RESTORE", archive, "->", dest)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="PlanSight SQLite backup/restore")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "data" / "backups")
    r = sub.add_parser("restore")
    r.add_argument("archive", type=Path)
    r.add_argument("--allow-destructive-restore", action="store_true")
    args = p.parse_args(argv)
    get_settings.cache_clear()
    if args.cmd == "backup":
        backup(args.out)
    else:
        restore(args.archive, allow=bool(args.allow_destructive_restore))


if __name__ == "__main__":
    main()
