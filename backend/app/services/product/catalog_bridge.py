"""Мост admin-каталогов (wt-*/eq-*) ↔ коды KB/CV пайплайна (excavation/excavator).

Единый продуктовый источник ожидаемой техники: строки WorkEquipmentProfile,
где equipment_key предпочтительно CV-код, а work_type_key — код работ KB
(или admin id с payload.kb_work_code / payload.cv_code).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import KbCatalogItem, WorkEquipmentProfile

# Id Admin UI → таксономия техники CV / KB
ADMIN_EQ_TO_CV: dict[str, str] = {
    "eq-excavator": "excavator",
    "eq-mini-excavator": "excavator",
    "eq-bulldozer": "bulldozer",
    "eq-loader": "loader",
    "eq-drill": "equipment_unknown",
    "eq-dump": "dump_truck",
    "eq-truck": "truck_unknown",
    "eq-mixer": "concrete_mixer",
    "eq-crane": "mobile_crane",
    "eq-tower-crane": "crane_unknown",
    "eq-lift": "equipment_unknown",
}

CV_TO_ADMIN_EQ: dict[str, str] = {
    "excavator": "eq-excavator",
    "dump_truck": "eq-dump",
    "bulldozer": "eq-bulldozer",
    "loader": "eq-loader",
    "concrete_mixer": "eq-mixer",
    "mobile_crane": "eq-crane",
    "crane_unknown": "eq-crane",
    "truck_unknown": "eq-truck",
    "grader": "eq-bulldozer",
    "roller": "eq-loader",
    "concrete_pump": "eq-mixer",
    "forklift": "eq-loader",
    "telehandler": "eq-loader",
    "loader_crane": "eq-crane",
}

# Сид admin-техники по умолчанию (как frontend EQUIPMENT_SEED)
ADMIN_EQUIPMENT_SEED: list[dict[str, Any]] = [
    {"id": "eq-excavator", "name": "Экскаватор", "group": "Землеройная", "cv_code": "excavator", "unit": "маш.-ч"},
    {"id": "eq-mini-excavator", "name": "Мини-экскаватор", "group": "Землеройная", "cv_code": "excavator", "unit": "маш.-ч"},
    {"id": "eq-bulldozer", "name": "Бульдозер", "group": "Землеройная", "cv_code": "bulldozer", "unit": "маш.-ч"},
    {"id": "eq-loader", "name": "Погрузчик", "group": "Землеройная", "cv_code": "loader", "unit": "маш.-ч"},
    {"id": "eq-drill", "name": "Буровая установка", "group": "Землеройная", "cv_code": "equipment_unknown", "unit": "маш.-ч"},
    {"id": "eq-dump", "name": "Самосвал", "group": "Транспорт", "cv_code": "dump_truck", "unit": "маш.-ч"},
    {"id": "eq-truck", "name": "Грузовой автомобиль", "group": "Транспорт", "cv_code": "truck_unknown", "unit": "маш.-ч"},
    {"id": "eq-mixer", "name": "Автобетоносмеситель", "group": "Транспорт", "cv_code": "concrete_mixer", "unit": "маш.-ч"},
    {"id": "eq-crane", "name": "Автокран", "group": "Подъёмная", "cv_code": "mobile_crane", "unit": "маш.-ч"},
    {"id": "eq-tower-crane", "name": "Башенный кран", "group": "Подъёмная", "cv_code": "crane_unknown", "unit": "маш.-ч"},
    {"id": "eq-lift", "name": "Автовышка", "group": "Подъёмная", "cv_code": "equipment_unknown", "unit": "маш.-ч"},
]


def to_cv_equipment(key: str | None) -> str | None:
    if not key:
        return None
    k = str(key).strip()
    if not k:
        return None
    if k in ADMIN_EQ_TO_CV:
        return ADMIN_EQ_TO_CV[k]
    # Уже код CV / KB
    return k


def to_admin_equipment(cv_code: str | None) -> str | None:
    if not cv_code:
        return None
    c = str(cv_code).strip()
    return CV_TO_ADMIN_EQ.get(c, f"eq-{c.replace('_', '-')}")


def _payload(row: WorkEquipmentProfile | KbCatalogItem) -> dict[str, Any]:
    raw = getattr(row, "payload_json", None) or "{}"
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_admin_owned(row: WorkEquipmentProfile) -> bool:
    p = _payload(row)
    src = str(p.get("source") or "").lower()
    # Строки, синхронизированные с KB (в т.ч. бывшие joint-pattern "confirmed"), перезаписываются KB sync.
    if src.startswith("kb"):
        return False
    if row.confirmed:
        return True
    return src in ("manual", "admin", "admin_ui")


def expected_equipment_for_work(db: Session, work_code: str) -> list[str]:
    """Коды техники CV, ожидаемые для кода work_type KB.

    Предпочитаем required; иначе confirmed expected; иначе все expected (≥2 для gap).
    """
    code = (work_code or "").strip()
    if not code:
        return []

    rows = (
        db.query(WorkEquipmentProfile)
        .filter(WorkEquipmentProfile.work_type_key == code)
        .order_by(WorkEquipmentProfile.id.asc())
        .all()
    )
    # Также профили с kb_work_code в payload (admin LTC → KB)
    if not rows:
        all_rows = db.query(WorkEquipmentProfile).all()
        rows = [r for r in all_rows if code in (_payload(r).get("kb_work_codes") or []) or _payload(r).get("kb_work_code") == code]

    def cv_of(r: WorkEquipmentProfile) -> str | None:
        p = _payload(r)
        return to_cv_equipment(str(p.get("cv_code") or r.equipment_key))

    required = [cv_of(r) for r in rows if (r.role or "").lower() == "required"]
    required = [c for c in required if c]
    if required:
        return list(dict.fromkeys(required))

    confirmed_exp = [
        cv_of(r)
        for r in rows
        if (r.role or "").lower() == "expected" and (r.confirmed or _is_admin_owned(r))
    ]
    confirmed_exp = [c for c in confirmed_exp if c]
    if len(confirmed_exp) >= 1:
        return list(dict.fromkeys(confirmed_exp))

    expected = [cv_of(r) for r in rows if (r.role or "").lower() in ("required", "expected")]
    expected = [c for c in expected if c]
    return list(dict.fromkeys(expected))


def ensure_catalog_bridge(db: Session, kb: Any | None = None) -> dict[str, int]:
    """Сид admin-каталогов + bridge-профилей: UI и пайплайн на одном графе."""
    from app.services.knowledge_base.service import load_kb

    kb = kb or load_kb()
    now = datetime.utcnow()
    stats = {"equipment": 0, "work_types": 0, "profiles_added": 0, "profiles_updated": 0}

    # --- каталог техники ---
    eq_n = db.query(KbCatalogItem).filter(KbCatalogItem.catalog_key == "equipment").count()
    if eq_n == 0:
        for it in ADMIN_EQUIPMENT_SEED:
            db.add(
                KbCatalogItem(
                    catalog_key="equipment",
                    external_id=it["id"],
                    name=it["name"],
                    group_name=it["group"],
                    payload_json=json.dumps(
                        {"cv_code": it["cv_code"], "unit": it.get("unit"), "code": it["id"]},
                        ensure_ascii=False,
                    ),
                    revision=1,
                    updated_at=now,
                )
            )
            stats["equipment"] += 1
        # Также отдать чистую KB-технику вне admin seed
        for code, meta in kb.equipment.items():
            if code in ("person",):
                continue
            admin_id = to_admin_equipment(code)
            if any(x["id"] == admin_id for x in ADMIN_EQUIPMENT_SEED):
                continue
            db.add(
                KbCatalogItem(
                    catalog_key="equipment",
                    external_id=admin_id or f"eq-{code}",
                    name=str(meta.get("name") or code),
                    group_name="Прочая",
                    payload_json=json.dumps({"cv_code": code, "unit": "маш.-ч", "code": code}, ensure_ascii=False),
                    revision=1,
                    updated_at=now,
                )
            )
            stats["equipment"] += 1

    # --- каталог видов работ: все коды KB (pipeline-native id) ---
    existing_wt = {
        r.external_id: r
        for r in db.query(KbCatalogItem).filter(KbCatalogItem.catalog_key == "work_types").all()
    }
    for code, meta in kb.work_types.items():
        aliases = meta.get("aliases") or []
        payload = {
            "code": code,
            "kb_code": code,
            "unit": "компл.",
            "aliases": aliases,
            "source": "kb_v1",
        }
        row = existing_wt.get(code)
        if row is None:
            db.add(
                KbCatalogItem(
                    catalog_key="work_types",
                    external_id=code,
                    name=str(meta.get("name") or code),
                    group_name=str(meta.get("group") or "КСГ / KB"),
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    revision=1,
                    updated_at=now,
                )
            )
            stats["work_types"] += 1
        else:
            # Сохранить admin name при правке; kb_code-мост всегда
            body = _payload(row)
            if not body.get("kb_code"):
                body.update(payload)
                row.payload_json = json.dumps(body, ensure_ascii=False)
                row.updated_at = now
                stats["work_types"] += 1

    db.flush()

    # --- профили: upsert из правил KB без затирания admin-confirmed ---
    existing = {(p.work_type_key, p.equipment_key): p for p in db.query(WorkEquipmentProfile).all()}

    for r in kb.rules:
        role = "expected" if r.necessity == "typical" else ("required" if r.necessity == "required" else "optional")
        key = (r.work_type, r.equipment_type)
        row = existing.get(key)
        payload = {
            "theta": r.theta,
            "necessity": r.necessity,
            "source": "kb_v1",
            "kb_version": kb.version,
            "cv_code": r.equipment_type,
            "admin_equipment_id": to_admin_equipment(r.equipment_type),
            "kb_work_code": r.work_type,
        }
        if row is None:
            db.add(
                WorkEquipmentProfile(
                    work_type_key=r.work_type,
                    equipment_key=r.equipment_type,
                    role=role,
                    min_qty=1,
                    confirmed=False,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    revision=1,
                )
            )
            stats["profiles_added"] += 1
        elif not _is_admin_owned(row):
            row.role = role
            row.payload_json = json.dumps({**_payload(row), **payload}, ensure_ascii=False)
            row.revision = int(row.revision or 1) + 1
            stats["profiles_updated"] += 1

    # Совместные паттерны → required для demo/product gap (≥2 ед.)
    for pat in kb.joint_patterns or []:
        boosts = pat.get("boost_work_types") or []
        eqs = [str(x) for x in (pat.get("equipment") or [])]
        for wt in boosts:
            for eq in eqs:
                payload_extra = {
                    "source": "kb_joint_pattern",
                    "cv_code": eq,
                    "admin_equipment_id": to_admin_equipment(eq),
                    "kb_work_code": wt,
                    "joint_pattern": True,
                }
                row = (
                    db.query(WorkEquipmentProfile)
                    .filter(
                        WorkEquipmentProfile.work_type_key == wt,
                        WorkEquipmentProfile.equipment_key == eq,
                    )
                    .one_or_none()
                )
                if row is None:
                    db.add(
                        WorkEquipmentProfile(
                            work_type_key=wt,
                            equipment_key=eq,
                            role="expected",
                            min_qty=1,
                            confirmed=False,
                            payload_json=json.dumps(
                                {**payload_extra, "necessity": "typical", "from_joint_pattern": True},
                                ensure_ascii=False,
                            ),
                            revision=1,
                        )
                    )
                    stats["profiles_added"] += 1
                elif not _is_admin_owned(row) or str(_payload(row).get("source") or "").startswith("kb"):
                    # Партнёры joint pattern — expected (не required): gap при ≥2 ед.
                    # без повышения KB typical→required.
                    body = {**_payload(row), **payload_extra, "from_joint_pattern": True}
                    if (row.role or "").lower() == "optional":
                        row.role = "expected"
                        body.setdefault("necessity", "typical")
                    row.payload_json = json.dumps(body, ensure_ascii=False)
                    row.revision = int(row.revision or 1) + 1
                    stats["profiles_updated"] += 1

    db.flush()
    return stats


def normalize_profile_keys_for_save(item: dict[str, Any]) -> dict[str, Any]:
    """Нормализовать одну admin-связь в ключи пайплайна + сохранить admin id в payload."""
    out = dict(item)
    wt = str(out.get("work_type_key") or out.get("workTypeId") or "").strip()
    eq = str(out.get("equipment_key") or out.get("equipmentId") or "").strip()
    body = out.get("payload") if isinstance(out.get("payload"), dict) else {}
    body = dict(body or {})
    cv = to_cv_equipment(str(body.get("cv_code") or eq))
    if cv:
        body["cv_code"] = cv
        body["admin_equipment_id"] = eq if eq.startswith("eq-") else to_admin_equipment(cv)
        out["equipment_key"] = cv  # pipeline-native
        out["equipmentId"] = cv
    if wt:
        body.setdefault("admin_work_type_id", wt)
        # Если админ уже сохранил под кодом KB — оставляем; иначе wt-* и алиасы позже
        out["work_type_key"] = wt
        out["workTypeId"] = wt
    body["source"] = body.get("source") or "admin"
    out["payload"] = body
    return out
