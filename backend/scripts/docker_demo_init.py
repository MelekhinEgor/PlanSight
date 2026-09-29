"""Хелпер entrypoint: поставить предзагруженное демо, если БД ещё нет."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    db = Path(os.environ.get("PLANSIGHT_DATABASE_PATH") or "/data/plansight.db")
    if db.exists() and db.stat().st_size > 0:
        print("SKIP_SEED existing", db)
        return
    db.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PLANSIGHT_DATABASE_PATH": str(db)}

    # 1) Предзагруженный снимок (репо / образ)
    try:
        subprocess.check_call([sys.executable, "scripts/install_product_demo.py"], env=env)
        if db.exists() and db.stat().st_size > 0:
            print("OK product_demo", db)
            return
    except subprocess.CalledProcessError as exc:
        print("WARN install_product_demo", exc.returncode)

    # 2) Fallback: полный seed
    cmd = [
        sys.executable,
        "scripts/seed_plansight3_portfolio.py",
        "--db-path",
        str(db),
        "--allow-destructive-demo-reset",
    ]
    print("SEED", cmd)
    subprocess.check_call(cmd)
    for script in (
        "scripts/migrate_frame_paths_relative.py",
        "scripts/cleanup_release_db_v74.py",
        "scripts/prepare_strogino_product_demo.py",
        "scripts/diversify_demo_kpi_v72.py",
    ):
        try:
            subprocess.check_call([sys.executable, script], env=env)
        except subprocess.CalledProcessError as exc:
            print("WARN", script, exc.returncode)


if __name__ == "__main__":
    main()
