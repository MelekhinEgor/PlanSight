"""Собрать product_demo/ из готовой data/ (по умолчанию — копия PlanSight_v2).

Не изменяет источник. Пишет только в целевой каталог репозитория.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SRC = Path(r"E:/PlanSight_v2/data")
DEFAULT_OUT = REPO / "product_demo"


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def pack(*, src_data: Path, out: Path, stills_fallback: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    db_src = src_data / "plansight.db"
    if not db_src.exists():
        raise SystemExit(f"no db: {db_src}")
    db_dst = out / "plansight.db"
    shutil.copy2(db_src, db_dst)

    c = sqlite3.connect(str(db_dst))
    c.row_factory = sqlite3.Row

    # Кадры, на которые ссылается БД
    paths = [r[0] for r in c.execute("SELECT DISTINCT file_path FROM frame") if r[0]]
    for rel in paths:
        rel_n = rel.replace("\\", "/")
        src = src_data / rel_n
        if not src.exists():
            # fallback: любой still
            stills = sorted(stills_fallback.glob("*.png")) + sorted(stills_fallback.glob("*.jpg"))
            if not stills:
                raise SystemExit(f"missing frame and no stills: {rel_n}")
            src = stills[0]
            print("FILL_MISSING", rel_n, "<-", src.name)
        _copy_file(src, out / rel_n)
        # если брали fallback — путь в БД уже rel_n
        c.execute("UPDATE frame SET file_path=? WHERE file_path=?", (rel_n, rel))

    # Относительные overlay_path в evidence (если файл есть в src overlays)
    overlays_src = src_data / "overlays"
    for r in c.execute("SELECT id, payload_json FROM evidence WHERE payload_json IS NOT NULL"):
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            continue
        op = payload.get("overlay_path")
        if not op:
            continue
        op_path = Path(str(op))
        rel_overlay = None
        if op_path.is_absolute():
            # E:\...\data\overlays\... → overlays/...
            parts = op_path.parts
            if "overlays" in parts:
                i = parts.index("overlays")
                rel_overlay = "/".join(parts[i:])
        else:
            rel_overlay = str(op).replace("\\", "/")
        if not rel_overlay:
            continue
        src_ov = src_data / rel_overlay
        if src_ov.exists():
            _copy_file(src_ov, out / rel_overlay)
            payload["overlay_path"] = rel_overlay
            c.execute(
                "UPDATE evidence SET payload_json=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), r["id"]),
            )
        else:
            payload.pop("overlay_path", None)
            c.execute(
                "UPDATE evidence SET payload_json=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), r["id"]),
            )

    c.commit()
    c.close()

    (out / "README.md").write_text(
        "\n".join(
            [
                "# Предзагруженное демо",
                "",
                "Снимок SQLite + кадры для портфеля (Строгино и др.).",
                "",
                "Установка в рабочую `data/`.",
                "",
                "```bash",
                "cd backend",
                "python scripts/install_product_demo.py",
                "```",
                "",
                "Docker product-demo ставит этот снимок в volume при первом запуске.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    files = [p for p in out.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    print("PACKED", out, "files", len(files), f"{size/1e6:.1f}MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-data", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--stills",
        type=Path,
        default=REPO / "demo" / "stills",
        help="fallback images for missing frame files",
    )
    args = ap.parse_args()
    pack(src_data=args.src_data, out=args.out, stills_fallback=args.stills)


if __name__ == "__main__":
    main()
