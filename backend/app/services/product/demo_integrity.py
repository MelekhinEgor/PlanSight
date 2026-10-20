"""V6 Sprint A — целостность демо: маппинг видов работ, правила корпусов, проверки FS-дат."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
KB_PATH = REPO_ROOT / "backend" / "knowledge" / "kb_v1.yaml"

# Доп. RU-подсказки для Строгино / демо (поверх алиасов kb_v1)
EXTRA_ALIASES: dict[str, list[str]] = {
    "excavation": ["котлован", "выемка грунта", "разработка грунта", "ограждающ"],
    "soil_haulage": ["вывоз", "погрузка строительного мусора", "мусор"],
    "concrete_pouring": [
        "бетонн",
        "ж/б",
        "монолит",
        "фундаментн",
        "перекрыт",
        "сваи",
        "свайного",
        "ростверк",
        "лестниц",
        "лестнич",
        "плит",
        "подготовк",
    ],
    "demolition": ["снос"],
    "utilities": [
        "сетей",
        "инженерн",
        "временных инженер",
        "наружных сетей",
        "хвс",
        "гвс",
        "вентиляц",
        "кондиционир",
    ],
    "facade": ["фасад"],
    "roofing": ["кровл"],
    "structural": [
        "несущих",
        "стен из",
        "конструкц",
        "каркас",
        "ячеистого",
        "кладка",
        "наружных стен",
    ],
    "interior_finish": ["отдел", "оконных проем"],
    "landscaping": ["благоустр", "озелен", "тротуар", "проезд", "площадк", "дорог"],
    "commissioning": ["пусконалад", "ввод в эксплуатац"],
    "documentation": [
        "разрешение",
        "документац",
        "квартир",
        "замечан",
        "геодезич",
        "получение рд",
        " рд",
        "ппр",
        "рабоч",
    ],
    "installation": ["видеокамер", "камер"],
    "grading": ["планиров"],
    "formwork": ["опалуб"],
    "rebar": ["арматур"],
}

CORPUS_RE = re.compile(r"корпус\s+([\d.]+)", re.I)
COMMON_BUILDING = "COMMON"
SITE_PREFIXES = ("1.1", "1.2", "1.10")


@dataclass
class WorkMap:
    work_type_code: str | None
    work_type_id: int | None
    observability: str
    mapping_status: str  # PROPOSED | UNMAPPED | MAPPED_CONFIRMED
    reason: str


def load_kb_taxonomy() -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load(KB_PATH.read_text(encoding="utf-8"))
    return dict(raw.get("work_taxonomy") or {})


def build_alias_index(taxonomy: dict[str, dict[str, Any]] | None = None) -> list[tuple[str, str, str]]:
    """Список (alias_lower, code, observability), сортировка по длине alias desc."""
    tax = taxonomy or load_kb_taxonomy()
    rows: list[tuple[str, str, str]] = []
    for code, meta in tax.items():
        obs = str(meta.get("observability") or "UNKNOWN")
        aliases = [str(meta.get("name") or code)] + [str(a) for a in (meta.get("aliases") or [])]
        aliases += EXTRA_ALIASES.get(code, [])
        for a in aliases:
            a = a.strip().lower()
            if a:
                rows.append((a, code, obs))
    rows.sort(key=lambda x: len(x[0]), reverse=True)
    return rows


def map_work_name(
    name: str,
    *,
    wt_by_code: dict[str, int],
    alias_index: list[tuple[str, str, str]] | None = None,
) -> WorkMap:
    blob = (name or "").lower()
    idx = alias_index or build_alias_index()
    for alias, code, obs in idx:
        if alias in blob:
            # Режим DIRECT только если KB говорит DIRECT (операции, видимые камерой)
            return WorkMap(
                work_type_code=code,
                work_type_id=wt_by_code.get(code),
                observability=obs,
                mapping_status="PROPOSED",
                reason=f"alias:{alias}",
            )
    return WorkMap(None, None, "UNKNOWN", "UNMAPPED", "no_alias")


def building_from_ancestors(
    code: str,
    by_code: dict[str, dict[str, Any]],
    known_buildings: set[str],
) -> tuple[str | None, str]:
    """Корпус из имён предков WBS; фазы площадки → COMMON; без round-robin."""
    parts = str(code).split(".")
    for depth in range(len(parts), 0, -1):
        anc = ".".join(parts[:depth])
        row = by_code.get(anc)
        if not row:
            continue
        name = str(row.get("name") or "")
        m = CORPUS_RE.search(name)
        if m:
            label = f"Корпус {m.group(1)}"
            if label in known_buildings:
                return label, "wbs_ancestor"
            # Принять, если известный корпус делит числовой ключ
            key = m.group(1)
            for b in known_buildings:
                if key in b.replace("Корпус ", ""):
                    return b, "wbs_ancestor"
    # Общеплощадочные фазы под 1.1 / 1.2 / 1.10
    if len(parts) >= 2:
        prefix = f"{parts[0]}.{parts[1]}"
        if prefix in SITE_PREFIXES or any(str(code).startswith(p + ".") or str(code) == p for p in SITE_PREFIXES):
            if COMMON_BUILDING in known_buildings or True:
                return COMMON_BUILDING, "site_common"
    return None, "unassigned"


def fs_date_ok(pred_finish: datetime | None, succ_start: datetime | None, lag_minutes: int = 0) -> bool:
    """Календарный FS lag=0 (включительно): start преемника после дня finish предшественника."""
    if not pred_finish or not succ_start:
        return False
    # Задержка lag целыми днями
    lag_days = int(lag_minutes // (24 * 60)) if lag_minutes else 0
    from datetime import timedelta

    min_start = pred_finish.date() + timedelta(days=1 + lag_days)
    return succ_start.date() >= min_start


def audit_schedule_items(items: list[Any], deps: list[Any]) -> dict[str, Any]:
    by_id = {it.id: it for it in items}
    wt_null = sum(1 for it in items if not getattr(it, "work_type_id", None))
    mapped_fake = sum(1 for it in items if (it.mapping_status or "") == "MAPPED" and not it.work_type_id)
    direct = sum(1 for it in items if (it.observability_mode or "") == "DIRECT")
    modulo_like = sum(1 for it in items if (it.building_source or "") in ("seed", "round_robin", "modulo"))
    common = sum(1 for it in items if (it.building or "") == COMMON_BUILDING)
    unassigned = sum(1 for it in items if not it.building)
    fs_viol = 0
    approved_viol = 0
    for d in deps:
        a, b = by_id.get(d.predecessor_item_id), by_id.get(d.successor_item_id)
        if not a or not b:
            continue
        if (d.link_type or "FS") != "FS":
            continue
        ok = fs_date_ok(a.planned_finish, b.planned_start, int(d.lag_minutes or 0))
        if not ok:
            fs_viol += 1
            src = getattr(d, "link_source", None) or "UNKNOWN"
            if src in ("EXPERT_APPROVED", "IMPORTED"):
                approved_viol += 1
    return {
        "items": len(items),
        "deps": len(deps),
        "work_type_null": wt_null,
        "mapped_without_work_type": mapped_fake,
        "direct_count": direct,
        "building_source_seedish": modulo_like,
        "building_common": common,
        "building_unassigned": unassigned,
        "fs_date_violations": fs_viol,
        "approved_fs_violations": approved_viol,
        "mapping_status": _count_attr(items, "mapping_status"),
        "observability": _count_attr(items, "observability_mode"),
        "building_source": _count_attr(items, "building_source"),
    }


def _count_attr(items: list[Any], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        k = str(getattr(it, attr, None) or "∅")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda x: (-x[1], x[0])))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_html_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in report.get("projects") or []:
        s = p.get("schedule") or {}
        rows.append(
            "<tr>"
            f"<td>{p.get('id')}</td><td>{p.get('name')}</td><td>{p.get('slug')}</td>"
            f"<td>{s.get('items')}</td><td>{s.get('deps')}</td>"
            f"<td>{s.get('work_type_null')}</td><td>{s.get('fs_date_violations')}</td>"
            f"<td>{s.get('approved_fs_violations')}</td><td>{s.get('building_common')}</td>"
            f"<td>{s.get('direct_count')}</td>"
            "</tr>"
        )
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/><title>PlanSight V6 demo integrity</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#1a2433}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #c5d0dc;padding:6px 8px;text-align:left}}
th{{background:#eef3f8}}
.ok{{color:#0a7a3e;font-weight:600}}.bad{{color:#b42318;font-weight:600}}
</style></head><body>
<h1>V6 Sprint A — audit_demo_integrity</h1>
<p>as_of={report.get('generated_at')} · db={report.get('db_path')}</p>
<p>frames={report.get('totals',{}).get('frames')} · detections={report.get('totals',{}).get('detections')} ·
cv_verified={report.get('totals',{}).get('cv_verified_findings')}</p>
<table><thead><tr>
<th>id</th><th>name</th><th>slug</th><th>items</th><th>deps</th>
<th>wt_null</th><th>fs_viol</th><th>approved_viol</th><th>COMMON</th><th>DIRECT</th>
</tr></thead><tbody>
{''.join(rows)}
</tbody></table>
<pre>{json.dumps(report.get('dod_a') or {}, ensure_ascii=False, indent=2)}</pre>
</body></html>"""
    path.write_text(html, encoding="utf-8")
