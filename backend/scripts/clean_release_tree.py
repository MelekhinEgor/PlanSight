"""Очистка дерева перед ZIP/git/Docker: __pycache__, *.pyc, временные _tmp_/_scan_."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKIP_DIR_NAMES = {".git", ".venv", "venv", "node_modules", "dist", ".pytest_cache"}


def _should_skip(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    removed: list[str] = []

    def drop(p: Path) -> None:
        rel = str(p.relative_to(REPO))
        removed.append(rel)
        if args.dry_run:
            return
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)

    for pycache in REPO.rglob("__pycache__"):
        if _should_skip(pycache):
            continue
        drop(pycache)

    for pyc in REPO.rglob("*.pyc"):
        if _should_skip(pyc):
            continue
        drop(pyc)

    for pat in ("_tmp_*", "_scan_*", "_translate_*", "_apply_ru_*", "_fix_*.py", "_comment_scan_*", "_remain_en.txt", "_en_comments.txt", "_ru_translate_*"):
        for base in (REPO, REPO / "backend", REPO / "backend" / "scripts"):
            if not base.exists():
                continue
            for p in base.glob(pat):
                if p.is_file() and not _should_skip(p):
                    drop(p)

    for p in (REPO / "frontend").glob("*.tsbuildinfo"):
        drop(p)

    verify = REPO / "_verify"
    if verify.exists():
        drop(verify)

    print({"removed": len(removed), "sample": removed[:40], "dry_run": args.dry_run})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
