from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import EquipmentType, EquipmentWorkRule, WorkType


@dataclass(frozen=True)
class KBRule:
    work_type: str
    equipment_type: str
    theta: float
    necessity: str
    source: str


@dataclass(frozen=True)
class KnowledgeBase:
    version: str
    work_types: dict[str, dict[str, Any]]
    equipment: dict[str, dict[str, Any]]
    rules: tuple[KBRule, ...]
    joint_patterns: tuple[dict[str, Any], ...]
    raw: dict[str, Any]

    def theta(self, work_type: str, equipment: str) -> float:
        for r in self.rules:
            if r.work_type == work_type and r.equipment_type == equipment:
                return float(r.theta)
        return 0.0

    def rules_for_work(self, work_type: str) -> list[KBRule]:
        return [r for r in self.rules if r.work_type == work_type]

    def map_work_name(self, name: str) -> str | None:
        text = " ".join((name or "").strip().lower().split())
        if not text:
            return None
        exact: list[str] = []
        # (alias_len, code) — самый длинный совпавший алиас на каждый код
        contains: list[tuple[int, str]] = []
        for code, meta in self.work_types.items():
            aliases = [a.lower() for a in meta.get("aliases", [])]
            aliases.extend([code.lower(), str(meta.get("name", "")).lower()])
            best_alias_len = 0
            for alias in dict.fromkeys(a for a in aliases if a):
                if alias == text:
                    exact.append(code)
                    best_alias_len = max(best_alias_len, len(alias))
                    continue
                if len(alias) >= 4 and alias in text:
                    best_alias_len = max(best_alias_len, len(alias))
            if best_alias_len and code not in exact:
                contains.append((best_alias_len, code))
        exact = list(dict.fromkeys(exact))
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None
        if not contains:
            return None
        contains.sort(key=lambda x: x[0], reverse=True)
        best_len = contains[0][0]
        top_codes = list(dict.fromkeys(c for ln, c in contains if ln == best_len))
        if len(top_codes) == 1:
            return top_codes[0]
        return None


@lru_cache(maxsize=1)
def load_kb(force: bool = False) -> KnowledgeBase:
    if force:
        load_kb.cache_clear()
    path = get_settings().kb_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = tuple(
        KBRule(
            work_type=str(r["work_type"]),
            equipment_type=str(r["equipment_type"]),
            theta=float(r["theta"]),
            necessity=str(r.get("necessity", "possible")),
            source=str(r.get("source", "expert_seed")),
        )
        for r in (raw.get("rules") or [])
    )
    return KnowledgeBase(
        version=str(raw.get("version", "kb_v1")),
        work_types=dict(raw.get("work_taxonomy") or {}),
        equipment=dict(raw.get("equipment_taxonomy") or {}),
        rules=rules,
        joint_patterns=tuple(raw.get("joint_equipment_patterns") or []),
        raw=raw,
    )


def validate_rules(kb: KnowledgeBase | None = None) -> list[str]:
    kb = kb or load_kb()
    errors: list[str] = []
    for r in kb.rules:
        if r.work_type not in kb.work_types:
            errors.append(f"unknown work_type in rule: {r.work_type}")
        if r.equipment_type not in kb.equipment:
            errors.append(f"unknown equipment_type in rule: {r.equipment_type}")
        if not (0.0 <= r.theta <= 1.0):
            errors.append(f"theta out of range for {r.work_type}/{r.equipment_type}")
    return errors


def sync_kb_to_db(db: Session, kb: KnowledgeBase | None = None) -> KnowledgeBase:
    kb = kb or load_kb()
    errors = validate_rules(kb)
    if errors:
        raise ValueError("KB validation failed: " + "; ".join(errors))

    for code, meta in kb.work_types.items():
        row = db.query(WorkType).filter(WorkType.code == code).one_or_none()
        aliases = json.dumps(meta.get("aliases") or [], ensure_ascii=False)
        if row is None:
            db.add(WorkType(code=code, name=str(meta.get("name", code)), aliases_json=aliases))
        else:
            row.name = str(meta.get("name", code))
            row.aliases_json = aliases

    for code, meta in kb.equipment.items():
        row = db.query(EquipmentType).filter(EquipmentType.code == code).one_or_none()
        aliases = json.dumps(meta.get("cv_aliases") or [], ensure_ascii=False)
        if row is None:
            db.add(
                EquipmentType(code=code, name=str(meta.get("name", code)), cv_aliases_json=aliases)
            )
        else:
            row.name = str(meta.get("name", code))
            row.cv_aliases_json = aliases

    db.flush()
    wt_by_code = {w.code: w for w in db.query(WorkType).all()}
    eq_by_code = {e.code: e for e in db.query(EquipmentType).all()}

    db.query(EquipmentWorkRule).filter(EquipmentWorkRule.kb_version == kb.version).delete()
    for r in kb.rules:
        db.add(
            EquipmentWorkRule(
                kb_version=kb.version,
                work_type_id=wt_by_code[r.work_type].id,
                equipment_type_id=eq_by_code[r.equipment_type].id,
                theta=r.theta,
                necessity=r.necessity,
                source=r.source,
            )
        )
    # Профили и admin catalogs: общий мост (не затирает подтверждённые admin-строки)
    from app.services.product.catalog_bridge import ensure_catalog_bridge

    ensure_catalog_bridge(db, kb)
    db.flush()
    return kb


def equipment_likelihood(
    equipment_present: dict[str, float],
    work_type: str,
    observability: float,
    kb: KnowledgeBase | None = None,
) -> dict[str, Any]:
    """Совместимость с heuristic_v2 (не likelihood ratio).

    Оставлено имя для совместимости вызовов; score_kind всегда uncalibrated.
    """
    from app.services.activity.service import equipment_feature_score, joint_pattern_boost

    kb = kb or load_kb()
    eq = equipment_feature_score(equipment_present, work_type, kb=kb, observability=observability)
    boost = joint_pattern_boost(equipment_present, work_type, kb)
    score = max(0.0, min(1.0, float(eq["equipment_score"]) + boost))
    return {
        "likelihood_score": score,
        "equipment_score": eq["equipment_score"],
        "boost": boost,
        "contributions": eq.get("contributions") or [],
        "score_kind": "uncalibrated_score",
        "note": "heuristic feature score, not P(O|A)",
    }


def export_kb(path: Path | None = None) -> Path:
    kb = load_kb()
    out = path or (get_settings().data_dir() / f"kb_export_{kb.version}.yaml")
    out.write_text(yaml.safe_dump(kb.raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out
