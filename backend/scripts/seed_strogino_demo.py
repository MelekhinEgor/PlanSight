"""Идемпотентный демо-сид V5 в изолированную SQLite (по умолчанию: data/demo_plansight.db).

Запуск (из backend/):
  .venv\\Scripts\\python.exe scripts\\seed_strogino_demo.py --allow-destructive-demo-reset
  .venv\\Scripts\\python.exe scripts\\seed_strogino_demo.py --db-path ../data/demo_plansight.db --allow-destructive-demo-reset
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_guard import DEFAULT_DEMO_DB, add_seed_cli_args
from seed_plansight3_portfolio import main as portfolio_main


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Seed isolated Strogino / portfolio demo DB")
    add_seed_cli_args(parser, default_db=DEFAULT_DEMO_DB)
    args = parser.parse_args(argv)
    # Пробрасываем тот же argv в portfolio seed
    forward = ["--db-path", str(args.db_path)]
    if args.allow_destructive_demo_reset:
        forward.append("--allow-destructive-demo-reset")
    portfolio_main(forward)


if __name__ == "__main__":
    main()
