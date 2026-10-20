"""Сборка portfolio_catalog.json из открытого датасета Betonij.ru.

Источник правды:
  https://betonij.ru/dataset/ — агрегат актуальных проектных деклараций
  застройщиков по Москве (регион 77). Выгрузка:
  https://betonij.ru/data/current/agg/all.json.zip

Использование данных — со ссылкой на betonij.ru (условия автора датасета).

Запуск::

  cd backend
  .venv/Scripts/python.exe scripts/build_portfolio_catalog.py
  .venv/Scripts/python.exe scripts/build_portfolio_catalog.py --download
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
GROUPS_PATH = ROOT / "app" / "data" / "company_groups.json"
OUT_PATH = ROOT / "app" / "data" / "portfolio_catalog.json"
EXTERNAL_DIR = REPO / "data" / "external"
BETONIJ_ZIP_URL = "https://betonij.ru/data/current/agg/all.json.zip"
BETONIJ_JSON = EXTERNAL_DIR / "all.json"

# Явные алиасы GROUP из датасета → id из company_groups.json
GROUP_ALIASES: dict[str, str] = {
    "3s group": "3s-group",
    "afi development": "afi-development",
    "alvek": "alvek",
    "baza development": "baza-development",
    "capital group": "capital-group",
    "dars development": "dars-development",
    "dars": "dars-development",
    "dominanta": "dominanta",
    "element": "element",
    "forma": "forma",
    "kr properties": "kr-properties",
    "legenda": "legenda",
    "legenda intelligent development": "legenda",
    "level group": "level-group",
    "level": "level-group",
    "mos city group": "mos-city-group",
    "mr group": "mr-group",
    "mr": "mr-group",
    "seven suns development": "seven-suns",
    "seven suns": "seven-suns",
    "sezar group": "sezar-group",
    "sezar": "sezar-group",
    "sminex": "sminex",
    "stone": "stone",
    "touch": "touch",
    "uds": "uds",
    "uniq development": "uniq-development",
    "upside": "upside",
    "upside development": "upside",
    "upside девелопмент": "upside",
    "vesper": "vesper",
    "vos'hod": "voshod",
    "voshod": "voshod",
    "ziggurat": "ziggurat",
    "а101": "a101",
    "a101": "a101",
    "абсолют": "absolut",
    "аеон девелопмент": "aeon",
    "аеон": "aeon",
    "аквилон": "akvilon",
    "апсис глоб": "apsis-glob",
    "атлант": "atlant",
    "афинастрой": "afinastroy",
    "брусника": "brusnika",
    "вектор": "vektor",
    "галс-девелопмент": "gals-development",
    "галс девелопмент": "gals-development",
    "галс": "gals-development",
    "главстрой": "glavstroy",
    "град девелопмент": "grad-development",
    "гранель": "granel",
    "форсайт": "forsayt",
    "форсайт девелопмент": "forsayt",
    "группа компаний «форсайт девелопмент»": "forsayt",
    "север": "sever",
    "девелоперская компания север": "sever",
    "донстрой": "donstroy",
    "идиль": "idil",
    "идиль девелопмент": "idil",
    "ингеоцентр": "ingeocenter",
    "колди": "koldi",
    "koldi": "koldi",
    # в датасете встречается смешанная раскладка KOЛDИ
    "koлdи": "koldi",
    "кoлди": "koldi",
    "концерн крост": "krost",
    "крост": "krost",
    "кортос": "kortros",
    "лср": "lsr",
    "группа лср": "lsr",
    "мангазея": "mangazeya",
    "новая эра": "novaya-era",
    "ом девелопмент": "om-development",
    "основа": "osnova",
    "отрада": "otrada",
    "пик": "pik",
    "группа компаний пик": "pik",
    "пионер": "pioner",
    "плюс девелопмент": "plus-development",
    "развитие": "razvitie",
    "рг-девелопмент": "rg-development",
    "рг девелопмент": "rg-development",
    "ркс девелопмент": "rks-development",
    "родина": "rodina",
    "самолет": "samolet",
    "самолёт": "samolet",
    "группа самолет": "samolet",
    "группа самолёт": "samolet",
    "сск": "ssk",
    "страна девелопмент": "strana-development",
    "страна": "strana-development",
    "стройком": "stroykom",
    "стройтэкс": "stroytex",
    "талан": "talan",
    "ташир": "tashir",
    "текта групп": "tekta",
    "tekta group": "tekta",
    "текта": "tekta",
    "точно": "tochno",
    "тпу рассказовка": "tpu-rasskazovka",
    "уэз": "uez",
    "фск": "fsk",
    "группа фск": "fsk",
    "центрстрой": "tsentstroy",
    "элит эко": "elit-eko",
    "эталон": "etalon",
    "группа эталон": "etalon",
    "юникей": "unikey",
}

# Демо-ЖК уже в PRODUCT_DEMO — не дублируем по нормализованному имени.
DEMO_NAME_BLOCKLIST = {
    "зеленый парк",
    "зелёный парк",
    "строгино 360",
    "амурский парк",
    "театральный квартал",
    "невский",
    "nevsky plaza",
    "правда",
    "плеханова 11",
}


def _norm(text: str) -> str:
    s = (text or "").lower().replace("ё", "е")
    s = s.replace("«", "").replace("»", "").replace('"', "").replace("'", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^жк\s+", "", s)
    s = re.sub(r"^группа компаний\s+", "", s)
    s = re.sub(r"[«»\"'()]", "", s)
    return s.strip(" -–—")


def _slugify(text: str) -> str:
    tr = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya",
    }
    s = _norm(text)
    s = "".join(tr.get(ch, ch) for ch in s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:56] or "project")


def download_betonij() -> Path:
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = EXTERNAL_DIR / "betonij_all.json.zip"
    print("DOWNLOAD", BETONIJ_ZIP_URL)
    urllib.request.urlretrieve(BETONIJ_ZIP_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(EXTERNAL_DIR)
    if not BETONIJ_JSON.exists():
        raise SystemExit(f"expected {BETONIJ_JSON} after unzip")
    print("SAVED", BETONIJ_JSON, "bytes", BETONIJ_JSON.stat().st_size)
    return BETONIJ_JSON


def resolve_group_id(raw_group: str, id_by_norm_name: dict[str, str]) -> str | None:
    key = _norm(raw_group)
    if not key:
        return None
    if key in GROUP_ALIASES:
        return GROUP_ALIASES[key]
    if key in id_by_norm_name:
        return id_by_norm_name[key]
    # частичное совпадение по имени справочника
    for name_norm, gid in id_by_norm_name.items():
        if name_norm and (name_norm in key or key in name_norm):
            return gid
    return None


def build_from_betonij(rows: list[dict], groups_meta: list[dict]) -> dict:
    id_by_norm = {_norm(g["name"]): g["id"] for g in groups_meta}
    name_by_id = {g["id"]: g["name"] for g in groups_meta}

    # Агрегируем декларации → ЖК: (group_id, cname_norm)
    buckets: dict[tuple[str, str], dict] = {}
    unmatched_groups: dict[str, int] = defaultdict(int)
    skipped_demo = 0

    for r in rows:
        if str(r.get("reg")) != "77":
            continue
        cname = (r.get("cname") or r.get("cname_orig") or "").strip()
        if not cname or cname.startswith("*"):
            continue
        cname_norm = _norm(cname)
        if not cname_norm or cname_norm in DEMO_NAME_BLOCKLIST:
            if cname_norm in DEMO_NAME_BLOCKLIST:
                skipped_demo += 1
            continue

        gid = resolve_group_id(str(r.get("GROUP") or ""), id_by_norm)
        if not gid:
            unmatched_groups[str(r.get("GROUP") or "").strip() or "(empty)"] += 1
            continue

        dev = (r.get("DEV") or "").strip() or "Застройщик не указан"
        key = (gid, cname_norm)
        bucket = buckets.get(key)
        lat = r.get("geolat")
        lng = r.get("geolong")
        try:
            lat_f = float(lat) if lat not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            lat_f = None
        try:
            lng_f = float(lng) if lng not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            lng_f = None

        if bucket is None:
            buckets[key] = {
                "group_id": gid,
                "group_name": name_by_id.get(gid, str(r.get("GROUP") or gid)),
                "cname": cname if not cname.startswith("ЖК") else cname,
                "devs": CounterLite(),
                "addrs": [],
                "lats": [],
                "lngs": [],
                "updated": str(r.get("UPDATED") or ""),
                "aids": set(),
            }
            bucket = buckets[key]
        bucket["devs"].add(dev)
        if r.get("addr"):
            bucket["addrs"].append(str(r["addr"]).strip())
        if lat_f and lng_f:
            bucket["lats"].append(lat_f)
            bucket["lngs"].append(lng_f)
        if str(r.get("UPDATED") or "") > bucket["updated"]:
            bucket["updated"] = str(r.get("UPDATED") or "")
            # предпочитаем более «красивое» имя с последней декларации
            bucket["cname"] = cname
        if r.get("AID"):
            bucket["aids"].add(str(r["AID"]))

    # group → developer → projects
    by_group: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    used_slugs: set[str] = set()

    for (_gid, _cn), b in sorted(buckets.items(), key=lambda x: (x[1]["group_id"], x[1]["cname"])):
        gid = b["group_id"]
        gname = b["group_name"]
        dev_name = b["devs"].most_common(1)[0][0]
        lat = sum(b["lats"]) / len(b["lats"]) if b["lats"] else 55.75
        lng = sum(b["lngs"]) / len(b["lngs"]) if b["lngs"] else 37.62
        addr = b["addrs"][0] if b["addrs"] else "Москва"
        # нормализуем отображаемое имя
        display = b["cname"].strip()
        if not display.lower().startswith("жк"):
            display = f"ЖК «{display}»" if "«" not in display else f"ЖК {display}"

        base = f"cat-{gid}-{_slugify(b['cname'])}"
        slug = base
        n = 2
        while slug in used_slugs:
            slug = f"{base}-{n}"
            n += 1
        used_slugs.add(slug)

        by_group[gid][dev_name].append(
            {
                "slug": slug,
                "name": display,
                "region": "Москва",
                "address": addr[:240],
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                        "commissioning": None,
                        "metro": None,
                        "metroWalk": None,
                        # превью кладёт fetch_catalog_thumbnails.py → /projects/catalog/{slug}.jpg
                        "imageUrl": f"/projects/catalog/{slug}.jpg",
                        "source_refs": {
                            "declaration_ids": sorted(b["aids"])[:12],
                            "updated": b["updated"],
                        },
                    }
                )

    catalog_groups = []
    developer_count = 0
    project_count = 0
    for g in groups_meta:
        gid = g["id"]
        devs_map = by_group.get(gid) or {}
        if not devs_map:
            continue
        developers = []
        for di, (dev_name, projects) in enumerate(sorted(devs_map.items(), key=lambda x: x[0])):
            developer_count += 1
            project_count += len(projects)
            developers.append(
                {
                    "id": f"dev-{gid}-{di + 1}",
                    "name": dev_name,
                    "projects": projects,
                }
            )
        catalog_groups.append({"id": gid, "name": g["name"], "developers": developers})

    unmatched_top = sorted(unmatched_groups.items(), key=lambda x: -x[1])[:25]
    return {
        "source": "BETONIJ_DECLARATIONS",
        "note": (
            "Открытый датасет Betonij.ru: агрегат актуальных проектных деклараций "
            "застройщиков по Москве (reg=77). https://betonij.ru/dataset/ — "
            "использование со ссылкой на источник. Снимок: data/external/all.json"
        ),
        "source_url": "https://betonij.ru/data/current/agg/all.json.zip",
        "attribution": "betonij.ru",
        "region_filter": "77",
        "stats": {
            "groups": len(catalog_groups),
            "developers": developer_count,
            "projects": project_count,
            "skipped_demo_name_overlap": skipped_demo,
            "unmatched_group_labels": len(unmatched_groups),
        },
        "unmatched_groups_sample": unmatched_top,
        "groups": catalog_groups,
    }


class CounterLite:
    def __init__(self) -> None:
        self._c: dict[str, int] = defaultdict(int)

    def add(self, item: str) -> None:
        self._c[item] += 1

    def most_common(self, n: int = 1) -> list[tuple[str, int]]:
        items = sorted(self._c.items(), key=lambda x: (-x[1], x[0]))
        return items[:n]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build portfolio catalog from Betonij open data")
    parser.add_argument("--download", action="store_true", help="re-download all.json.zip")
    parser.add_argument("--json", type=Path, default=BETONIJ_JSON)
    args = parser.parse_args(argv)

    if args.download or not args.json.exists():
        download_betonij()
        args.json = BETONIJ_JSON

    groups_meta = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
    print("LOAD", args.json)
    rows = json.loads(args.json.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SystemExit("betonij json must be a list of declarations")

    payload = build_from_betonij(rows, groups_meta)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT_PATH)
    print("STATS", payload["stats"])
    if payload.get("unmatched_groups_sample"):
        print("UNMATCHED_SAMPLE")
        for name, cnt in payload["unmatched_groups_sample"][:15]:
            print(f"  {cnt:4d}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
