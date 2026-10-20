"""V7.2 §6 — разнообразие demo KPI + персоны КСГ из серверной истины."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.db import SessionLocal, init_db
from app.db.models import Camera, Deviation, Frame, Project, ScheduleItem, reset_engine
from app.services.product.health import compute_project_health
from app.services.product.v42_api import settings_of
from app.services.schedule.service import get_active_schedule

PERSONAS = {
    "strogino": "COMBINED — cameras + KSG + strong finding",
    "parkline": "ON_TRACK — late stage, healthy schedule",
    "amursky": "DELAYED — strong schedule lag (14d+)",
    "teatralny": "STALE observations / data freshness",
    "nevsky": "expert-closed findings",
    "pravda": "mid-stage compact WBS",
    "plekhanova": "early-stage fewer active works",
}


def _slug(p: Project) -> str | None:
    return settings_of(p).get("slug")


def _acts(db, project_id: int) -> list[ScheduleItem]:
    v = get_active_schedule(db, project_id)
    if not v:
        return []
    return (
        db.query(ScheduleItem)
        .filter(ScheduleItem.schedule_version_id == v.id, ScheduleItem.is_summary.is_(False))
        .all()
    )


def _set_persona(p: Project, persona: str, stage: str) -> None:
    s = settings_of(p)
    s.pop("status", None)
    s["demo_persona"] = persona
    s["demo_stage"] = stage
    s["status_note"] = "legacy_removed_v72"
    p.settings_json = json.dumps(s, ensure_ascii=False)


def _thin_wbs(acts: list[ScheduleItem], keep: int) -> None:
    """Лишние листья → summary, чтобы число видимых работ отличалось по проектам."""
    for i, a in enumerate(sorted(acts, key=lambda x: x.id)):
        if i >= keep:
            a.is_summary = True


def main() -> None:
    os.environ.setdefault("PLANSIGHT_DATABASE_PATH", str(REPO_ROOT / "data" / "plansight.db"))
    get_settings.cache_clear()
    reset_engine()
    init_db()
    db = SessionLocal()
    try:
        by_slug = {_slug(p): p for p in db.query(Project).all() if _slug(p)}
        from app.services.product.demo_clock import demo_as_of_iso

        as_of = datetime.fromisoformat(demo_as_of_iso()[:10] + "T12:00:00")

        # parkline — ON_TRACK поздняя стадия
        p = by_slug.get("parkline")
        if p:
            acts = _acts(db, p.id)
            for a in acts:
                a.is_summary = False
                plan = float(a.planned_progress or 70)
                a.planned_progress = max(plan, 70.0)
                a.actual_progress = min(100.0, float(a.planned_progress) + 1)
                if a.planned_finish and a.planned_finish.date() < as_of.date():
                    a.planned_finish = as_of + timedelta(days=40)
                    a.actual_progress = max(float(a.actual_progress or 0), 96.0)
            _set_persona(p, "ON_TRACK_SCHEDULE", "late")

        # amursky — DELAYED (лаг ≥14д)
        p = by_slug.get("amursky")
        if p:
            acts = _acts(db, p.id)
            for a in acts:
                a.is_summary = False
            for i, a in enumerate(acts):
                plan = float(a.planned_progress or 50)
                if i % 4 == 0:
                    a.actual_progress = max(0.0, plan - 35)
                    a.planned_finish = as_of - timedelta(days=16)
                elif i % 4 == 1:
                    a.actual_progress = max(0.0, plan - 20)
                    a.planned_finish = as_of - timedelta(days=10)
                else:
                    a.actual_progress = max(0.0, plan - 2)
                    if a.planned_finish and a.planned_finish.date() < as_of.date():
                        a.planned_finish = as_of + timedelta(days=20)
            for d in db.query(Deviation).filter(Deviation.project_id == p.id).all():
                d.lifecycle = "RESOLVED"
                d.status = "resolved"
                d.resolved_at = as_of
            _set_persona(p, "DELAYED_SCHEDULE", "mid")

        # teatralny — устаревшие наблюдения, без prod findings, шум DQ
        p = by_slug.get("teatralny")
        if p:
            for a in _acts(db, p.id):
                a.is_summary = False
                a.actual_progress = 38.0
                a.planned_progress = 40.0
                if a.planned_finish and a.planned_finish.date() < as_of.date():
                    a.planned_finish = as_of + timedelta(days=50)
            for d in db.query(Deviation).filter(Deviation.project_id == p.id).all():
                if d.code in (
                    "REQUIRED_EQUIPMENT_GAP",
                    "UNEXPECTED_EQUIPMENT_IN_ZONE",
                    "UNCONFIRMED_ACTIVITY",
                    "SCHEDULE_LAG",
                    "POSSIBLE_LATE_START",
                    "POSSIBLE_PAUSE",
                    "WORK_AFTER_PLAN",
                    "LOW_ACTIVITY",
                    "EARLY_START",
                ):
                    d.lifecycle = "RESOLVED"
                    d.status = "resolved"
                    d.resolved_at = as_of
            # Гарантируем camera + stale frame для data_freshness=STALE
            cam = db.query(Camera).filter(Camera.project_id == p.id).first()
            if cam is None:
                cam = Camera(project_id=p.id, name="Камера площадки (устаревшие кадры)", building_hint=None)
                db.add(cam)
                db.flush()
            stale_at = as_of - timedelta(days=60)
            # Реальный файл (копия still), иначе resolve_frame_path даёт 404
            stale_rel = "demo/teatralny_stale_placeholder.jpg"
            stale_abs = REPO_ROOT / stale_rel
            if not stale_abs.exists():
                stills = sorted((REPO_ROOT / "demo" / "stills").glob("*.png"))
                if stills:
                    stale_abs.parent.mkdir(parents=True, exist_ok=True)
                    import shutil

                    shutil.copy2(stills[0], stale_abs)
            fr = db.query(Frame).filter(Frame.project_id == p.id).first()
            if fr is None:
                fr = Frame(
                    project_id=p.id,
                    camera_id=cam.id,
                    captured_at=stale_at,
                    file_path=stale_rel,
                    sha256="teatralny_stale_placeholder_v72",
                    ingest_status="READY",
                    image_quality="VALID",
                    quality_json=json.dumps({"source_kind": "PHOTO_ARCHIVE", "stale_demo": True}),
                )
                db.add(fr)
            else:
                fr.captured_at = stale_at
                if not (fr.file_path or "").strip():
                    fr.file_path = stale_rel
            # Сид пробелов качества данных (не производственные риски)
            dq_n = (
                db.query(Deviation)
                .filter(Deviation.project_id == p.id, Deviation.code == "CAMERA_COVERAGE_GAP", Deviation.lifecycle == "OPEN")
                .count()
            )
            for i in range(max(0, 6 - dq_n)):
                db.add(
                    Deviation(
                        project_id=p.id,
                        code="CAMERA_COVERAGE_GAP",
                        lifecycle="OPEN",
                        status="open",
                        risk_score=0.2,
                        heuristic_score=0.2,
                        details_json=json.dumps(
                            {
                                "signal_kind": "UNVERIFIED",
                                "camera_id": cam.id,
                                "zone_key": "Z1",
                                "note": "stale_demo_coverage",
                            },
                            ensure_ascii=False,
                        ),
                        evidence_ids_json="[]",
                    )
                )
            _set_persona(p, "STALE_OBSERVATIONS", "mid")

        # nevsky — закрыт экспертом
        p = by_slug.get("nevsky")
        if p:
            for a in _acts(db, p.id):
                a.is_summary = False
                plan = float(a.planned_progress or 60)
                a.actual_progress = min(100.0, plan + 1)
            for d in db.query(Deviation).filter(Deviation.project_id == p.id).all():
                d.lifecycle = "RESOLVED"
                d.status = "resolved"
                d.resolved_at = as_of
            _set_persona(p, "EXPERT_CLOSED", "late")

        # pravda — средняя стадия, более тонкий WBS (~12 листьев)
        p = by_slug.get("pravda")
        if p:
            acts = _acts(db, p.id)
            for a in acts:
                a.is_summary = False
            _thin_wbs(acts, keep=12)
            for a in _acts(db, p.id):
                a.actual_progress = 55.0
                a.planned_progress = 58.0
                if a.planned_finish and a.planned_finish.date() < as_of.date():
                    a.planned_finish = as_of + timedelta(days=25)
            for d in db.query(Deviation).filter(Deviation.project_id == p.id).all():
                d.lifecycle = "RESOLVED"
                d.status = "resolved"
                d.resolved_at = as_of
            _set_persona(p, "MID_STAGE_COMPACT", "mid")

        # plekhanova — ранняя стадия, мало активных работ (~8)
        p = by_slug.get("plekhanova")
        if p:
            acts = _acts(db, p.id)
            for a in acts:
                a.is_summary = False
            _thin_wbs(acts, keep=8)
            for a in _acts(db, p.id):
                a.actual_progress = 18.0
                a.planned_progress = 22.0
                a.planned_start = as_of - timedelta(days=10)
                a.planned_finish = as_of + timedelta(days=90)
            for d in db.query(Deviation).filter(Deviation.project_id == p.id).all():
                d.lifecycle = "RESOLVED"
                d.status = "resolved"
                d.resolved_at = as_of
            _set_persona(p, "EARLY_STAGE", "early")

        # strogino — оставляем 1–2 сильных CV-сигнала, лишнее закрываем (не «всё красное»)
        p = by_slug.get("strogino")
        if p:
            prod = (
                db.query(Deviation)
                .filter(
                    Deviation.project_id == p.id,
                    Deviation.code.in_(
                        (
                            "REQUIRED_EQUIPMENT_GAP",
                            "UNEXPECTED_EQUIPMENT_IN_ZONE",
                            "UNCONFIRMED_ACTIVITY",
                            "SCHEDULE_LAG",
                            "LOW_ACTIVITY",
                        )
                    ),
                )
                .order_by(Deviation.id.asc())
                .all()
            )
            keep = 0
            for d in prod:
                details = {}
                try:
                    details = json.loads(d.details_json or "{}")
                except Exception:
                    details = {}
                primary = bool(details.get("demo_primary")) or d.code == "REQUIRED_EQUIPMENT_GAP"
                if primary and keep < 2 and (d.lifecycle or "OPEN") in ("OPEN", "ACKNOWLEDGED", "", None):
                    d.lifecycle = "OPEN"
                    d.status = "open"
                    keep += 1
                else:
                    d.lifecycle = "RESOLVED"
                    d.status = "resolved"
                    d.resolved_at = as_of
            for a in _acts(db, p.id):
                # не раздувать календарный lag
                if a.planned_finish and a.planned_finish.date() < as_of.date():
                    if float(a.actual_progress or 0) < 95:
                        a.actual_progress = 100.0
            _set_persona(p, "COMBINED_CV", "combined")

        # Снимаем legacy status везде остальном
        for p in db.query(Project).all():
            s = settings_of(p)
            if "status" in s:
                s.pop("status", None)
                s["status_note"] = "legacy_removed_v72"
                p.settings_json = json.dumps(s, ensure_ascii=False)

        db.commit()

        print("=== health after diversify ===")
        for slug, intent in PERSONAS.items():
            p = by_slug.get(slug)
            if not p:
                continue
            h = compute_project_health(db, p, as_of=as_of.date().isoformat())
            print(
                {
                    "slug": slug,
                    "intent": intent,
                    "status": h.status,
                    "progress": h.progress,
                    "problems": h.problem_works,
                    "open_prod": h.open_production_findings,
                    "open_dq": h.open_data_quality_findings,
                    "freshness": h.data_freshness,
                    "source": h.status_source,
                    "analysis": h.analysis_source,
                    "works": len(_acts(db, p.id)),
                }
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
