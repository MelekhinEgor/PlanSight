"""Хелперы продуктового API V4.2 (этапы 2–8).

Эндпоинты добавлены / обогащены (проводка из main.py):
  Stage 3
    GET  /api/projects, GET /api/projects/{id}     — поля карточки проекта PlanSight(3)
    GET  /api/portfolio                           — PortfolioRow + objects из project_object
    GET/POST /api/projects/{id}/objects
    GET/POST/PATCH/DELETE /api/projects/{id}/objects/{oid}
  Stage 4
    GET/PUT /api/admin/catalogs/{catalogKey}      — kb_catalog_item
    GET/PUT /api/admin/work-profiles              — work_equipment_profile
  Stage 5–6
    schedule workspace включает network_recovery (из schedule_version.network_recovery_json)
    PATCH /api/projects/{id}/schedules/{vid}/network-recovery
    POST /api/ai/mapping/status
    POST /api/ai/mapping/suggest
  Stage 7–8
    GET/POST /api/projects/{id}/activities/{activityId}/evidence-thread?signal=
    (cameras/zones/frames/deviations уже в main.py)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import (
    EvidenceComment,
    KbCatalogItem,
    Organization,
    Project,
    ProjectObject,
    WorkEquipmentProfile,
)

CATALOG_ALIASES = {
    "work-types": "work_types",
    "work_types": "work_types",
    "equipment": "equipment",
}


def settings_of(p: Project) -> dict[str, Any]:
    try:
        return json.loads(p.settings_json or "{}")
    except Exception:
        return {}


def normalize_catalog_key(raw: str) -> str:
    key = (raw or "").strip().lower().replace(" ", "_")
    if key not in CATALOG_ALIASES:
        raise HTTPException(400, f"unknown catalogKey '{raw}' (work_types|equipment)")
    return CATALOG_ALIASES[key]


def developer_payload(settings: dict[str, Any], org: Organization | None = None) -> dict[str, Any] | None:
    """Формат PlanSight(3): застройщик {id, name, groupId}."""
    raw = settings.get("developer")
    if isinstance(raw, dict) and (raw.get("name") or raw.get("id")):
        return {
            "id": str(raw.get("id") or f"org-{raw.get('name')}"),
            "name": str(raw.get("name") or "—"),
            "groupId": raw.get("groupId") or raw.get("group_id") or settings.get("companyGroupId") or settings.get("group_id"),
        }
    if org is not None:
        return {"id": str(org.id), "name": org.name, "groupId": org.group_id}
    if isinstance(raw, str) and raw.strip():
        group = settings.get("companyGroupId") or settings.get("group_id") or settings.get("groupId")
        org_id = settings.get("developer_id") or settings.get("organization_id") or f"dev-{raw.strip()}"
        return {"id": str(org_id), "name": raw.strip(), "groupId": group}
    return None


def project_card(p: Project, *, org: Organization | None = None, db: Session | None = None) -> dict[str, Any]:
    """Сериализация Project в форме карточки PlanSight(3) — статус из ProjectHealthService."""
    s = settings_of(p)
    developer = developer_payload(s, org=org)
    badge_schedule = s.get("badge_schedule")
    if badge_schedule and any(x in str(badge_schedule).lower() for x in ("учеб", "демо", "demo", "synth")):
        badge_schedule = None
    badge_photos = s.get("badge_photos")
    if badge_photos and any(x in str(badge_photos).lower() for x in ("учеб", "демо", "demo", "synth")):
        badge_photos = None
    status = "NO_DATA"
    status_source = "NONE"
    status_reason = None
    if db is not None:
        from app.services.product.health import compute_project_health

        h = compute_project_health(db, p)
        status = h.status
        status_source = h.status_source
        status_reason = h.status_reason
    return {
        "id": p.id,
        "name": p.name,
        "timezone": p.timezone,
        "status": status,
        "status_source": status_source,
        "status_reason": status_reason,
        "developer": developer,
        "region": s.get("region"),
        "address": s.get("address"),
        "slug": s.get("slug"),
        "imageUrl": s.get("imageUrl") or s.get("image_url"),
        "commissioning": s.get("commissioning"),
        "metro": s.get("metro"),
        "metroWalk": s.get("metroWalk") or s.get("metro_walk"),
        "is_demo": False,
        "data_origin": s.get("data_origin"),
        "source_graph": s.get("source_graph"),
        "badge_schedule": badge_schedule,
        "badge_photos": badge_photos,
        "as_of": s.get("as_of"),
        "lat": s.get("lat"),
        "lng": s.get("lng"),
        "companyGroupId": (developer or {}).get("groupId") if developer else (s.get("companyGroupId") or s.get("group_id")),
        "companyGroup": s.get("companyGroup") or s.get("company_group"),
    }


_BUILDING_DISPLAY = {
    "common": "Общие работы",
    "общие работы": "Общие работы",
    "без корпуса": "Без корпуса",
}


def display_building_name(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return "Без корпуса"
    key = " ".join(raw.lower().split())
    return _BUILDING_DISPLAY.get(key, raw)


def serialize_project_object(row: ProjectObject) -> dict[str, Any]:
    raw_name = row.name or ""
    shown = raw_name if (row.object_type or "") == "stage" else display_building_name(raw_name)
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "parent_id": str(row.parent_id) if row.parent_id is not None else None,
        "name": shown,
        "object_type": row.object_type or "building",
        "type": row.object_type or "building",
        "lat": row.lat,
        "lng": row.lng,
        "sort_order": row.sort_order or 0,
    }


def list_objects_from_table(db: Session, project_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(ProjectObject)
        .filter(ProjectObject.project_id == project_id)
        .order_by(ProjectObject.sort_order.asc(), ProjectObject.id.asc())
        .all()
    )
    return [serialize_project_object(r) for r in rows]


def create_project_object(db: Session, project_id: int, payload: dict[str, Any]) -> ProjectObject:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    parent_id = payload.get("parent_id")
    if parent_id is not None:
        parent = db.get(ProjectObject, int(parent_id))
        if not parent or parent.project_id != project_id:
            raise HTTPException(400, "parent_id invalid")
    row = ProjectObject(
        project_id=project_id,
        parent_id=int(parent_id) if parent_id is not None else None,
        name=name,
        object_type=str(payload.get("object_type") or payload.get("type") or "building"),
        lat=float(payload["lat"]) if payload.get("lat") is not None else None,
        lng=float(payload["lng"]) if payload.get("lng") is not None else None,
        sort_order=int(payload.get("sort_order") or 0),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_project_object(db: Session, project_id: int, oid: int) -> ProjectObject:
    row = db.get(ProjectObject, oid)
    if not row or row.project_id != project_id:
        raise HTTPException(404, "object not found")
    return row


def patch_project_object(db: Session, project_id: int, oid: int, payload: dict[str, Any]) -> ProjectObject:
    row = get_project_object(db, project_id, oid)
    if "name" in payload and payload["name"] is not None:
        name = str(payload["name"]).strip()
        if not name:
            raise HTTPException(400, "name required")
        row.name = name
    if "object_type" in payload or "type" in payload:
        row.object_type = str(payload.get("object_type") or payload.get("type") or row.object_type)
    if "parent_id" in payload:
        pid = payload.get("parent_id")
        if pid is None:
            row.parent_id = None
        else:
            parent = db.get(ProjectObject, int(pid))
            if not parent or parent.project_id != project_id or parent.id == row.id:
                raise HTTPException(400, "parent_id invalid")
            row.parent_id = parent.id
    if "lat" in payload:
        row.lat = float(payload["lat"]) if payload["lat"] is not None else None
    if "lng" in payload:
        row.lng = float(payload["lng"]) if payload["lng"] is not None else None
    if "sort_order" in payload and payload["sort_order"] is not None:
        row.sort_order = int(payload["sort_order"])
    db.commit()
    db.refresh(row)
    return row


def delete_project_object(db: Session, project_id: int, oid: int) -> dict[str, Any]:
    row = get_project_object(db, project_id, oid)
    children = db.query(ProjectObject).filter(ProjectObject.parent_id == row.id).count()
    if children:
        raise HTTPException(400, "object has children; delete or reparent first")
    db.delete(row)
    db.commit()
    return {"ok": True, "id": oid}


def parse_network_recovery(raw: str | None) -> Any | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def save_network_recovery(
    db: Session,
    project_id: int,
    version_id: int,
    payload: Any,
) -> dict[str, Any]:
    """Сохранить recovery JSON и применить confirmed/rejected к ScheduleDependency."""
    from app.db.models import ScheduleDependency, ScheduleItem, ScheduleVersion

    version = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.id == version_id, ScheduleVersion.project_id == project_id)
        .first()
    )
    if not version:
        raise HTTPException(404, "schedule version not found")

    body: dict[str, Any] | list | None
    if payload is None:
        body = None
    elif isinstance(payload, dict):
        body = payload
    elif isinstance(payload, list):
        body = {"proposed": payload}
    else:
        raise HTTPException(400, "network_recovery must be object or null")

    applied = 0
    removed = 0
    if isinstance(body, dict):
        proposed = body.get("proposed") or []
        if isinstance(proposed, list):
            items = {
                str(it.id): it
                for it in db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version.id).all()
            }
            existing = (
                db.query(ScheduleDependency)
                .filter(ScheduleDependency.schedule_version_id == version.id)
                .all()
            )
            by_pair = {(d.predecessor_item_id, d.successor_item_id): d for d in existing}

            for p in proposed:
                if not isinstance(p, dict):
                    continue
                status = str(p.get("status") or "").lower()
                pred_s = str(p.get("predecessor_activity_id") or "")
                succ_s = str(p.get("successor_activity_id") or "")
                if pred_s not in items or succ_s not in items:
                    continue
                pred_id = items[pred_s].id
                succ_id = items[succ_s].id
                pair = (pred_id, succ_id)
                rel = str(p.get("relation_type") or "FS").upper()
                if rel not in ("FS", "SS", "FF", "SF"):
                    rel = "FS"
                lag_days = int(p.get("lag_days") or 0)
                lag_min = lag_days * 60 * 24
                source = str(p.get("source") or "rule")

                if status == "confirmed":
                    row = by_pair.get(pair)
                    if row:
                        row.link_type = rel
                        row.lag_minutes = lag_min
                    else:
                        row = ScheduleDependency(
                            schedule_version_id=version.id,
                            predecessor_item_id=pred_id,
                            successor_item_id=succ_id,
                            link_type=rel,
                            lag_minutes=lag_min,
                            predecessor_uid=items[pred_s].external_id,
                            successor_uid=items[succ_s].external_id,
                        )
                        db.add(row)
                        by_pair[pair] = row
                    applied += 1
                elif status == "rejected":
                    row = by_pair.get(pair)
                    # Удалять только deps из proposals (или все помеченные proposed)
                    if row and (
                        source in ("rule", "user", "qwen")
                        or str(p.get("rule_id") or "").startswith("proposed")
                    ):
                        # Удалять пару при reject, если нет другого явного excel-dep
                        db.delete(row)
                        by_pair.pop(pair, None)
                        removed += 1

            version.revision = int(getattr(version, "revision", 1) or 1) + 1

    if body is None:
        version.network_recovery_json = None
    else:
        version.network_recovery_json = json.dumps(body, ensure_ascii=False)
    version.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(version)
    return {
        "ok": True,
        "project_id": str(project_id),
        "version_id": str(version.id),
        "network_recovery": parse_network_recovery(version.network_recovery_json),
        "applied_dependencies": applied,
        "removed_dependencies": removed,
        "revision": int(getattr(version, "revision", 1) or 1),
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
    }


def list_catalog(db: Session, catalog_key: str) -> dict[str, Any]:
    key = normalize_catalog_key(catalog_key)
    rows = (
        db.query(KbCatalogItem)
        .filter(KbCatalogItem.catalog_key == key)
        .order_by(KbCatalogItem.id.asc())
        .all()
    )
    revision = max((r.revision for r in rows), default=0)
    items = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json or "{}")
        except Exception:
            payload = {}
        items.append(
            {
                "id": r.external_id,
                "db_id": r.id,
                "external_id": r.external_id,
                "name": r.name,
                "group": r.group_name,
                "group_name": r.group_name,
                "payload": payload,
                "revision": r.revision,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return {"catalog_key": key, "revision": revision, "items": items}


def replace_catalog(db: Session, catalog_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = normalize_catalog_key(catalog_key)
    items = payload.get("items")
    if not isinstance(items, list):
        raise HTTPException(400, "items list required")
    existing = db.query(KbCatalogItem).filter(KbCatalogItem.catalog_key == key).all()
    next_rev = max((r.revision for r in existing), default=0) + 1
    db.query(KbCatalogItem).filter(KbCatalogItem.catalog_key == key).delete(synchronize_session=False)
    now = datetime.utcnow()
    for it in items:
        ext = str(it.get("external_id") or it.get("id") or "").strip()
        name = str(it.get("name") or "").strip()
        if not ext or not name:
            continue
        body = it.get("payload") if isinstance(it.get("payload"), dict) else {k: v for k, v in it.items() if k not in ("external_id", "id", "name", "group", "group_name", "payload")}
        db.add(
            KbCatalogItem(
                catalog_key=key,
                external_id=ext,
                name=name,
                group_name=it.get("group_name") or it.get("group"),
                payload_json=json.dumps(body or {}, ensure_ascii=False),
                revision=next_rev,
                updated_at=now,
            )
        )
    db.commit()
    return list_catalog(db, key)


def list_work_profiles(db: Session) -> dict[str, Any]:
    from app.services.product.catalog_bridge import to_admin_equipment

    rows = db.query(WorkEquipmentProfile).order_by(WorkEquipmentProfile.id.asc()).all()
    revision = max((r.revision for r in rows), default=0)
    items = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json or "{}")
        except Exception:
            payload = {}
        admin_eq = payload.get("admin_equipment_id") or to_admin_equipment(r.equipment_key)
        admin_wt = payload.get("admin_work_type_id") or r.work_type_key
        # Пропуск mirror-строк в nested UI (фронт собирает по workTypeId)
        if payload.get("mirrored_from"):
            continue
        items.append(
            {
                "id": r.id,
                "work_type_key": r.work_type_key,
                "workTypeId": admin_wt,
                "equipment_key": r.equipment_key,
                "equipmentId": admin_eq or r.equipment_key,
                "role": r.role,
                "min_qty": r.min_qty,
                "minQty": r.min_qty,
                "confirmed": bool(r.confirmed),
                "payload": payload,
                "revision": r.revision,
            }
        )
    return {"revision": revision, "items": items}


def replace_work_profiles(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.product.catalog_bridge import normalize_profile_keys_for_save, to_cv_equipment

    items = payload.get("items")
    if not isinstance(items, list):
        raise HTTPException(400, "items list required")
    existing = db.query(WorkEquipmentProfile).all()
    next_rev = max((r.revision for r in existing), default=0) + 1
    # Сохранить KB-строки, не тронутые admin в этом PUT, если merge —
    # Интерфейс Admin UI шлёт полный replace nested profiles; wipe+rewrite ок, затем re-bridge KB.
    db.query(WorkEquipmentProfile).delete(synchronize_session=False)

    def _add(wt: str, eq: str, role: str, min_qty: int, confirmed: bool, body: dict[str, Any]) -> None:
        if not wt or not eq:
            return
        role_n = role.lower() if role else "expected"
        if role_n not in ("required", "expected", "optional"):
            role_n = "expected"
        body = dict(body or {})
        body.setdefault("source", "admin")
        cv = to_cv_equipment(str(body.get("cv_code") or eq))
        if cv:
            body["cv_code"] = cv
            body["admin_equipment_id"] = eq if str(eq).startswith("eq-") else body.get("admin_equipment_id")
            eq_store = cv
        else:
            eq_store = eq
        body["admin_work_type_id"] = body.get("admin_work_type_id") or wt
        # Двойной индекс: всегда ключ пайплайна; если wt похож на LTC — также as-is
        db.add(
            WorkEquipmentProfile(
                work_type_key=wt,
                equipment_key=eq_store,
                role=role_n,
                min_qty=max(1, int(min_qty or 1)),
                confirmed=bool(confirmed),
                payload_json=json.dumps(body, ensure_ascii=False),
                revision=next_rev,
            )
        )
        # Если админ дал LTC/wt-* id, а в payload есть kb_work_code — mirror-строка для pipeline
        kb_code = body.get("kb_work_code") or body.get("kb_code")
        if kb_code and str(kb_code) != wt and eq_store:
            db.add(
                WorkEquipmentProfile(
                    work_type_key=str(kb_code),
                    equipment_key=eq_store,
                    role=role_n,
                    min_qty=max(1, int(min_qty or 1)),
                    confirmed=bool(confirmed),
                    payload_json=json.dumps({**body, "mirrored_from": wt, "source": "admin"}, ensure_ascii=False),
                    revision=next_rev,
                )
            )

    for it in items:
        if not isinstance(it, dict):
            continue
        it = normalize_profile_keys_for_save(it)
        nested = it.get("items")
        if isinstance(nested, list):
            wt = str(it.get("work_type_key") or it.get("workTypeId") or "").strip()
            confirmed = bool(it.get("confirmed", False))
            source = it.get("source") or "admin"
            kb_code = None
            if isinstance(it.get("payload"), dict):
                kb_code = it["payload"].get("kb_work_code") or it["payload"].get("kb_code")
            for link in nested:
                if not isinstance(link, dict):
                    continue
                eq = str(link.get("equipment_key") or link.get("equipmentId") or "").strip()
                link_body = {"source": source}
                if kb_code:
                    link_body["kb_work_code"] = kb_code
                if link.get("cv_code"):
                    link_body["cv_code"] = link.get("cv_code")
                _add(
                    wt,
                    eq,
                    str(link.get("role") or "expected"),
                    int(link.get("min_qty") if link.get("min_qty") is not None else link.get("minQty") or 1),
                    confirmed,
                    link_body,
                )
            continue
        wt = str(it.get("work_type_key") or it.get("workTypeId") or "").strip()
        eq = str(it.get("equipment_key") or it.get("equipmentId") or "").strip()
        body = it.get("payload") if isinstance(it.get("payload"), dict) else {}
        _add(
            wt,
            eq,
            str(it.get("role") or "expected"),
            int(it.get("min_qty") if it.get("min_qty") is not None else it.get("minQty") or 1),
            bool(it.get("confirmed", False)),
            body,
        )
    db.flush()
    # Повторно накатываем KB defaults на работы без админ-покрытия (админ-строки не трогаем)
    from app.services.product.catalog_bridge import ensure_catalog_bridge
    from app.services.knowledge_base.service import load_kb

    ensure_catalog_bridge(db, load_kb())
    db.commit()
    return list_work_profiles(db)


def ai_mapping_status() -> dict[str, Any]:
    """Проверить, настроен ли server-side mapping Ollama/Qwen."""
    base = (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("PLANSIGHT_OLLAMA_URL") or "").strip()
    model = (os.environ.get("OLLAMA_MODEL") or os.environ.get("PLANSIGHT_OLLAMA_MODEL") or "").strip()
    if not base:
        return {"available": False, "reason": "ollama not configured on server yet"}
    return {
        "available": True,
        "base_url": base,
        "model": model or None,
        "note": "endpoint reachability not probed; suggest remains stub until wired",
    }


def ai_mapping_suggest(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Подсказки canonical work types: Ollama если есть, иначе строковая эвристика по каталогу."""
    from sqlalchemy.orm import Session as _Session  # noqa: F401 — keep typing soft

    status = ai_mapping_status()
    body = payload or {}
    names = body.get("names") or []
    activities = body.get("activities") or []
    if not names and isinstance(activities, list):
        names = [a.get("name") if isinstance(a, dict) else str(a) for a in activities]
    catalog = body.get("catalog") or body.get("candidates") or []
    # Каталог из payload или пустой → heuristic вернёт unmatched
    catalog_rows: list[dict[str, Any]] = []
    if isinstance(catalog, list):
        for c in catalog:
            if isinstance(c, dict) and (c.get("name") or c.get("code")):
                catalog_rows.append(c)
            elif isinstance(c, str):
                catalog_rows.append({"name": c, "code": c})

    candidates: list[dict[str, Any]] = []
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        nlow = name.lower()
        best = None
        best_score = 0.0
        for c in catalog_rows:
            cname = str(c.get("name") or "").lower()
            ccode = str(c.get("code") or "").lower()
            score = 0.0
            if cname and cname == nlow:
                score = 1.0
            elif cname and (cname in nlow or nlow in cname):
                score = 0.72
            elif ccode and ccode in nlow:
                score = 0.55
            if score > best_score:
                best_score = score
                best = c
        if best and best_score >= 0.55:
            candidates.append(
                {
                    "name": name,
                    "canonical_work_code": best.get("code") or best.get("id"),
                    "canonical_work_name": best.get("name"),
                    "score": best_score,
                    "source": "heuristic",
                }
            )
        else:
            candidates.append(
                {
                    "name": name,
                    "canonical_work_code": None,
                    "canonical_work_name": None,
                    "score": 0,
                    "source": "unmapped",
                    "mapping_status": "UNMAPPED",
                }
            )

    # Опциональный probe Ollama: статус отметить, ответ всё равно heuristic
    note = "heuristic string match against provided catalog"
    if status.get("available"):
        note = "ollama configured — heuristic used; LLM chat gateway reserved for full prompt pass"

    return {
        "candidates": candidates,
        "fallback": True,
        "note": note,
        "status": status,
        "request_echo": {"names_count": len(names), "catalog_count": len(catalog_rows)},
    }


