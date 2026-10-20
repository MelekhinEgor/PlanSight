"""Справочник групп компаний (синхрон с frontend/src/data/companyGroups.ts)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[2] / "data" / "company_groups.json"


@lru_cache(maxsize=1)
def load_company_groups() -> list[dict[str, str]]:
    try:
        raw = json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        gid = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if gid and name:
            out.append({"id": gid, "name": name})
    return out


@lru_cache(maxsize=1)
def company_group_names() -> dict[str, str]:
    return {g["id"]: g["name"] for g in load_company_groups()}


def company_group_name(group_id: str | None) -> str | None:
    if not group_id:
        return None
    return company_group_names().get(str(group_id))
