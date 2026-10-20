"""Установить product_demo/ в рабочий каталог data/ (локально или в Docker volume)."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _bundle_candidates() -> list[Path]:
    return [
        Path(os.environ.get("PLANSIGHT_PRODUCT_DEMO_DIR") or ""),
        Path("/app/product_demo"),
        REPO / "product_demo",
        BACKEND / "product_demo",
    ]


def find_bundle() -> Path:
    for p in _bundle_candidates():
        if p and (p / "plansight.db").exists():
            return p
    raise SystemExit("product_demo/plansight.db not found (pack first)")


def install(bundle: Path, dest_data: Path, *, force: bool) -> None:
    dest_data.mkdir(parents=True, exist_ok=True)
    db = dest_data / "plansight.db"
    if db.exists() and db.stat().st_size > 0 and not force:
        print("SKIP_INSTALL existing", db)
        return

    # frames + overlays из бандла
    for name in ("frames", "overlays"):
        src = bundle / name
        if not src.exists():
            continue
        dst = dest_data / name
        if dst.exists() and force:
            shutil.rmtree(dst)
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src)
                out = dst / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)

    shutil.copy2(bundle / "plansight.db", db)
    print("INSTALLED", bundle, "->", dest_data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=None)
    ap.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="каталог data/ (по умолчанию рядом с PLANSIGHT_DATABASE_PATH или REPO/data)",
    )
    ap.add_argument("--force", action="store_true", help="перезаписать существующую БД и кадры")
    args = ap.parse_args()

    bundle = args.bundle or find_bundle()
    if args.dest:
        dest = args.dest
    else:
        env = os.environ.get("PLANSIGHT_DATABASE_PATH")
        if env:
            dest = Path(env).resolve().parent
        else:
            dest = REPO / "data"

    install(bundle, dest, force=bool(args.force))


if __name__ == "__main__":
    main()