def list_evidence_thread(
    db: Session,
    project_id: int,
    activity_id: str,
    *,
    signal: str | None = None,
) -> list[dict[str, Any]]:
    q = (
        db.query(EvidenceComment)
        .filter(
            EvidenceComment.project_id == project_id,
            EvidenceComment.activity_key == str(activity_id),
        )
        .order_by(EvidenceComment.created_at.asc(), EvidenceComment.id.asc())
    )
    rows = q.all()
    # Параметр signal принимаем для parity API; фильтр по kind/signal — позже
    _ = (signal or "").upper()
    return [
        {
            "id": str(r.id),
            "author": r.author,
            "role": r.role or "",
            "initials": r.initials or "",
            "text": r.text,
            "at": r.created_at.isoformat() if r.created_at else datetime.utcnow().isoformat(),
            "kind": r.kind if r.kind in ("user", "pm", "system") else "user",
            "deviation_id": r.deviation_id,
            "activity_key": r.activity_key,
            "signal": signal,
        }
        for r in rows
    ]


def add_evidence_comment(
    db: Session,
    project_id: int,
    activity_id: str,
    payload: dict[str, Any],
    *,
    signal: str | None = None,
) -> list[dict[str, Any]]:
    text = str(payload.get("text") or "").strip()
    if not text:
        return list_evidence_thread(db, project_id, activity_id, signal=signal)
    author = str(payload.get("author") or "Оператор").strip()
    role = str(payload.get("role") or "Аналитик")
    initials = str(payload.get("initials") or "".join(w[0] for w in author.split()[:2]).upper() or "ОП")
    kind = str(payload.get("kind") or "user").lower()
    if kind not in ("user", "pm", "system"):
        kind = "user"
    deviation_id = payload.get("deviation_id")
    row = EvidenceComment(
        project_id=project_id,
        activity_key=str(activity_id),
        deviation_id=int(deviation_id) if deviation_id is not None else None,
        author=author,
        role=role,
        initials=initials[:16],
        text=text,
        kind=kind,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    return list_evidence_thread(db, project_id, activity_id, signal=signal)
