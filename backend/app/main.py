from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Camera,
    Detection,
    Deviation,
    Frame,
    InferenceRun,
    Project,
    ScheduleItem,
    WorkType,
    init_db,
)
from app.db import SessionLocal
from app.services.deviations.service import detect_deviations
from app.services.frames.service import ingest_frame
from app.services.knowledge_base.service import load_kb, sync_kb_to_db
from app.services.pipeline.service import process_frame
from app.services.reporting.service import (
    ensure_daily_summary,
    get_project_dashboard,
    get_work_evidence,
    list_activities,
    list_matches,
)
from app.services.schedule.service import get_active_schedule, list_schedule_items
from app.services.verification.service import queue_ambiguous, submit_verdict


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbDep = Annotated[Session, Depends(get_db)]

app = FastAPI(title="PlanSight", version="0.1.0")
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.get("api", "cors_origins", ["*"]) or ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.services.auth.rbac import rbac_middleware

app.middleware("http")(rbac_middleware)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        sync_kb_to_db(db)
        _sync_weights_sha256(db)
        db.commit()
    finally:
        db.close()


def _sync_weights_sha256(db: Session) -> None:
    """Заполнить ModelVersion.weights_sha256 из registry, если пусто (без разрушения)."""
    import json as _json
    from pathlib import Path as _Path

    from app.core.paths import REPO_ROOT
    from app.db.models import ModelVersion

    man = REPO_ROOT / "models" / "registry" / "yolo11s_combined_v1.json"
    if not man.exists():
        return
    try:
        data = _json.loads(man.read_text(encoding="utf-8"))
    except Exception:
        return
    sha = data.get("weights_sha256")
    if not sha:
        return
    for mv in db.query(ModelVersion).all():
        if not getattr(mv, "weights_sha256", None):
            mv.weights_sha256 = sha
        wp = getattr(mv, "weights_path", None) or ""
        if "yolo11s" in wp or not wp:
            mv.weights_sha256 = sha


@app.get("/health")
@app.get("/api/health")
def health():
    """Проверка liveness. Поля readiness аддитивны — клиент может их игнорировать."""
    from pathlib import Path

    from app.services.activity.activity_net import activity_net_status

    weights = None
    try:
        weights = get_settings().model_path()
    except Exception:
        weights = None
    weights_ok = bool(weights and Path(weights).exists())
    an = activity_net_status()
    return {
        "status": "ok",
        "engine": settings.get("engine", "version", "plansight-engine-v1"),
        "readiness": {
            "api": True,
            "yolo_weights_present": weights_ok,
            "activity_net": an.get("status"),
            "activity_production_engine": an.get("production_engine"),
        },
    }


@app.get("/api/projects")
def api_list_projects(db: DbDep, include_lab: bool = False):
    from app.services.product.slugs import is_visible_in_portfolio
    from app.services.product.v42_api import project_card, settings_of

    rows = db.query(Project).order_by(Project.id.asc()).all()
    out = []
    for p in rows:
        if not is_visible_in_portfolio(settings_of(p), include_lab=include_lab):
            continue
        out.append(project_card(p, db=db))
    return out


@app.get("/api/portfolio")
def api_portfolio(db: DbDep, as_of: str | None = None, include_lab: bool = False):
    """Портфель для frontend — без CV Lab в обычном режиме (V7.1)."""
    from app.services.product.portfolio import build_portfolio

    return build_portfolio(db, as_of=as_of, include_lab=include_lab)


@app.get("/api/projects/{project_id}/objects")
def api_project_objects(project_id: int, db: DbDep):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    from app.services.product.portfolio import list_project_objects

    return {"items": list_project_objects(db, project_id)}


@app.post("/api/projects/{project_id}/objects")
def api_create_project_object(project_id: int, payload: dict, db: DbDep):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.v42_api import create_project_object, serialize_project_object

    row = create_project_object(db, project_id, payload or {})
    return serialize_project_object(row)


@app.get("/api/projects/{project_id}/objects/{oid}")
def api_get_project_object(project_id: int, oid: int, db: DbDep):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.v42_api import get_project_object, serialize_project_object

    return serialize_project_object(get_project_object(db, project_id, oid))


@app.patch("/api/projects/{project_id}/objects/{oid}")
def api_patch_project_object(project_id: int, oid: int, payload: dict, db: DbDep):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.v42_api import patch_project_object, serialize_project_object

    return serialize_project_object(patch_project_object(db, project_id, oid, payload or {}))


@app.delete("/api/projects/{project_id}/objects/{oid}")
def api_delete_project_object(project_id: int, oid: int, db: DbDep):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.v42_api import delete_project_object

    return delete_project_object(db, project_id, oid)

@app.get("/api/projects/{project_id}/schedules/versions")
def api_schedule_versions_v2(project_id: int, db: DbDep):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    from app.services.product.portfolio import list_schedule_versions_v2

    return {"items": list_schedule_versions_v2(db, project_id)}


@app.get("/api/projects/{project_id}/schedules/workspace")
def api_schedule_workspace(
    project_id: int,
    db: DbDep,
    version: int | None = None,
    version_id: int | None = None,
    object_id: int | None = None,
    as_of: str | None = None,
):
    """Мост workspace под SchedulePage v2 (WBS/activities/deps)."""
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    from app.services.product.portfolio import build_schedule_workspace

    vid = version_id if version_id is not None else version
    return build_schedule_workspace(db, project_id, version_id=vid, object_id=object_id, as_of=as_of)


@app.post("/api/projects/{project_id}/schedules/{version_id}/fork")
def api_schedule_fork(project_id: int, version_id: int, db: DbDep):
    from app.services.schedule.editor import fork_working_copy

    return fork_working_copy(db, project_id, source_version_id=version_id)


@app.post("/api/projects/{project_id}/schedules/fork")
def api_schedule_fork_active(project_id: int, db: DbDep, payload: dict = None):  # type: ignore[assignment]
    from app.services.schedule.editor import fork_working_copy

    body = payload or {}
    src = body.get("source_version_id")
    return fork_working_copy(db, project_id, source_version_id=int(src) if src else None)


@app.post("/api/projects/{project_id}/schedules/{version_id}/recalculate")
def api_schedule_recalculate(project_id: int, version_id: int, payload: dict, db: DbDep):
    from app.services.schedule.editor import dry_run_recalculate

    return dry_run_recalculate(
        db,
        project_id,
        version_id,
        activities=list(payload.get("activities") or []),
        dependencies=list(payload.get("dependencies") or []),
    )


@app.get("/api/projects/{project_id}/schedules/{version_id}/schedule-quality")
def api_schedule_quality(project_id: int, version_id: int, db: DbDep):
    """V6 Sprint B — quality gate готовности сети / CPM."""
    from app.db.models import ScheduleDependency, ScheduleItem, ScheduleVersion
    from app.services.schedule.network import quality_report_from_db_items

    v = db.get(ScheduleVersion, version_id)
    if not v or v.project_id != project_id:
        raise HTTPException(404, "version not found")
    items = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version_id).all()
    deps = db.query(ScheduleDependency).filter(ScheduleDependency.schedule_version_id == version_id).all()
    report = quality_report_from_db_items(items, deps)
    report["project_id"] = str(project_id)
    report["version_id"] = str(version_id)
    return report


