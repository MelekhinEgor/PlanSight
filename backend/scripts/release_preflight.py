"""V7.4 release preflight — ненулевой exit при любом блокере релиза.

Проверяет гигиену shipped DB, абсолютные пути, CV Lab, MANUAL_DEMO, README, веса YOLO.
Опционально гоняет pytest при --with-tests.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
ABS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def fail(msg: str, errors: list[str]) -> None:
    errors.append(msg)
    print("FAIL:", msg)


def check_readme(errors: list[str]) -> None:
    readme = REPO_ROOT / "README.md"
    if not readme.is_file():
        fail("README.md отсутствует", errors)
        return
    text = readme.read_text(encoding="utf-8")
    if "docker compose" not in text.lower() and "docker-compose" not in text.lower():
        fail("В README нет инструкции Docker", errors)
    if "uvicorn" not in text.lower() and "npm" not in text.lower():
        fail("В README нет локального запуска", errors)


def check_yolo(errors: list[str]) -> None:
    cfg = BACKEND_ROOT / "config.yaml"
    model = REPO_ROOT / "models" / "yolo11s_combined_v1_best.pt"
    # Принимаем документированный путь или путь из config.yaml
    candidates = [model]
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "model:" in line and not line.strip().startswith("#"):
                rel = line.split(":", 1)[1].strip().strip("\"'")
                if rel:
                    candidates.append((BACKEND_ROOT / rel).resolve())
                    candidates.append((REPO_ROOT / rel).resolve())
    if not any(p.is_file() for p in candidates):
        fail("Нет весов YOLO (models/yolo11s_combined_v1_best.pt)", errors)


def check_db(errors: list[str]) -> None:
    db_path = REPO_ROOT / "data" / "plansight.db"
    if not db_path.is_file():
        fail(f"Нет shipped DB: {db_path}", errors)
        return
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        for pid, name in cur.execute("SELECT id, name FROM project").fetchall():
            n = (name or "").lower()
            if "cv lab" in n or "синтетич" in n:
                fail(f"CV Lab всё ещё в shipped DB: id={pid} name={name}", errors)

        try:
            cols = {r[1] for r in cur.execute("PRAGMA table_info(deviation)").fetchall()}
            detail_col = "details_json" if "details_json" in cols else None
            for row in cur.execute(
                f"SELECT id, code, {detail_col or 'code'}, lifecycle FROM deviation"
            ).fetchall():
                did, code, details, life = row[0], row[1], row[2], row[3]
                blob = f"{details or ''}".lower()
                if "manual_demo" in blob or "учебный график" in blob:
                    fail(f"MANUAL_DEMO/учебный finding id={did} code={code}", errors)
        except sqlite3.OperationalError:
            pass

        try:
            for fid, path in cur.execute("SELECT id, file_path FROM frame").fetchall():
                if not path:
                    continue
                if ABS_DRIVE.match(path) or path.startswith("\\\\"):
                    fail(f"Абсолютный путь в frame id={fid}: {path[:80]}", errors)
                    break
        except sqlite3.OperationalError:
            pass

        cv_codes = (
            "EARLY_START",
            "WORK_AFTER_PLAN",
            "REQUIRED_EQUIPMENT_GAP",
            "EQUIPMENT_COMPOSITION_ANOMALY",
            "POSSIBLE_LATE_START",
            "UNCONFIRMED_ACTIVITY",
        )
        try:
            for did, code, evid, life in cur.execute(
                "SELECT id, code, evidence_ids_json, lifecycle FROM deviation"
            ).fetchall():
                if code not in cv_codes:
                    continue
                if (life or "").upper() not in ("OPEN", "NEW", "ACTIVE", ""):
                    continue
                try:
                    ids = json.loads(evid or "[]")
                except Exception:
                    ids = []
                if not ids:
                    fail(f"Открытый CV finding без evidence frames: id={did} code={code}", errors)
        except sqlite3.OperationalError:
            pass
    finally:
        con.close()


def check_pycache(errors: list[str]) -> None:
    # В workspace __pycache__ допустим; под data/ — нет
    bad = list((REPO_ROOT / "data").rglob("__pycache__")) + list((REPO_ROOT / "data").rglob("*.pyc"))
    if bad:
        fail(f"__pycache__/.pyc под data/: {bad[0]}", errors)


def run_tests(errors: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line"],
        cwd=str(BACKEND_ROOT),
        env=env,
    )
    if proc.returncode != 0:
        fail(f"pytest завершился с кодом {proc.returncode}", errors)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-tests", action="store_true")
    ap.add_argument("--skip-yolo", action="store_true")
    args = ap.parse_args()
    errors: list[str] = []
    check_readme(errors)
    if not args.skip_yolo:
        check_yolo(errors)
    check_db(errors)
    check_pycache(errors)
    if args.with_tests:
        run_tests(errors)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "errors": []}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
