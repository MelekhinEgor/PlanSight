"""Скачать миниатюры каталожных ЖК и прописать imageUrl.

Источник превью: Яндекс Static Maps (спутник) по координатам из деклараций.
Сохраняет файлы в frontend/public/projects/catalog/{slug}.jpg
и обновляет portfolio_catalog.json + settings_json в БД.

Запуск::

  cd backend
  $env:PLANSIGHT_DATABASE_PATH="..\\data\\plansight.db"
  .venv/Scripts/python.exe scripts/fetch_catalog_thumbnails.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CATALOG_PATH = ROOT / "app" / "data" / "portfolio_catalog.json"
OUT_DIR = REPO / "frontend" / "public" / "projects" / "catalog"
UA = "PlanSight/1.0 (local portfolio thumbs; offline demo)"


def _yandex_sat_url(lat: float, lng: float, *, w: int = 400, h: int = 300, z: int = 16) -> str:
    return (
        f"https://static-maps.yandex.ru/1.x/"
        f"?ll={lng:.6f},{lat:.6f}&z={z}&l=sat&size={w},{h}"
    )


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _polish(raw: bytes, title: str) -> Image.Image:
    """Чуть привести спутник к виду карточки портфеля."""
    from io import BytesIO

    img = Image.open(BytesIO(raw)).convert("RGB")
    img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Contrast(img).enhance(1.06)
    img = img.resize((480, 320), Image.Resampling.LANCZOS)
    # нижний градиент + подпись, чтобы карточка не выглядела «сырой»
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(220, 320):
        a = int(160 * (y - 220) / 100)
        draw.line([(0, y), (480, y)], fill=(12, 28, 48, a))
    label = (title or "").replace("ЖК ", "").replace("«", "").replace("»", "").strip()
    if len(label) > 28:
        label = label[:27] + "…"
    if label:
        draw.rectangle((12, 278, 12 + min(456, 10 + len(label) * 9), 308), fill=(255, 255, 255, 210))
        draw.text((18, 284), label, fill=(20, 40, 70, 255))
    out = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    out = out.filter(ImageFilter.SMOOTH_MORE)
    return out


def _iter_catalog_projects(catalog: dict):
    for group in catalog.get("groups") or []:
        for dev in group.get("developers") or []:
            for proj in dev.get("projects") or []:
                yield group, dev, proj


def fetch_thumbs(catalog: dict, *, force: bool = False, limit: int | None = None, sleep_s: float = 0.12) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"ok": 0, "skip": 0, "fail": 0}
    n = 0
    for _group, _dev, proj in _iter_catalog_projects(catalog):
        if limit is not None and n >= limit:
            break
        n += 1
        slug = str(proj.get("slug") or "").strip()
        if not slug:
            stats["fail"] += 1
            continue
        out_path = OUT_DIR / f"{slug}.jpg"
        public_url = f"/projects/catalog/{slug}.jpg"
        if out_path.exists() and not force and out_path.stat().st_size > 2000:
            proj["imageUrl"] = public_url
            stats["skip"] += 1
            continue
        try:
            lat = float(proj.get("lat") or 55.75)
            lng = float(proj.get("lng") or 37.62)
            raw = _download(_yandex_sat_url(lat, lng))
            img = _polish(raw, str(proj.get("name") or slug))
            img.save(out_path, format="JPEG", quality=86, optimize=True)
            proj["imageUrl"] = public_url
            stats["ok"] += 1
            print("OK", slug, out_path.stat().st_size, flush=True)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            stats["fail"] += 1
            print("FAIL", slug, exc, flush=True)
        time.sleep(sleep_s)
    return stats


def patch_db_image_urls(catalog: dict) -> int:
    sys.path.insert(0, str(ROOT))
    from app.db import SessionLocal, init_db
    from app.db.migrate import ensure_schema_patches
    from app.db.models import Project
    from app.services.product.v42_api import settings_of

    by_slug = {}
    for _g, _d, proj in _iter_catalog_projects(catalog):
        slug = str(proj.get("slug") or "")
        url = proj.get("imageUrl")
        if slug and url:
            by_slug[slug] = url

    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    updated = 0
    try:
        for p in db.query(Project).all():
            s = settings_of(p)
            slug = str(s.get("slug") or "")
            if slug in by_slug:
                if s.get("imageUrl") != by_slug[slug]:
                    s["imageUrl"] = by_slug[slug]
                    p.settings_json = json.dumps(s, ensure_ascii=False)
                    updated += 1
        db.commit()
    finally:
        db.close()
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch catalog project thumbnails")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-db", action="store_true", help="only update catalog JSON")
    args = parser.parse_args(argv)

    if not CATALOG_PATH.exists():
        raise SystemExit(f"missing {CATALOG_PATH}; run build_portfolio_catalog.py first")
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    stats = fetch_thumbs(catalog, force=args.force, limit=args.limit)
    catalog["thumbnail_source"] = {
        "provider": "yandex-static-maps",
        "layer": "sat",
        "note": "Спутниковые превью площадок по координатам деклараций (Яндекс Static Maps).",
        "url_template": "https://static-maps.yandex.ru/1.x/?ll={lon},{lat}&z=16&l=sat&size=400,300",
    }
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print("THUMBS", stats, "dir", OUT_DIR)
    if not args.no_db:
        n = patch_db_image_urls(catalog)
        print("DB_UPDATED", n)
    return 0 if stats["fail"] == 0 or stats["ok"] + stats["skip"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