@app.post("/api/projects/{project_id}/schedules/{version_id}/calculate-preview")
def api_schedule_calculate_preview(project_id: int, version_id: int, payload: dict, db: DbDep):
    """V6 Sprint B — превью CPM (не сохраняет)."""
    from app.db.models import ScheduleDependency, ScheduleItem, ScheduleVersion
    from app.services.schedule.network import calculate_cpm, result_to_json

    v = db.get(ScheduleVersion, version_id)
    if not v or v.project_id != project_id:
        raise HTTPException(404, "version not found")
    body_acts = list(payload.get("activities") or [])
    body_deps = list(payload.get("dependencies") or [])
    if not body_acts:
        items = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version_id).all()
        body_acts = [
            {
                "id": str(it.id),
                "name": it.raw_name,
                "planned_start": it.planned_start.date().isoformat() if it.planned_start else None,
                "planned_end": it.planned_finish.date().isoformat() if it.planned_finish else None,
            }
            for it in items
        ]
        deps = db.query(ScheduleDependency).filter(ScheduleDependency.schedule_version_id == version_id).all()
        body_deps = [
            {
                "predecessor_activity_id": str(d.predecessor_item_id),
                "successor_activity_id": str(d.successor_item_id),
                "relation_type": d.link_type or "FS",
                "lag_days": int((d.lag_minutes or 0) // (24 * 60)),
            }
            for d in deps
        ]
    res = calculate_cpm(body_acts, body_deps)
    out = result_to_json(res)
    out["project_id"] = str(project_id)
    out["version_id"] = str(version_id)
    out["persisted"] = False
    return out


@app.post("/api/projects/{project_id}/scenarios")
def api_create_scenario(project_id: int, payload: dict, db: DbDep):
    """V6 Stage 4 — сохраняемый what-if; никогда не мутирует published КСГ."""
    from app.db.models import ScheduleDependency, ScheduleItem, ScheduleVersion
    from app.services.schedule.network import calculate_cpm, impact_delay_days, result_to_json
    from app.services.schedule.service import get_active_schedule

    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    version_id = payload.get("source_schedule_version") or payload.get("version_id")
    if version_id is not None:
        v = db.get(ScheduleVersion, int(version_id))
        if not v or v.project_id != project_id:
            raise HTTPException(404, "version not found")
    else:
        v = get_active_schedule(db, project_id)
        if not v:
            raise HTTPException(404, "no active schedule")
    items = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == v.id).all()
    deps = db.query(ScheduleDependency).filter(ScheduleDependency.schedule_version_id == v.id).all()
    acts = [
        {
            "id": str(it.id),
            "name": it.raw_name,
            "planned_start": it.planned_start.date().isoformat() if it.planned_start else None,
            "planned_end": it.planned_finish.date().isoformat() if it.planned_finish else None,
            "is_milestone": bool(getattr(it, "is_milestone", False)),
        }
        for it in items
    ]
    links = [
        {
            "predecessor_activity_id": str(d.predecessor_item_id),
            "successor_activity_id": str(d.successor_item_id),
            "relation_type": d.link_type or "FS",
            "lag_days": int((d.lag_minutes or 0) // (24 * 60)),
        }
        for d in deps
    ]
    status_date = payload.get("status_date")
    base = calculate_cpm(acts, links, status_date=status_date)
    template = str(payload.get("template") or "DELAY_ACTIVITY")
    # Шаблоны: DELAY_ACTIVITY | ABSORB_FLOAT | FINISH_SLIP
    assumptions = list(payload.get("assumptions") or [])
    assumptions.append("Не официальный график — только what-if preview")
    assumptions.append(f"Шаблон: {template}")
    if status_date:
        assumptions.append(f"status_date={status_date} — remaining относительно даты статуса")
    if payload.get("confirmed_finding_ids"):
        assumptions.append(f"Учтены confirmed findings: {payload.get('confirmed_finding_ids')}")
    if payload.get("resource_changes"):
        assumptions.append("resource_changes + precedence из сети (если переданы); не схема Строгино")
    if base.errors or not base.quality.get("forecast_available"):
        return {
            "scenario_id": None,
            "status": "FORECAST_UNAVAILABLE",
            "reason": base.errors or ["network_not_ready"],
            "baseline": result_to_json(base),
            "template": template,
            "assumptions": assumptions,
            "not_official_schedule": True,
            "published": False,
            "partial_network": bool(base.quality.get("partial_network")),
            "note": "Сценарий не считается официальным графиком; нет подтверждённой сети — влияние на срок недоступно",
            "message_ru": "Нет подтверждённой сети работ",
            "explain": {
                "verified": [],
                "assumed": assumptions,
                "driver_activity": None,
                "float_used": None,
            },
        }
    partial_network = bool(base.quality.get("partial_network"))
    if partial_network:
        assumptions.append(
            "Прогноз по связанному фрагменту сети; полное влияние на срок проекта не определяется"
        )
    overrides = dict(payload.get("remaining_duration_overrides") or {})
    activity_id = str(payload.get("activity_id") or next(iter(overrides), "") or "")
    extra = int(payload.get("extra_days") or overrides.get(activity_id) or 0)
    if template == "ABSORB_FLOAT" and activity_id and not extra:
        # Пробный +1 день — проверяем, поглощает ли резерв
        extra = 1
        assumptions.append("ABSORB_FLOAT: пробный +1 день")
    if template == "FINISH_SLIP" and activity_id and not extra:
        extra = 5
        assumptions.append("FINISH_SLIP: шаблон +5 дней")
    impact = impact_delay_days(base, activity_id, extra) if activity_id and extra else None
    act_name = next((a["name"] for a in acts if a["id"] == activity_id), activity_id)
    float_days = None
    if activity_id and activity_id in base.activities:
        float_days = getattr(base.activities[activity_id], "total_float", None)

    from app.services.schedule.resource_leveling import level_resources

    leveling = level_resources(
        resource_changes=payload.get("resource_changes"),
        capacities=payload.get("resource_capacities"),
        horizon_days=int(payload.get("horizon_days") or 60),
        links=links if payload.get("resource_changes") else None,
    )
    if leveling.get("resource_leveling") not in (None, "skipped"):
        assumptions.append(f"resource_leveling={leveling.get('engine')}")

    fragment_msg = (
        "Прогноз рассчитан по доступному связанному фрагменту сети. "
        "Полное влияние на срок проекта не определяется: график содержит неполную сеть зависимостей."
        if partial_network
        else None
    )
    # Срок всего проекта авторитетен только при VALIDATED_NETWORK
    finish_after = None if partial_network else (impact or {}).get("project_finish_after")
    finish_before = None if partial_network else (impact or {}).get("project_finish_before")
    finish_delta = None if partial_network else (impact or {}).get("project_finish_delta_days")
    explain = {
        "driver_activity": {"id": activity_id or None, "name": act_name},
        "float_used_days": float_days,
        "absorbed_by_float": bool(impact and impact.get("absorbed_by_float")),
        "verified": [
            "CPM forward/backward на рабочей копии сети",
            "Опубликованный график не изменён",
            f"quality_status={base.quality.get('quality_status')}",
        ],
        "assumed": assumptions,
        "resource_leveling": leveling.get("resource_leveling") or "not_run",
        "resource_feasible": leveling.get("feasible"),
        "validated_network": not partial_network,
        "partial_network": partial_network,
        "estimated_project_finish": finish_after
        or (None if partial_network else (base.project_finish.isoformat() if base.project_finish else None)),
    }
    out = {
        "scenario_id": f"scen-{project_id}-{v.id}-{template}-{activity_id or 'none'}-{extra}",
        "status": "PARTIAL_NETWORK_PREVIEW" if partial_network else "WHAT_IF_PREVIEW",
        "kind": "SCENARIO",
        "template": template,
        "not_official_schedule": True,
        "partial_network": partial_network,
        "message_ru": fragment_msg,
        "note": fragment_msg or "Сценарий не публикует график — только preview",
        "source_schedule_version": v.id,
        "status_date": status_date,
        "baseline": result_to_json(base),
        "impact": (
            {
                **(impact or {}),
                "project_finish_before": finish_before,
                "project_finish_after": finish_after,
                "project_finish_delta_days": finish_delta,
                "partial_network": partial_network,
                "affected_successors": len((impact or {}).get("critical_after") or []) if impact else 0,
            }
            if impact
            else None
        ),
        "assumptions": assumptions,
        "explain": explain,
        "resource_leveling": leveling,
        "diff": {
            "project_finish_before": finish_before,
            "project_finish_after": finish_after,
            "delta_days": finish_delta,
        },
        "published": False,
        "frozen_input": {
            "activity_id": activity_id or None,
            "extra_days": extra,
            "template": template,
            "status_date": status_date,
            "source_schedule_version": v.id,
            "quality_status": base.quality.get("quality_status"),
            "partial_network": partial_network,
        },
    }
    from app.db.models import ScenarioRun

    key = out["scenario_id"]
    row = db.query(ScenarioRun).filter(ScenarioRun.scenario_key == key).one_or_none()
    if row is None:
        row = ScenarioRun(
            project_id=project_id,
            scenario_key=key,
            source_schedule_version_id=v.id,
            status=out["status"],
            template=template,
            author=str(payload.get("author") or "operator"),
            input_json=json.dumps(payload, ensure_ascii=False, default=str),
            result_json=json.dumps(out, ensure_ascii=False, default=str),
            published=False,
        )
        db.add(row)
    else:
        row.result_json = json.dumps(out, ensure_ascii=False, default=str)
        row.status = out["status"]
        row.input_json = json.dumps(payload, ensure_ascii=False, default=str)
        row.published = False
    db.commit()
    out["persisted"] = True
    out["db_id"] = row.id
    return out


@app.get("/api/projects/{project_id}/scenarios")
def api_list_scenarios(project_id: int, db: DbDep, limit: int = 50):
    """Список сохранённых what-if сценариев проекта (сначала новые)."""
    from app.db.models import ScenarioRun

    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    lim = max(1, min(int(limit or 50), 200))
    rows = (
        db.query(ScenarioRun)
        .filter(ScenarioRun.project_id == project_id)
        .order_by(ScenarioRun.created_at.desc())
        .limit(lim)
        .all()
    )
    items = []
    for row in rows:
        try:
            result = json.loads(row.result_json or "{}")
        except Exception:
            result = {}
        diff = result.get("diff") or {}
        items.append(
            {
                "scenario_id": row.scenario_key,
                "status": row.status,
                "template": row.template,
                "published": bool(row.published),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "source_schedule_version": row.source_schedule_version_id,
                "delta_days": diff.get("delta_days"),
                "project_finish_after": diff.get("project_finish_after"),
            }
        )
    return {"project_id": str(project_id), "items": items, "count": len(items)}


@app.get("/api/projects/{project_id}/scenarios/{scenario_id}")
def api_get_scenario(project_id: int, scenario_id: str, db: DbDep):
    from app.db.models import ScenarioRun

    row = (
        db.query(ScenarioRun)
        .filter(ScenarioRun.project_id == project_id, ScenarioRun.scenario_key == scenario_id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(404, "scenario not found")
    try:
        result = json.loads(row.result_json or "{}")
    except Exception:
        result = {}
    return {
        "scenario_id": row.scenario_key,
        "project_id": str(project_id),
        "status": row.status,
        "template": row.template,
        "published": bool(row.published),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "input": json.loads(row.input_json or "{}"),
        "result": result,
        "frozen_input": result.get("frozen_input") or json.loads(row.input_json or "{}"),
        "assumptions": result.get("assumptions") or [],
        "note": "Сохранённый what-if; публикация в график — отдельное утверждение",
    }


@app.post("/api/projects/{project_id}/scenarios/compare")
def api_compare_scenarios(project_id: int, payload: dict, db: DbDep):
    """Сравнить два ScenarioRun по id — график не мутирует."""
    from app.db.models import ScenarioRun

    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    a_id = str(payload.get("scenario_a") or payload.get("a") or "")
    b_id = str(payload.get("scenario_b") or payload.get("b") or "")
    if not a_id or not b_id:
        raise HTTPException(400, "scenario_a and scenario_b required")

    def _load(key: str) -> dict:
        row = (
            db.query(ScenarioRun)
            .filter(ScenarioRun.project_id == project_id, ScenarioRun.scenario_key == key)
            .one_or_none()
        )
        if not row:
            raise HTTPException(404, f"scenario not found: {key}")
        try:
            result = json.loads(row.result_json or "{}")
        except Exception:
            result = {}
        return {
            "scenario_id": row.scenario_key,
            "status": row.status,
            "published": bool(row.published),
            "template": row.template,
            "diff": result.get("diff") or {},
            "assumptions": result.get("assumptions") or [],
            "frozen_input": result.get("frozen_input") or {},
            "explain": (result.get("explain") or {}),
        }

    a = _load(a_id)
    b = _load(b_id)
    da = a["diff"].get("delta_days")
    db_ = b["diff"].get("delta_days")
    finish_a = a["diff"].get("project_finish_after")
    finish_b = b["diff"].get("project_finish_after")
    delta_vs = None
    if isinstance(da, (int, float)) and isinstance(db_, (int, float)):
        delta_vs = db_ - da
    return {
        "project_id": str(project_id),
        "a": a,
        "b": b,
        "comparison": {
            "delta_days_a": da,
            "delta_days_b": db_,
            "delta_days_b_minus_a": delta_vs,
            "project_finish_after_a": finish_a,
            "project_finish_after_b": finish_b,
            "same_template": a.get("template") == b.get("template"),
            "both_published": bool(a.get("published") and b.get("published")),
        },
        "not_official_schedule": True,
        "note": "Сравнение записей what-if; КСГ не изменён",
    }


@app.post("/api/projects/{project_id}/scenarios/{scenario_id}/publish")
def api_publish_scenario(project_id: int, scenario_id: str, payload: dict, db: DbDep):
    """Только явное утверждение — published=true; график не мутирует."""
    from app.db.models import ScenarioRun

    body = payload or {}
    row = (
        db.query(ScenarioRun)
        .filter(ScenarioRun.project_id == project_id, ScenarioRun.scenario_key == scenario_id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(404, "scenario not found")
    if row.status == "FORECAST_UNAVAILABLE":
        raise HTTPException(400, "cannot publish FORECAST_UNAVAILABLE scenario")
    if not body.get("confirm"):
        raise HTTPException(400, "confirm=true required — публикация только явным утверждением")
    row.published = True
    row.status = "SCENARIO_APPROVED"
    try:
        result = json.loads(row.result_json or "{}")
    except Exception:
        result = {}
    result["published"] = True
    result["status"] = "SCENARIO_APPROVED"
    result["approved_by"] = str(body.get("author") or "operator")
    result["not_official_schedule"] = True
    result["note"] = (
        "Сценарий утверждён как запись what-if; рабочий/опубликованный КСГ не изменён. "
        "Перенос в версию графика — отдельный publish schedule."
    )
    row.result_json = json.dumps(result, ensure_ascii=False, default=str)
    db.commit()
    return {
        "scenario_id": row.scenario_key,
        "published": True,
        "status": row.status,
        "schedule_mutated": False,
        "message_ru": "Сценарий утверждён; график не изменён",
        "result": result,
    }


@app.patch("/api/projects/{project_id}/schedules/{version_id}")
def api_schedule_patch(project_id: int, version_id: int, payload: dict, db: DbDep):
    from app.services.schedule.editor import save_schedule_edits

    expected = payload.get("expected_revision")
    return save_schedule_edits(
        db,
        project_id,
        version_id=version_id,
        activities=list(payload.get("activities") or []),
        dependencies=list(payload.get("dependencies") or []),
        recalculate=bool(payload.get("recalculate", True)),
        expected_revision=int(expected) if expected is not None else None,
    )


@app.patch("/api/projects/{project_id}/schedules/{version_id}/network-recovery")
def api_schedule_network_recovery(project_id: int, version_id: int, payload: dict, db: DbDep):
    """Сохранить предложения network recovery в schedule_version.network_recovery_json."""
    from app.services.product.v42_api import save_network_recovery

    body = payload.get("network_recovery") if isinstance(payload.get("network_recovery"), dict) else payload
    return save_network_recovery(db, project_id, version_id, body)


@app.post("/api/projects/{project_id}/schedules/{version_id}/publish")
def api_schedule_publish(project_id: int, version_id: int, db: DbDep):
    from app.services.schedule.editor import publish_version

    return publish_version(db, project_id, version_id)


@app.get("/api/projects/{project_id}/schedules/export")
def api_schedule_export(
    project_id: int,
    db: DbDep,
    format: str = "xlsx",
    version: int | None = None,
):
    """Экспорт работ workspace в XLSX/CSV. CSV, если openpyxl нет."""
    import csv
    import io
    from fastapi.responses import Response
    from app.services.product.portfolio import build_schedule_workspace

    ws = build_schedule_workspace(db, project_id, version_id=version)
    acts = ws.get("activities") or []
    wbs_map = {n["id"]: n.get("name") for n in (ws.get("wbs") or [])}
    rows = []
    for a in acts:
        rows.append(
            {
                "Код": a.get("code") or "",
                "WBS": wbs_map.get(a.get("wbs_node_id") or "", ""),
                "Наименование": a.get("name") or "",
                "Ед. изм.": a.get("unit") or "",
                "Объем": a.get("planned_quantity") if a.get("planned_quantity") is not None else "",
                "План %": a.get("planned_progress") if a.get("planned_progress") is not None else "",
                "Факт %": a.get("actual_progress") if a.get("actual_progress") is not None else "",
                "План. начало": a.get("planned_start") or "",
                "План. окончание": a.get("planned_end") or "",
                "Факт. начало": a.get("actual_start") or "",
                "Прогноз": a.get("forecast_end") or "",
            }
        )
    ver = (ws.get("active_version") or {}).get("version") or "x"
    fname = f"project_{project_id}_schedule_v{ver}"

    def _csv_response() -> Response:
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(rows)
        data = ("\ufeff" + buf.getvalue()).encode("utf-8")
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
        )

    if format.lower() == "csv":
        return _csv_response()
    try:
        from openpyxl import Workbook
    except ImportError:
        # Лучше отдать CSV, чем 501 — клиент просил xlsx, но CSV допустим
        return _csv_response()
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Schedule"
    headers = list(rows[0].keys()) if rows else ["Наименование"]
    sheet.append(headers)
    for r in rows:
        sheet.append([r.get(h, "") for h in headers])
    out = io.BytesIO()
    wb.save(out)
    return Response(
        content=out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
    )


@app.post("/api/projects")
def api_create_project(payload: dict, db: DbDep):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    p = Project(name=name, timezone=str(payload.get("timezone") or "Europe/Moscow"))
    db.add(p)
    db.flush()
    cam_name = str(payload.get("camera_name") or "Camera-1")
    cam = Camera(
        project_id=p.id,
        name=cam_name,
        building_hint=payload.get("building_hint"),
    )
    db.add(cam)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "name": p.name, "camera_id": cam.id}


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: int, db: DbDep):
    from app.services.product.v42_api import project_card

    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    cameras = db.query(Camera).filter(Camera.project_id == project_id).all()
    out = project_card(p)
    out["cameras"] = [
        {
            "id": c.id,
            "name": c.name,
            "enabled": c.enabled,
            "building_hint": c.building_hint,
            "expected_interval_sec": c.expected_interval_sec,
        }
        for c in cameras
    ]
    out["dashboard"] = get_project_dashboard(db, project_id)
    return out


@app.patch("/api/projects/{project_id}/cameras/{camera_id}")
def api_patch_camera(project_id: int, camera_id: int, payload: dict, db: DbDep):
    cam = db.get(Camera, camera_id)
    if not cam or cam.project_id != project_id:
        raise HTTPException(404, "camera not found")
    if "building_hint" in payload:
        cam.building_hint = payload.get("building_hint") or None
    if "expected_interval_sec" in payload and payload["expected_interval_sec"] is not None:
        cam.expected_interval_sec = int(payload["expected_interval_sec"])
    if "name" in payload and payload["name"]:
        cam.name = str(payload["name"])
    if "enabled" in payload:
        cam.enabled = bool(payload["enabled"])
    # зеркало в CameraZoneBinding WHOLE_FRAME
    if "building_hint" in payload and cam.building_hint:
        from app.db.models import CameraZoneBinding

        bind = (
            db.query(CameraZoneBinding)
            .filter(
                CameraZoneBinding.camera_id == cam.id,
                CameraZoneBinding.visual_zone_key == "WHOLE_FRAME",
            )
            .order_by(CameraZoneBinding.id.desc())
            .first()
        )
        if bind is None:
            db.add(
                CameraZoneBinding(
                    project_id=project_id,
                    camera_id=cam.id,
                    visual_zone_key="WHOLE_FRAME",
                    building=cam.building_hint,
                    notes="from camera.building_hint",
                )
            )
        else:
            bind.building = cam.building_hint
    db.commit()
    db.refresh(cam)
    return {
        "id": cam.id,
        "name": cam.name,
        "building_hint": cam.building_hint,
        "expected_interval_sec": cam.expected_interval_sec,
        "enabled": cam.enabled,
    }


@app.post("/api/projects/{project_id}/camera-bindings")
def api_camera_binding(project_id: int, payload: dict, db: DbDep):
    from app.db.models import CameraZoneBinding

    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    camera_id = int(payload.get("camera_id") or 0)
    cam = db.get(Camera, camera_id)
    if not cam or cam.project_id != project_id:
        raise HTTPException(400, "camera_id invalid")
    building = str(payload.get("building") or "").strip()
    if not building:
        raise HTTPException(400, "building required")
    zone = str(payload.get("visual_zone_key") or "WHOLE_FRAME")
    row = CameraZoneBinding(
        project_id=project_id,
        camera_id=camera_id,
        visual_zone_key=zone,
        building=building,
        workface=payload.get("workface"),
        notes=payload.get("notes"),
        created_by=str(payload.get("user") or "operator"),
    )
    db.add(row)
    cam.building_hint = building
    db.commit()
    db.refresh(row)
    return {"id": row.id, "camera_id": camera_id, "building": building, "visual_zone_key": zone}


@app.get("/api/projects/{project_id}/autonomy")
def api_autonomy_status(project_id: int, db: DbDep):
    """Статус автономной настройки зон/привязок (без участия оператора)."""
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.zones.auto import auto_ensure_project, collect_schedule_buildings
    from app.services.zones.service import list_active_zones, zones_payload

    buildings = collect_schedule_buildings(db, project_id)
    cams = db.query(Camera).filter(Camera.project_id == project_id).all()
    per_cam = []
    for c in cams:
        zs = list_active_zones(db, c.id)
        per_cam.append(
            {
                "camera_id": c.id,
                "name": c.name,
                "building_hint": c.building_hint,
                "zones": zones_payload(zs, db),
                "auto_zone_count": sum(1 for z in zs if (z.created_by or "") == "auto"),
            }
        )
    return {
        "mode": "autonomous_default",
        "principle": "оператор не обязателен; ручные зоны (notes=manual*) сохраняются как override",
        "buildings_from_schedule": buildings,
        "cameras": per_cam,
    }


@app.post("/api/projects/{project_id}/autonomy/ensure")
def api_autonomy_ensure(project_id: int, db: DbDep):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.zones.auto import auto_ensure_project

    result = auto_ensure_project(db, project_id)
    db.commit()
    return result


@app.get("/api/projects/{project_id}/cameras/{camera_id}/zones")
def api_list_zones(project_id: int, camera_id: int, db: DbDep):
    from app.services.zones.service import list_active_zones, zones_payload

    cam = db.get(Camera, camera_id)
    if not cam or cam.project_id != project_id:
        raise HTTPException(404, "camera not found")
    return {"camera_id": camera_id, "zones": zones_payload(list_active_zones(db, camera_id), db)}


@app.post("/api/projects/{project_id}/zones/{zone_id}/verify")
def api_verify_zone(project_id: int, zone_id: int, payload: dict, db: DbDep):
    """Подтвердить или переназначить ROI↔корпус (human_verified)."""
    from app.db.models import CameraVisualZone, CameraZoneBinding

    z = db.get(CameraVisualZone, zone_id)
    if not z or z.project_id != project_id:
        raise HTTPException(404, "zone not found")
    building = str(payload.get("building") or "").strip()
    if not building:
        raise HTTPException(400, "building required")
    z.zone_status = "VERIFIED"
    note_bit = f" | verified→{building}"
    z.notes = ((z.notes or "") + note_bit)[-500:]
    existing = (
        db.query(CameraZoneBinding)
        .filter(
            CameraZoneBinding.project_id == project_id,
            CameraZoneBinding.camera_id == z.camera_id,
            CameraZoneBinding.visual_zone_key == z.zone_key,
        )
        .order_by(CameraZoneBinding.id.desc())
        .first()
    )
    if existing is not None:
        existing.building = building
        existing.visual_zone_id = z.id
        existing.notes = "human verified (rebind)"
        existing.created_by = str(payload.get("user") or "operator")
        existing.binding_source = "human_verified"
        existing.binding_status = "VERIFIED"
    else:
        db.add(
            CameraZoneBinding(
                project_id=project_id,
                camera_id=z.camera_id,
                visual_zone_key=z.zone_key,
                visual_zone_id=z.id,
                building=building,
                notes="human verified",
                created_by=str(payload.get("user") or "operator"),
                binding_source="human_verified",
                binding_status="VERIFIED",
            )
        )
    db.commit()
    from app.services.zones.service import zones_payload

    return zones_payload([z], db)[0]


@app.post("/api/projects/{project_id}/cameras/{camera_id}/zones")
def api_upsert_zone(project_id: int, camera_id: int, payload: dict, db: DbDep):
    from app.services.zones.service import upsert_zone, zones_payload

    cam = db.get(Camera, camera_id)
    if not cam or cam.project_id != project_id:
        raise HTTPException(404, "camera not found")
    name = str(payload.get("name") or "").strip()
    zone_key = str(payload.get("zone_key") or "").strip()
    polygon = payload.get("polygon_norm") or payload.get("polygon") or []
    if not name or not zone_key or len(polygon) < 3:
        raise HTTPException(400, "name, zone_key и polygon_norm (≥3 точек) обязательны")
    row = upsert_zone(
        db,
        project_id=project_id,
        camera_id=camera_id,
        name=name,
        zone_key=zone_key,
        polygon=polygon,
        building=payload.get("building"),
        user=str(payload.get("user") or "operator"),
    )
    row.notes = "manual " + (payload.get("notes") or "operator override")
    row.created_by = "operator"
    if payload.get("building"):
        cam.building_hint = cam.building_hint or str(payload["building"])
    db.commit()
    return zones_payload([row], db)[0]


@app.post("/api/projects/{project_id}/cameras/{camera_id}/zones/demo-k1-k2")
def api_demo_zones_k1_k2(project_id: int, camera_id: int, db: DbDep):
    """Быстрый setup демо: левая половина кадра = К1, правая = К2."""
    from app.services.zones.service import list_active_zones, upsert_zone, zones_payload

    cam = db.get(Camera, camera_id)
    if not cam or cam.project_id != project_id:
        raise HTTPException(404, "camera not found")
    # убрать авто-предложения, чтобы не дублировать VERIFIED K1/K2
    for z in list_active_zones(db, camera_id):
        if (z.created_by or "") == "auto" or (z.geometry_source or "") in ("auto_strips", "auto_activity_cluster"):
            if z.zone_key not in ("K1", "K2"):
                z.status = "archived"
    z1 = upsert_zone(
        db,
        project_id=project_id,
        camera_id=camera_id,
        name="К1-КОТЛОВАН",
        zone_key="K1",
        polygon=[[0.0, 0.0], [0.48, 0.0], [0.48, 1.0], [0.0, 1.0]],
        building="К1",
        user="operator",
        zone_status="VERIFIED",
        binding_status="VERIFIED",
        binding_source="human_verified",
    )
    z1.notes = "manual demo halves"
    z1.created_by = "operator"
    z1.zone_status = "VERIFIED"
    z2 = upsert_zone(
        db,
        project_id=project_id,
        camera_id=camera_id,
        name="К2-КОТЛОВАН",
        zone_key="K2",
        polygon=[[0.52, 0.0], [1.0, 0.0], [1.0, 1.0], [0.52, 1.0]],
        building="К2",
        user="operator",
        zone_status="VERIFIED",
        binding_status="VERIFIED",
        binding_source="human_verified",
    )
    z2.notes = "manual demo halves"
    z2.created_by = "operator"
    z2.zone_status = "VERIFIED"
    db.commit()
    return {"zones": zones_payload(list_active_zones(db, camera_id), db), "locked": "manual"}


@app.get("/api/projects/{project_id}/cameras")
def api_list_cameras(project_id: int, db: DbDep):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    cameras = db.query(Camera).filter(Camera.project_id == project_id).order_by(Camera.id.asc()).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "building_hint": c.building_hint,
            "expected_interval_sec": c.expected_interval_sec,
            "enabled": getattr(c, "enabled", True),
        }
        for c in cameras
    ]


@app.post("/api/projects/{project_id}/cameras")
def api_add_camera(project_id: int, payload: dict, db: DbDep):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    cam = Camera(
        project_id=project_id,
        name=str(payload.get("name") or "Camera"),
        building_hint=payload.get("building_hint"),
        expected_interval_sec=int(payload.get("expected_interval_sec") or 300),
    )
    db.add(cam)
    db.flush()
    from app.services.zones.auto import auto_ensure_zones

    auto = auto_ensure_zones(db, project_id=project_id, camera_id=cam.id)
    db.commit()
    db.refresh(cam)
    return {
        "id": cam.id,
        "name": cam.name,
        "building_hint": cam.building_hint,
        "autonomy": auto,
    }


@app.post("/api/projects/{project_id}/rebuild")
def api_rebuild(project_id: int, db: DbDep, payload: dict | None = None):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.pipeline.rebuild import rebuild_project

    payload = payload or {}
    start = datetime.fromisoformat(payload["start"]) if payload.get("start") else None
    end = datetime.fromisoformat(payload["end"]) if payload.get("end") else None
    cam = int(payload["camera_id"]) if payload.get("camera_id") else None
    try:
        result = rebuild_project(db, project_id, camera_id=cam, start=start, end=end)
        if result.get("ok"):
            db.commit()
        else:
            db.rollback()
        return result
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": str(exc), "rolled_back": True}


@app.get("/api/ops/latency")
def api_ops_latency():
    """V6 Sprint F — выборки P50/P95 по стадиям (in-process)."""
    from app.services.jobs.queue import latency_summary

    return {"stages": latency_summary()}


@app.get("/api/ops/jobs/{job_id}")
def api_ops_job(job_id: str):
    from app.services.jobs.queue import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "result": job.result,
        "timings_ms": job.timings_ms,
        "mode": getattr(job, "mode", "sync"),
    }


@app.post("/api/ops/jobs")
def api_ops_jobs_submit(payload: dict):
    """Поставить ping/demo job. async=true — фоновый поток; иначе sync."""
    from app.services.jobs.queue import get_job, submit_job, submit_job_async

    kind = str(payload.get("kind") or "ping")
    async_mode = bool(payload.get("async"))

    def _fn() -> dict:
        return {"ok": True, "kind": kind, "echo": payload.get("echo")}

    if kind not in ("ping", "demo_latency"):
        raise HTTPException(400, "only ping|demo_latency allowed without worker hooks")
    job = submit_job_async(kind, _fn) if async_mode else submit_job(kind, _fn)
    # Для async статус уже может быть RUNNING/COMPLETED
    fresh = get_job(job.id) or job
    return {
        "id": fresh.id,
        "kind": fresh.kind,
        "status": fresh.status,
        "mode": fresh.mode,
        "created_at": fresh.created_at,
        "finished_at": fresh.finished_at,
        "result": fresh.result,
        "note": "result durable in job_run; in-flight QUEUED may be lost on hard kill",
    }


@app.post("/api/ops/backup")
def api_ops_backup(payload: dict | None = None):
    """Снимок SQLite в data/backups. При RBAC — только admin."""
    import shutil
    from datetime import datetime as _dt
    from pathlib import Path

    body = payload or {}
    src = get_settings().database_path()
    if not Path(src).exists():
        raise HTTPException(404, "database not found")
    out_dir = Path(body["out"]) if body.get("out") else Path(src).parent / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = out_dir / f"plansight_{stamp}.db"
    shutil.copy2(src, dest)
    return {
        "ok": True,
        "path": str(dest),
        "bytes": dest.stat().st_size,
        "note": "SQLite file copy; restore only via scripts/backup_restore.py --allow-destructive-restore",
    }


@app.get("/api/models/activity-net")
def api_activity_net_status():
    from app.services.activity.activity_net import activity_net_status, ensure_registry_stub

    ensure_registry_stub()
    return activity_net_status()


@app.get("/api/models/yolo-eval")
def api_yolo_eval_status():
    """Честный статус eval YOLO — не выдумывать AP50 из фикстур."""
    import json
    from pathlib import Path

    from app.core.paths import REPO_ROOT

    man = REPO_ROOT / "models" / "registry" / "yolo11s_combined_v1.json"
    ev = REPO_ROOT / "models" / "registry" / "yolo11s_combined_v1_eval.json"
    out: dict = {"model_id": "yolo11s_combined_v1", "status": "UNKNOWN"}
    if man.exists():
        try:
            out.update(json.loads(man.read_text(encoding="utf-8")))
        except Exception:
            pass
    if ev.exists():
        try:
            evj = json.loads(ev.read_text(encoding="utf-8"))
            out["eval_artifact"] = evj
            out["status"] = evj.get("status") or out.get("eval", {}).get("status")
        except Exception:
            pass
    # Если ap50 == precision на фикстуре — обнуляем в ответе
    eval_block = out.get("eval") or {}
    if eval_block.get("status") in ("FIXTURE_SELF_CHECK", "EVALUATED_FIXTURE") or out.get("status") == "FIXTURE_SELF_CHECK":
        out["publishable_as_yolo_metrics"] = False
        out["note"] = "Fixture self-check only — not detector AP50/Precision for production claims"
    return out


@app.post("/api/explain")
def api_explain(payload: dict):
    """Структурированное объяснение — Qwen если настроен, иначе шаблон."""
    from app.services.llm.qwen_explain import explain_structured

    return explain_structured(payload or {})


@app.post("/api/projects/{project_id}/schedule")
async def api_import_schedule(
    project_id: int,
    db: DbDep,
    file: UploadFile = File(...),
    kind: str = Form("CURRENT"),
    overrides: str | None = Form(None),
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    content = await file.read()
    filename = file.filename or "schedule.csv"
    lower = filename.lower()
    wt = {w.id: w for w in db.query(WorkType).all()}
    override_list: list[dict] = []
    if overrides:
        try:
            parsed = json.loads(overrides)
            if isinstance(parsed, list):
                override_list = [x for x in parsed if isinstance(x, dict)]
        except Exception:
            override_list = []

    from app.services.zones.auto import auto_ensure_project
    from app.services.product.portfolio import resolve_schedule_item_objects, build_schedule_workspace

    if lower.endswith(".xml"):
        from app.services.schedule.import_mspdi import import_mspdi_xml

        version, stats = import_mspdi_xml(
            db, project_id, content, filename, kind=(kind or "CURRENT").upper(), activate=True
        )
        autonomy = auto_ensure_project(db, project_id)
        _apply_mapping_overrides(db, version.id, override_list, wt)
        resolve_schedule_item_objects(db, project_id, version.id)
        db.commit()
        ws = build_schedule_workspace(db, project_id, version_id=version.id)
        items = list_schedule_items(db, project_id)
        return _import_result_payload(version, filename, "mspdi", autonomy, items, wt, ws, stats=stats)

    from app.services.schedule.service import import_schedule

    try:
        version = import_schedule(db, project_id, content, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    autonomy = auto_ensure_project(db, project_id)
    _apply_mapping_overrides(db, version.id, override_list, wt)
    resolve_schedule_item_objects(db, project_id, version.id)
    db.commit()
    ws = build_schedule_workspace(db, project_id, version_id=version.id)
    items = list_schedule_items(db, project_id)
    return _import_result_payload(version, filename, "csv_xlsx", autonomy, items, wt, ws)


@app.post("/api/projects/{project_id}/schedule/preview")
async def api_import_schedule_preview(
    project_id: int,
    db: DbDep,
    file: UploadFile = File(...),
):
    """Серверное превью импорта (sniff колонок + sample rows) для HTTP-режима."""
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    content = await file.read()
    filename = file.filename or "schedule.csv"
    lower = filename.lower()
    import csv
    import io

    rows: list[dict[str, Any]] = []
    headers: list[str] = []
    if lower.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError as exc:
            raise HTTPException(501, "openpyxl required for xlsx preview") from exc
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = wb.active
        raw = list(sheet.iter_rows(values_only=True))
        if not raw:
            return {"filename": filename, "headers": [], "rows": [], "row_count": 0, "suggested_mapping": {}}
        headers = [str(h or f"col{i}") for i, h in enumerate(raw[0])]
        for r in raw[1:51]:
            rows.append({headers[i]: ("" if r[i] is None else r[i]) for i in range(len(headers))})
    else:
        text = content.decode("utf-8-sig", errors="replace")
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except Exception:
            dialect = csv.excel
            dialect.delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        headers = list(reader.fieldnames or [])
        for i, row in enumerate(reader):
            if i >= 50:
                break
            rows.append(dict(row))

    suggested: dict[str, str] = {}
    hlow = {h: h.lower() for h in headers}
    for h, low in hlow.items():
        if any(k in low for k in ("наимен", "name", "работ")) and "name" not in suggested.values():
            suggested["name"] = h
        elif any(k in low for k in ("код", "code", "wbs")) and "code" not in suggested.values():
            suggested["code"] = h
        elif any(k in low for k in ("начал", "start")) and "start" not in suggested.values():
            suggested["start"] = h
        elif any(k in low for k in ("оконч", "finish", "end")) and "end" not in suggested.values():
            suggested["end"] = h
        elif any(k in low for k in ("корпус", "building", "объект")) and "building" not in suggested.values():
            suggested["building"] = h
    return {
        "filename": filename,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "suggested_mapping": suggested,
        "note": "preview only — import via POST /schedule",
    }


def _apply_mapping_overrides(db: Session, version_id: int, overrides: list[dict], wt_by_id: dict) -> None:
    if not overrides:
        return
    code_to_wt = {w.code.lower(): w for w in wt_by_id.values()}
    items = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version_id).all()
    by_ext = {str(i.external_id): i for i in items}
    by_id = {str(i.id): i for i in items}
    for ov in overrides:
        key = str(ov.get("activity_id") or ov.get("external_id") or ov.get("id") or "")
        it = by_id.get(key) or by_ext.get(key)
        if not it:
            continue
        code = ov.get("canonical_work_code") or ov.get("work_type_code") or ov.get("code")
        name = ov.get("canonical_work_name") or ov.get("work_type_name") or ov.get("name")
        if code:
            it.canonical_work_code = str(code)
            wt = code_to_wt.get(str(code).lower())
            if wt:
                it.work_type_id = wt.id
        if name:
            it.canonical_work_name = str(name)
        status = ov.get("mapping_status")
        if status:
            it.mapping_status = str(status)
        elif code or name:
            it.mapping_status = "MAPPED"


def _import_result_payload(version, filename, fmt, autonomy, items, wt, ws, stats=None):
    stats = stats or {}
    missing = stats.get("missing_data") or {}
    return {
        "schedule_version_id": version.id,
        "id": str(version.id),
        "version": version.id,
        "checksum": version.checksum,
        "format": fmt,
        "stats": stats,
        "missing_data": missing,
        "autonomy": autonomy,
        "is_active": bool(version.is_active),
        "version_state": getattr(version, "version_state", None) or "IMPORTED",
        "source_filename": filename,
        "uploaded_at": version.imported_at.isoformat() if version.imported_at else None,
        "row_count": len(items),
        "warning_count": int(stats.get("warning_count") or 0),
        "network_recovery": ws.get("network_recovery"),
        "items": [
            {
                "id": i.id,
                "external_id": i.external_id,
                "work_name": i.raw_name,
                "work_type": wt[i.work_type_id].code if i.work_type_id in wt else None,
                "observability_mode": getattr(i, "observability_mode", None),
                "planned_start": i.planned_start.isoformat(),
                "planned_finish": i.planned_finish.isoformat(),
                "building": i.building,
                "project_object_id": getattr(i, "project_object_id", None),
            }
            for i in items
        ],
    }


@app.post("/api/projects/{project_id}/estimate-staging")
async def api_estimate_staging(project_id: int, db: DbDep, file: UploadFile = File(...)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.core.config import get_settings
    from app.services.knowledge_base.import_estimate import import_estimate_xlsx

    content = await file.read()
    dest = get_settings().uploads_dir() / "estimates" / (file.filename or "estimate.xlsx")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    stats = import_estimate_xlsx(db, dest)
    db.commit()
    return stats


@app.get("/api/projects/{project_id}/schedule")
def api_get_schedule(project_id: int, db: DbDep, kind: str | None = None):
    from app.db.models import ScheduleVersion

    versions = (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == project_id)
        .order_by(ScheduleVersion.id.desc())
        .all()
    )
    version = get_active_schedule(db, project_id)
    if kind:
        picked = next((v for v in versions if v.kind == kind.upper()), None)
        if picked:
            version = picked
    items = []
    if version:
        q = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version.id)
        items = q.order_by(ScheduleItem.planned_start.asc()).all()
        items = [i for i in items if not i.is_summary and not i.is_milestone]
    wt = {w.id: w for w in db.query(WorkType).all()}
    obs: dict[str, int] = {}
    mapped = 0
    for i in items:
        mode = getattr(i, "observability_mode", None) or "UNKNOWN"
        obs[mode] = obs.get(mode, 0) + 1
        if i.work_type_id:
            mapped += 1
    return {
        "schedule_version_id": version.id if version else None,
        "checksum": version.checksum if version else None,
        "kind": version.kind if version else None,
        "coverage": {
            "leaf": len(items),
            "mapped_work_type": mapped,
            "observability": obs,
        },
        "versions": [
            {
                "id": v.id,
                "kind": v.kind,
                "is_active": v.is_active,
                "checksum": v.checksum[:12],
                "imported_at": v.imported_at.isoformat() if v.imported_at else None,
            }
            for v in versions
        ],
        "items": [
            {
                "id": i.id,
                "external_id": i.external_id,
                "work_name": i.raw_name,
                "work_type": wt[i.work_type_id].code if i.work_type_id in wt else None,
                "work_type_id": i.work_type_id,
                "observability_mode": getattr(i, "observability_mode", None),
                "observability_reason": getattr(i, "observability_reason", None),
                "is_milestone": getattr(i, "is_milestone", False),
                "planned_start": i.planned_start.isoformat(),
                "planned_finish": i.planned_finish.isoformat(),
                "building": i.building,
                "workface": i.workface,
                "floor": i.floor,
                "wbs": getattr(i, "wbs", None),
            }
            for i in items
        ],
    }


@app.get("/api/projects/{project_id}/schedule/compare")
def api_schedule_compare(project_id: int, db: DbDep):
    """Сравнение baseline vs current по WBS+имени (UID не джойнятся)."""
    from app.db.models import ScheduleVersion

    versions = db.query(ScheduleVersion).filter(ScheduleVersion.project_id == project_id).all()
    base = next((v for v in versions if v.kind == "BASELINE"), None)
    cur = next((v for v in versions if v.kind == "CURRENT" and v.is_active), None)
    if cur is None:
        cur = next((v for v in versions if v.kind == "CURRENT"), None)
    if not base or not cur:
        return {"ok": False, "reason": "нужны версии BASELINE и CURRENT", "diffs": []}

    def load(vid: int) -> dict[str, ScheduleItem]:
        rows = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == vid).all()
        out = {}
        for r in rows:
            if r.is_summary or r.is_milestone:
                continue
            key = f"{(r.wbs or '').strip()}|{(r.raw_name or '').strip().lower()}"
            out[key] = r
        return out

    bmap, cmap = load(base.id), load(cur.id)
    diffs = []
    for key in sorted(set(bmap) | set(cmap)):
        b, c = bmap.get(key), cmap.get(key)
        if b and c:
            if b.planned_start != c.planned_start or b.planned_finish != c.planned_finish:
                diffs.append(
                    {
                        "key": key,
                        "name": c.raw_name,
                        "change": "dates",
                        "baseline": [b.planned_start.isoformat(), b.planned_finish.isoformat()],
                        "current": [c.planned_start.isoformat(), c.planned_finish.isoformat()],
                    }
                )
        elif b and not c:
            diffs.append({"key": key, "name": b.raw_name, "change": "removed_in_current"})
        else:
            diffs.append({"key": key, "name": c.raw_name, "change": "added_in_current"})
    return {
        "ok": True,
        "baseline_version_id": base.id,
        "current_version_id": cur.id,
        "diff_count": len(diffs),
        "diffs": diffs[:200],
    }


@app.post("/api/projects/{project_id}/frames")
async def api_upload_frame(
    project_id: int,
    db: DbDep,
    file: UploadFile = File(...),
    camera_id: int = Form(...),
    captured_at: str = Form(...),
    process: bool = Form(True),
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    cam = db.get(Camera, camera_id)
    if cam is None or cam.project_id != project_id:
        raise HTTPException(400, "invalid camera_id")
    content = await file.read()
    frame = ingest_frame(
        db,
        project_id=project_id,
        camera_id=camera_id,
        content=content,
        filename=file.filename or "frame.jpg",
        captured_at_raw=captured_at,
    )
    db.commit()
    db.refresh(frame)

    result = {
        "frame_id": frame.id,
        "sha256": frame.sha256,
        "ingest_status": frame.ingest_status,
        "image_quality": frame.image_quality,
        "captured_at": frame.captured_at.isoformat() if frame.captured_at else None,
        "image_url": f"/api/frames/{frame.id}/image",
    }
    if frame.ingest_status == "NEEDS_TIMESTAMP":
        result["error"] = "captured_at missing/ambiguous — frame not analyzed"
        return result
    if process:
        try:
            run = process_frame(db, frame.id)
            db.commit()
            result["inference_run_id"] = run.id
            result["run_status"] = run.status
            result["detections_url"] = f"/api/frames/{frame.id}/detections"
        except Exception as exc:
            db.rollback()
            raise HTTPException(500, f"processing failed: {exc}") from exc
    return result


@app.get("/api/frames/{frame_id}/detections")
def api_frame_detections(frame_id: int, db: DbDep):
    frame = db.get(Frame, frame_id)
    if not frame:
        raise HTTPException(404, "frame not found")
    run = (
        db.query(InferenceRun)
        .filter(InferenceRun.frame_id == frame_id)
        .order_by(InferenceRun.id.desc())
        .first()
    )
    if not run:
        return {"frame_id": frame_id, "run": None, "detections": []}
    dets = db.query(Detection).filter(Detection.inference_run_id == run.id).all()
    from app.db.models import ModelVersion, Observation

    model = db.get(ModelVersion, run.model_version_id)
    obs = db.query(Observation).filter(Observation.inference_run_id == run.id).one_or_none()
    quality = json.loads(obs.quality_json or "{}") if obs else {}
    return {
        "frame_id": frame_id,
        "captured_at": frame.captured_at.isoformat() if frame.captured_at else None,
        "run": {
            "id": run.id,
            "status": run.status,
            "kb_version": run.kb_version,
            "engine_version": run.engine_version,
            "schedule_version_id": run.schedule_version_id,
            "model": {
                "name": model.name if model else None,
                "weights_sha256": model.weights_sha256 if model else None,
                "weights_path": model.weights_path if model else None,
            },
            "error": run.error,
        },
        "observation": {
            "equipment_vector": json.loads(obs.equipment_vector_json or "{}") if obs else {},
            "observability": obs.observability if obs else None,
            "episode_id": obs.episode_id if obs else None,
            "zones": quality.get("zones") or {},
        },
        "detections": [
            {
                "id": d.id,
                "equipment_code": d.equipment_code,
                "raw_class_name": d.raw_class_name,
                "confidence": d.confidence,
                "bbox_norm": json.loads(d.bbox_norm_json),
                "zone_id": d.zone_id,
                "zone_ambiguous": bool(d.zone_ambiguous),
            }
            for d in dets
        ],
        "pipeline_steps": [
            "1. Приём кадра (контрольная сумма, время съёмки, качество)",
            "2. Идемпотентный прогон (версии CV + базы знаний + КСГ)",
            "3. Неизменяемые детекции техникой с готовых весов",
            "4. Наблюдение и эпизод (повторы не независимы)",
            "5. Multi-label гипотезы видов работ",
            "6. Временной фильтр состояний и события",
            "7. Сопоставление со строками КСГ + «не сопоставлено»",
            "8. Отклонения / сравнение план–факт",
        ],
    }


@app.get("/api/frames/{frame_id}/image")
def api_frame_image(frame_id: int, db: DbDep, project_id: int | None = None):
    """Сырое изображение кадра. project_id отклоняет чужие кадры."""
    from app.services.frames.service import resolve_frame_path

    frame = db.get(Frame, frame_id)
    if not frame or (project_id is not None and frame.project_id != project_id):
        raise HTTPException(404, "image not found")
    path = resolve_frame_path(frame.file_path)
    if path is None or not path.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(path)


@app.get("/api/projects/{project_id}/frames/{frame_id}/image")
def api_project_frame_image(project_id: int, frame_id: int, db: DbDep):
    """Медиа в скоупе проекта — предпочтительно для изоляции."""
    return api_frame_image(frame_id, db, project_id=project_id)


@app.delete("/api/projects/{project_id}/frames/{frame_id}")
def api_delete_frame(project_id: int, frame_id: int, db: DbDep, force: bool = False):
    """Архив/удаление кадра. Evidence-кадры только ARCHIVED (без hard-delete)."""
    from app.services.frames.lifecycle import archive_or_delete_frame

    try:
        out = archive_or_delete_frame(db, project_id=project_id, frame_id=frame_id, force=force)
        db.commit()
        return out
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/projects/{project_id}/schedule-items/{item_id}/complete-preview")
def api_complete_work_preview(project_id: int, item_id: int, db: DbDep):
    """Какие предшественники ещё не закрыты — без записи в БД."""
    from app.services.schedule.completion import preview_complete_work

    try:
        return preview_complete_work(db, project_id=project_id, schedule_item_id=item_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/projects/{project_id}/schedule-items/{item_id}/complete")
def api_complete_work(project_id: int, item_id: int, payload: dict, db: DbDep):
    """Закрыть работу (+ опционально предшественников). Не публикует КСГ."""
    from app.services.schedule.completion import confirm_complete_work

    try:
        out = confirm_complete_work(
            db,
            project_id=project_id,
            schedule_item_id=item_id,
            close_predecessor_ids=payload.get("close_predecessor_ids"),
            close_all_open_predecessors=bool(payload.get("close_all_open_predecessors")),
            user_id=str(payload.get("user_id") or "operator"),
        )
        db.commit()
        return out
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/frames/{frame_id}/overlay")
def api_frame_overlay(
    frame_id: int,
    db: DbDep,
    run_id: int | None = None,
    project_id: int | None = None,
):
    frame = db.get(Frame, frame_id)
    if not frame or (project_id is not None and frame.project_id != project_id):
        raise HTTPException(404, "frame not found")
    run = None
    if run_id:
        run = db.get(InferenceRun, run_id)
    if run is None:
        run = (
            db.query(InferenceRun)
            .filter(InferenceRun.frame_id == frame_id)
            .order_by(InferenceRun.id.desc())
            .first()
        )
    if not run:
        raise HTTPException(404, "run not found")
    path = get_settings().overlays_dir() / f"project_{frame.project_id}" / f"frame_{frame.id}_run_{run.id}.jpg"
    if not path.exists():
        raise HTTPException(404, "overlay not found")
    return FileResponse(path)


@app.get("/api/projects/{project_id}/activities")
def api_activities(
    project_id: int,
    db: DbDep,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    return list_activities(db, project_id, df, dt)


@app.get("/api/projects/{project_id}/matches")
def api_matches(
    project_id: int,
    db: DbDep,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    return list_matches(db, project_id, df, dt)


@app.get("/api/projects/{project_id}/deviations")
def api_deviations(project_id: int, db: DbDep, refresh: bool = False):
    if refresh:
        detect_deviations(db, project_id)
        db.commit()
    rows = (
        db.query(Deviation)
        .filter(Deviation.project_id == project_id)
        .order_by(Deviation.id.desc())
        .all()
    )
    from app.services.explanation.service import explain_deviation
    from app.services.product.deviation_buckets import decorate_deviation_list

    out = []
    for d in rows:
        item = db.get(ScheduleItem, d.schedule_item_id) if d.schedule_item_id else None
        expl = explain_deviation(d)
        details = json.loads(d.details_json or "{}")
        try:
            eids = json.loads(d.evidence_ids_json or "[]")
        except Exception:
            eids = []
        signal_kind = details.get("signal_kind")
        if not signal_kind:
            if d.code == "SCHEDULE_LAG":
                signal_kind = "SCHEDULE_EDITORIAL"
            else:
                signal_kind = "UNVERIFIED"
        # V6: CV_VERIFIED_FINDING только с явным флагом + разрешимыми Frame id (не hyp id)
        frame_eids: list[int] = []
        for x in eids or []:
            try:
                fid = int(x)
            except (TypeError, ValueError):
                continue
            fr = db.get(Frame, fid)
            if fr and fr.project_id == project_id:
                frame_eids.append(fid)
        # V7.1: повышаем production CV-коды, когда evidence кадра резолвится
        if signal_kind == "UNVERIFIED" and frame_eids and d.code in (
            "REQUIRED_EQUIPMENT_GAP",
            "UNEXPECTED_EQUIPMENT_IN_ZONE",
            "CAMERA_COVERAGE_GAP",
            "UNCONFIRMED_ACTIVITY",
            "POSSIBLE_PAUSE",
            "WORK_AFTER_PLAN",
            "LOW_ACTIVITY",
        ):
            signal_kind = "CV_VERIFIED_FINDING"
        # V6 audit: SYNTHETIC_DEMO_FINDING — учебный; CV_VERIFIED только с реальными кадрами + явным флагом
        if signal_kind == "CV_VERIFIED_FINDING" and details.get("data_origin") == "SYNTHETIC_TEST_FIXTURE":
            signal_kind = "SYNTHETIC_DEMO_FINDING"
        if signal_kind == "CV_VERIFIED_FINDING" and not frame_eids:
            signal_kind = "UNVERIFIED"
        if signal_kind == "SYNTHETIC_DEMO_FINDING" and not frame_eids:
            signal_kind = "UNVERIFIED"
        # V5: голый LOW_ACTIVITY без кадров — не camera finding
        if d.code == "LOW_ACTIVITY" and not frame_eids and signal_kind not in (
            "CV_VERIFIED_FINDING",
            "SYNTHETIC_DEMO_FINDING",
        ):
            signal_kind = "UNVERIFIED"
            if not details.get("keep_unverified") and details.get("signal_kind") not in (
                "CV_VERIFIED_FINDING",
                "SYNTHETIC_DEMO_FINDING",
            ):
                continue
        out.append(
            {
                "id": d.id,
                "code": d.code,
                "signal_kind": signal_kind,
                "risk_score": d.heuristic_score if d.heuristic_score is not None else d.risk_score,
                "heuristic_score": d.heuristic_score if d.heuristic_score is not None else d.risk_score,
                "status": d.status,
                "lifecycle": d.lifecycle,
                "schedule_item_id": str(d.schedule_item_id) if d.schedule_item_id is not None else None,
                "schedule_item_name": item.raw_name if item else None,
                "details": details,
                "explanation_ru": expl["text_ru"],
                "finding": expl["finding"],
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "has_evidence_frames": bool(frame_eids),
                "demo_primary": bool(details.get("demo_primary")),
            }
        )
    return decorate_deviation_list(out)


@app.get("/api/projects/{project_id}/schedule-items/{item_id}/evidence")
def api_schedule_item_evidence(
    project_id: int,
    item_id: int,
    db: DbDep,
    as_of: str | None = None,
):
    from app.services.product.overview import schedule_item_evidence

    try:
        return schedule_item_evidence(db, project_id, item_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/projects/{project_id}/overview")
def api_overview(project_id: int, db: DbDep, as_of: str | None = None):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.overview import build_overview

    ao = datetime.fromisoformat(as_of) if as_of else None
    return build_overview(db, project_id, as_of=ao)


@app.get("/api/projects/{project_id}/timeline")
def api_timeline(
    project_id: int,
    db: DbDep,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    building: str | None = None,
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.overview import build_timeline

    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    return build_timeline(db, project_id, date_from=df, date_to=dt, building=building)


@app.get("/api/projects/{project_id}/frames")
def api_list_frames(
    project_id: int,
    db: DbDep,
    camera_id: int | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    limit: int = 50,
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.overview import list_frames

    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    return {"items": list_frames(db, project_id, camera_id=camera_id, date_from=df, date_to=dt, limit=limit)}


@app.get("/api/projects/{project_id}/deviations/{deviation_id}/evidence")
def api_deviation_evidence(project_id: int, deviation_id: int, db: DbDep):
    from app.services.product.overview import deviation_evidence

    try:
        return deviation_evidence(db, project_id, deviation_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/projects/{project_id}/deviations/{deviation_id}/decision-trace")
def api_decision_trace(project_id: int, deviation_id: int, db: DbDep):
    """V7.1 Sprint 4 — только сохранённые факты, без повторного инференса."""
    from app.services.product.decision_trace import build_decision_trace

    try:
        return build_decision_trace(db, project_id, deviation_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/projects/{project_id}/observations/ingest")
async def api_observations_ingest(
    project_id: int,
    db: DbDep,
    file: UploadFile = File(...),
    camera_id: int | None = Form(None),
    camera_name: str | None = Form(None),
    building_hint: str | None = Form(None),
    captured_at: str = Form(...),
    timezone: str = Form("Europe/Moscow"),
    process: bool = Form(True),
    run_deviations: bool = Form(True),
    video_interval_sec: float = Form(30.0),
    async_job: bool | None = Form(None),
):
    """Продуктовый CTA: фото / ZIP / video → quality → YOLO → deviations.

    Одно изображение → sync 200. ZIP/video/несколько кадров → 202 + job_id (durable queue).
    """
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.frames.batch_ingest import (
        ensure_camera,
        expand_upload,
        ingest_observation_batch,
    )
    from app.services.frames.service import parse_captured_at
    from app.services.jobs.queue import get_job, submit_job_async
    from fastapi.responses import JSONResponse

    tz = timezone or "Europe/Moscow"
    ts = parse_captured_at(captured_at, timezone=tz)
    if ts is None:
        raise HTTPException(400, "captured_at missing or invalid")
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    fname = file.filename or "upload.bin"
    try:
        cam = ensure_camera(
            db,
            project_id=project_id,
            camera_id=camera_id,
            camera_name=camera_name,
            building_hint=building_hint,
        )
        items = expand_upload(
            filename=fname,
            content=content,
            captured_at=ts,
            video_interval_sec=float(video_interval_sec or 30),
        )
        ext = Path(fname).suffix.lower()
        multi = len(items) > 1
        is_video = ext in (".mp4", ".mov", ".avi", ".mkv")
        force_async = async_job is True or (async_job is None and (multi or is_video))
        if async_job is False:
            force_async = False
        if not force_async:
            result = ingest_observation_batch(
                db,
                project_id=project_id,
                camera=cam,
                items=items,
                process=process,
                run_deviations=run_deviations,
                as_of=ts,
            )
            db.commit()
            result["timezone"] = tz
            result["timezone_applied"] = True
            result["captured_at_utc"] = ts.isoformat(sep="T", timespec="seconds") + "Z"
            result["mode"] = "sync"
            result["stages"] = ["uploaded", "frames", "cv", "analytics", "done"]
            return result

        # Сохранить камеру и commit до фонового job со своей сессией
        cam_id = cam.id
        cam_name = cam.name
        db.commit()

        # Материализовать items (bytes) для worker — уже в памяти
        packed = [(n, blob, t.isoformat(sep="T", timespec="seconds") if t else None) for n, blob, t in items]

        def _worker() -> dict:
            from app.db import SessionLocal
            from app.db.models import Camera as CamModel
            from app.services.frames.service import parse_captured_at as _parse

            wdb = SessionLocal()
            try:
                wcam = wdb.get(CamModel, cam_id)
                if wcam is None:
                    raise ValueError("camera missing in worker")
                witems = [(n, b, _parse(t) if t else None) for n, b, t in packed]
                stages = {"uploaded": True, "frames_extracted": False, "cv": False, "analytics": False, "done": False}
                stages["frames_extracted"] = True
                out = ingest_observation_batch(
                    wdb,
                    project_id=project_id,
                    camera=wcam,
                    items=witems,
                    process=process,
                    run_deviations=run_deviations,
                    as_of=ts,
                )
                stages["cv"] = True
                stages["analytics"] = True
                stages["done"] = True
                wdb.commit()
                out["timezone"] = tz
                out["timezone_applied"] = True
                out["captured_at_utc"] = ts.isoformat(sep="T", timespec="seconds") + "Z"
                out["mode"] = "async"
                out["stages"] = stages
                out["progress"] = {
                    "uploaded": True,
                    "frames_extracted": True,
                    "cv": True,
                    "analytics": True,
                    "done": True,
                }
                return out
            except Exception:
                wdb.rollback()
                raise
            finally:
                wdb.close()

        job = submit_job_async("observation_ingest", _worker)
        fresh = get_job(job.id) or job
        body = {
            "job_id": fresh.id,
            "status": fresh.status,
            "mode": "async",
            "camera_id": cam_id,
            "camera_name": cam_name,
            "frame_count_queued": len(items),
            "timezone": tz,
            "stages": ["uploaded", "frames_extracted", "cv", "analytics", "done"],
            "progress_url": f"/api/ops/jobs/{fresh.id}",
            "note": "poll progress_url until status=COMPLETED",
        }
        return JSONResponse(status_code=202, content=body)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"observation ingest failed: {exc}") from exc


@app.patch("/api/projects/{project_id}/deviations/{deviation_id}")
def api_patch_deviation(project_id: int, deviation_id: int, payload: dict, db: DbDep):
    from app.services.product.overview import patch_deviation_lifecycle
    from app.services.explanation.service import explain_deviation

    try:
        row = patch_deviation_lifecycle(
            db,
            project_id,
            deviation_id,
            lifecycle=str(payload.get("lifecycle") or payload.get("status") or "ACKNOWLEDGED"),
            note=payload.get("note"),
            user_id=str(payload.get("user_id") or "operator"),
        )
        db.commit()
        expl = explain_deviation(row)
        return {
            "id": row.id,
            "lifecycle": row.lifecycle,
            "explanation_ru": expl["text_ru"],
            "ack_is_ml_label": False,
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/projects/{project_id}/deviations/{deviation_id}/verdict")
def api_deviation_verdict(project_id: int, deviation_id: int, payload: dict, db: DbDep):
    """Экспертный confirm/reject/correct — создаёт HumanVerdict."""
    from app.services.verification.service import is_ml_label, submit_verdict

    d = db.get(Deviation, deviation_id)
    if not d or d.project_id != project_id:
        raise HTTPException(404, "deviation not found")
    verdict = str(payload.get("verdict") or "").strip()
    if not verdict:
        raise HTTPException(400, "verdict required")
    row = submit_verdict(
        db,
        target_type="deviation",
        target_id=deviation_id,
        verdict=verdict,
        correction=payload.get("correction") or {},
        user_id=str(payload.get("user_id") or "operator"),
    )
    db.commit()
    return {
        "verdict_id": row.id,
        "verdict": row.verdict,
        "is_ml_label": is_ml_label(row.verdict),
        "lifecycle": d.lifecycle,
    }


@app.get("/api/projects/{project_id}/daily/{day}")
def api_daily(project_id: int, day: str, db: DbDep):
    row = ensure_daily_summary(db, project_id, day)
    db.commit()
    return {
        "date": row.date,
        "generated_at": row.generated_at.isoformat(),
        "run_version": row.run_version,
        "payload": json.loads(row.payload_json or "{}"),
    }


@app.get("/api/hypotheses/{hypothesis_id}/evidence")
def api_evidence(hypothesis_id: int, db: DbDep):
    try:
        return get_work_evidence(db, hypothesis_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/hypotheses/{hypothesis_id}/verify")
def api_verify(hypothesis_id: int, payload: dict, db: DbDep):
    from app.db.models import ActivityHypothesis

    if not db.get(ActivityHypothesis, hypothesis_id):
        raise HTTPException(404, "hypothesis not found")
    row = submit_verdict(
        db,
        target_type="hypothesis",
        target_id=hypothesis_id,
        verdict=str(payload.get("verdict") or "confirm"),
        correction=payload.get("correction") or {},
        user_id=str(payload.get("user_id") or "operator"),
    )
    db.commit()
    return {"verdict_id": row.id, "verdict": row.verdict}


@app.get("/api/projects/{project_id}/verification-queue")
def api_verification_queue(project_id: int, db: DbDep):
    from app.services.reporting.service import serialize_hypothesis

    rows = queue_ambiguous(db, project_id)
    return [serialize_hypothesis(db, h) for h in rows]


@app.get("/api/knowledge/equipment-work-rules")
def api_kb_rules(db: DbDep):
    kb = load_kb()
    sync_kb_to_db(db)
    db.commit()
    return {
        "version": kb.version,
        "work_types": kb.work_types,
        "equipment": kb.equipment,
        "rules": [
            {
                "work_type": r.work_type,
                "equipment_type": r.equipment_type,
                "theta": r.theta,
                "necessity": r.necessity,
                "source": r.source,
            }
            for r in kb.rules
        ],
        "joint_patterns": list(kb.joint_patterns),
        "note": "θ values are expert seed — not calibrated probabilities",
    }


# --- V4.2 Stage 4: админ-каталоги / профили работ ---


@app.get("/api/admin/catalogs/{catalog_key}")
def api_admin_catalog_get(catalog_key: str, db: DbDep):
    from app.services.product.v42_api import list_catalog

    return list_catalog(db, catalog_key)


@app.put("/api/admin/catalogs/{catalog_key}")
def api_admin_catalog_put(catalog_key: str, payload: dict, db: DbDep):
    from app.services.product.v42_api import replace_catalog

    return replace_catalog(db, catalog_key, payload or {})


@app.get("/api/admin/work-profiles")
def api_admin_work_profiles_get(db: DbDep):
    from app.services.product.v42_api import list_work_profiles

    return list_work_profiles(db)


@app.put("/api/admin/work-profiles")
def api_admin_work_profiles_put(payload: dict, db: DbDep):
    from app.services.product.v42_api import replace_work_profiles

    return replace_work_profiles(db, payload or {})


# --- V7.2 P2-AI: единый backend AI surface (браузер не должен звать Ollama) ---


@app.get("/api/ai/status")
def api_ai_status():
    from app.services.llm.registry import registry_snapshot

    return registry_snapshot()


@app.post("/api/ai/canonical-match")
def api_ai_canonical_match(payload: dict | None = None):
    from app.services.llm.canonical_match import match_activities

    body = payload or {}
    activities = body.get("activities") or []
    catalog = body.get("catalog") or []
    if not catalog and body.get("candidates"):
        catalog = body["candidates"]
    use_llm = body.get("use_llm", True)
    return match_activities(list(activities), list(catalog), use_llm=bool(use_llm))


@app.post("/api/ai/explain")
def api_ai_explain(payload: dict | None = None):
    from app.services.llm.qwen_explain import explain_structured

    return explain_structured(payload or {})


@app.post("/api/ai/vlm-assist")
def api_ai_vlm_assist(payload: dict | None = None):
    """Опциональный multimodal assistant — не источник истины."""
    from app.services.llm.vlm_assist import vlm_assist

    return vlm_assist(payload or {})


@app.get("/api/ai/feedback-dataset")
def api_ai_feedback_dataset(
    db: DbDep,
    project_id: int | None = None,
    limit: int = 200,
):
    from app.services.verification.feedback_dataset import build_feedback_dataset

    return build_feedback_dataset(db, project_id=project_id, limit=max(1, min(limit, 2000)))


# --- V4.2 Stage 5–6: заглушки AI-маппинга (для совместимости) ---


@app.post("/api/ai/mapping/status")
def api_ai_mapping_status():
    from app.services.llm.registry import registry_snapshot
    from app.services.product.v42_api import ai_mapping_status

    legacy = ai_mapping_status()
    snap = registry_snapshot()
    return {
        **legacy,
        "available": bool(snap.get("ollama_configured")),
        "reachable": snap.get("ollama_reachable"),
        "model": (snap.get("models") or {}).get("text_llm", {}).get("id"),
        "registry": snap,
        "note": "Prefer GET /api/ai/status",
    }


@app.post("/api/ai/mapping/suggest")
def api_ai_mapping_suggest(payload: dict | None = None):
    """Совместимая обёртка → эвристика canonical-match (+ опциональный LLM)."""
    from app.services.llm.canonical_match import match_activities

    body = payload or {}
    names = body.get("names") or []
    activities = body.get("activities") or [{"id": f"n-{i}", "name": n} for i, n in enumerate(names)]
    catalog = body.get("catalog") or body.get("candidates") or []
    out = match_activities(list(activities), list(catalog), use_llm=bool(body.get("use_llm", False)))
    return {
        "candidates": [
            {
                "name": m["source_name"],
                "canonical_work_code": m.get("canonical_work_code"),
                "canonical_work_name": m.get("canonical_work_name"),
                "score": m.get("score"),
                "source": m.get("source"),
                "mapping_status": m.get("mapping_status"),
            }
            for m in out.get("matches") or []
        ],
        "fallback": not out.get("used_llm"),
        "note": out.get("detail") or "backend canonical-match",
        "matches": out.get("matches"),
    }


# --- V4.2 Stage 7–8: тред комментариев evidence ---


@app.get("/api/projects/{project_id}/activities/{activity_id}/evidence-thread")
def api_evidence_thread_get(
    project_id: int,
    activity_id: str,
    db: DbDep,
    signal: str | None = Query(None),
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.v42_api import list_evidence_thread

    return {"items": list_evidence_thread(db, project_id, activity_id, signal=signal)}


@app.post("/api/projects/{project_id}/activities/{activity_id}/evidence-thread")
def api_evidence_thread_post(
    project_id: int,
    activity_id: str,
    payload: dict,
    db: DbDep,
    signal: str | None = Query(None),
):
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    from app.services.product.v42_api import add_evidence_comment

    items = add_evidence_comment(db, project_id, activity_id, payload or {}, signal=signal)
    return {"items": items}
