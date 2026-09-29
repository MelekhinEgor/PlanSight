"""V7.4 — очистка shipped product DB перед релизом.

Удаляет CV Lab, MANUAL_DEMO / учебные findings, legacy calendar-only hypotheses,
абсолютные Windows-пути кадров и чинит cadence для photo-archive камер.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.core.config import get_settings
from app.db.migrate import ensure_schema_patches
from app.db.models import (
    ActivityHypothesis,
    Camera,
    Deviation,
    Frame,
    InferenceRun,
    Project,
    SessionLocal,
    init_db,
    reset_engine,
)
from app.services.product.slugs import project_slug
from app.services.product.v42_api import settings_of


def relativize(path: str) -> str:
    raw = path.replace("\\", "/")
    # Сначала uploads — не путать strogino_frames/... с каталогом frames/
    m = re.search(r"(data/uploads/.+)$", raw, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|/)(uploads/.+)$", raw, re.I)
    if m:
        return "data/" + m.group(1)
    # Канонический каталог data/frames/... или frames/... (не *_frames)
    m = re.search(r"(data/frames/.+)$", raw, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|/)(frames/[^/]+)$", raw, re.I)
    if m:
        return m.group(1)
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return path


CV_LAB_MARKERS = ("CV Lab", "синтетический контур", "синтетик")
MANUAL_MARKERS = ("MANUAL_DEMO", "учебн", "Учебный график", "demo", "synthetic")

def _is_cv_lab(project: Project) -> bool:
    name = (project.name or "").lower()
    if "cv lab" in name or "синтетич" in name:
        return True
    try:
        s = settings_of(project)
        blob = json.dumps(s, ensure_ascii=False).lower()
        if "cv_lab" in blob or "cvlab" in blob:
            return True
    except Exception:
        pass
    return False


def _delete_project(db, project_id: int) -> None:
    ids = str(project_id)
    for stmt in (
        f"DELETE FROM detection WHERE inference_run_id IN (SELECT id FROM inference_run WHERE frame_id IN (SELECT id FROM frame WHERE project_id IN ({ids})))",
        f"DELETE FROM observation WHERE inference_run_id IN (SELECT id FROM inference_run WHERE frame_id IN (SELECT id FROM frame WHERE project_id IN ({ids})))",
        f"DELETE FROM schedule_match WHERE hypothesis_id IN (SELECT id FROM activity_hypothesis WHERE inference_run_id IN (SELECT id FROM inference_run WHERE frame_id IN (SELECT id FROM frame WHERE project_id IN ({ids}))))",
        f"DELETE FROM activity_hypothesis WHERE inference_run_id IN (SELECT id FROM inference_run WHERE frame_id IN (SELECT id FROM frame WHERE project_id IN ({ids})))",
        f"DELETE FROM inference_run WHERE frame_id IN (SELECT id FROM frame WHERE project_id IN ({ids}))",
        f"DELETE FROM frame WHERE project_id IN ({ids})",
        f"DELETE FROM camera_zone_binding WHERE project_id IN ({ids})",
        f"DELETE FROM camera_visual_zone WHERE project_id IN ({ids})",
        f"DELETE FROM camera WHERE project_id IN ({ids})",
        f"DELETE FROM human_verdict WHERE target_type IN ('deviation','finding') AND target_id IN (SELECT id FROM deviation WHERE project_id IN ({ids}))",
        f"DELETE FROM deviation WHERE project_id IN ({ids})",
        f"DELETE FROM scenario_run WHERE project_id IN ({ids})",
        f"DELETE FROM project_object WHERE project_id IN ({ids})",
        f"DELETE FROM schedule_item WHERE schedule_version_id IN (SELECT id FROM schedule_version WHERE project_id IN ({ids}))",
        f"DELETE FROM schedule_dependency WHERE schedule_version_id IN (SELECT id FROM schedule_version WHERE project_id IN ({ids}))",
        f"DELETE FROM schedule_version WHERE project_id IN ({ids})",
        f"DELETE FROM project WHERE id IN ({ids})",
    ):
        try:
            db.execute(text(stmt))
        except Exception as exc:
            print("skip", stmt[:60], "->", exc)


def _legacy_calendar_only(hyp: ActivityHypothesis) -> bool:
    """visual hyp с equipment=0 от calendar-prior движка до V7.3."""
    raw = getattr(hyp, "explanation_json", None) or getattr(hyp, "features_json", None) or "{}"
    try:
        feats = json.loads(raw or "{}")
    except Exception:
        feats = {}
    # Вложенный feature breakdown типичен для новых explanations
    if "features" in feats and isinstance(feats["features"], dict):
        feats = {**feats, **feats["features"]}
    eq = feats.get("equipment") or feats.get("equipment_score") or 0
    try:
        eq_f = float(eq)
    except (TypeError, ValueError):
        eq_f = 0.0
    if eq_f > 0.01:
        return False
    cal = feats.get("calendar") or feats.get("calendar_prior") or feats.get("prior")
    try:
        cal_f = float(cal) if cal is not None else 0.0
    except (TypeError, ValueError):
        cal_f = 0.0
    if feats.get("allow_zero_equipment"):
        return False
    # Помечаем legacy: нет техники и высокий calendar либо нет флага equipment evidence
    return eq_f <= 0.01 and (cal_f >= 0.5 or not feats.get("equipment_evidence"))


def main() -> None:
    product = (REPO_ROOT / "data" / "plansight.db").resolve()
    os.environ["PLANSIGHT_DATABASE_PATH"] = str(product)
    get_settings.cache_clear()
    reset_engine()
    init_db()
    ensure_schema_patches()
    db = SessionLocal()
    report: dict = {
        "removed_projects": [],
        "removed_deviations": 0,
        "removed_hypotheses": 0,
        "paths_updated": 0,
        "cadence_fixed": 0,
    }
    try:
        # 1) Удаляем CV Lab
        for p in list(db.query(Project).all()):
            if _is_cv_lab(p):
                report["removed_projects"].append({"id": p.id, "name": p.name})
                _delete_project(db, p.id)
        db.commit()

        # 2) Удаляем только «сломанные» учебные findings без доказательств.
        # PRODUCT_DEMO (конкурсный seed с evidence) сохраняем.
        doomed_dev: list[int] = []
        for d in db.query(Deviation).all():
            blob = " ".join(
                [
                    d.code or "",
                    d.details_json or "",
                    d.event_key or "",
                ]
            ).lower()
            details = {}
            try:
                details = json.loads(d.details_json or "{}")
            except Exception:
                pass
            origin = str(details.get("data_origin") or details.get("origin") or "").upper()
            evid = []
            try:
                evid = json.loads(d.evidence_ids_json or "[]")
            except Exception:
                evid = []
            kill = False
            # Старый MANUAL_DEMO без кадров — шум
            if origin == "MANUAL_DEMO" and not evid:
                kill = True
            # Явно помеченные как учебные без evidence
            if ("учебн" in blob or "учебный график" in blob) and not evid and origin != "PRODUCT_DEMO":
                kill = True
            # CV-код без работы и без evidence
            cv_codes = {
                "EARLY_START",
                "WORK_AFTER_PLAN",
                "REQUIRED_EQUIPMENT_GAP",
                "EQUIPMENT_COMPOSITION_ANOMALY",
                "POSSIBLE_LATE_START",
                "UNCONFIRMED_ACTIVITY",
            }
            if d.code in cv_codes and not evid and not d.schedule_item_id:
                kill = True
            if kill:
                doomed_dev.append(d.id)
        if doomed_dev:
            ids = ",".join(str(i) for i in doomed_dev)
            try:
                db.execute(text(f"DELETE FROM human_verdict WHERE deviation_id IN ({ids})"))
            except Exception:
                pass
            db.execute(text(f"DELETE FROM deviation WHERE id IN ({ids})"))
            report["removed_deviations"] = len(doomed_dev)
        db.commit()

        # 3) Legacy гипотезы только из календаря (equipment=0)
        doomed_h: list[int] = []
        for h in db.query(ActivityHypothesis).all():
            if _legacy_calendar_only(h):
                doomed_h.append(h.id)
        if doomed_h:
            ids = ",".join(str(i) for i in doomed_h)
            try:
                db.execute(text(f"DELETE FROM schedule_match WHERE hypothesis_id IN ({ids})"))
            except Exception:
                pass
            db.execute(text(f"DELETE FROM activity_hypothesis WHERE id IN ({ids})"))
            report["removed_hypotheses"] = len(doomed_h)
        db.commit()

        # 4) Относительные пути кадров (не ломать …/strogino_frames/…)
        for fr in db.query(Frame).all():
            if not fr.file_path:
                continue
            new = relativize(fr.file_path)
            if new != fr.file_path:
                fr.file_path = new
                report["paths_updated"] += 1
        db.commit()

        # 5) Каденс photo-archive: expected_interval_sec → 1800 при PHOTO_ARCHIVE
        for cam in db.query(Camera).all():
            frames = db.query(Frame).filter(Frame.camera_id == cam.id).limit(20).all()
            is_archive = False
            for fr in frames:
                try:
                    q = json.loads(fr.quality_json or "{}")
                except Exception:
                    q = {}
                if q.get("source_kind") == "PHOTO_ARCHIVE" or q.get(
                    "not_claiming_continuous_fixed_camera"
                ):
                    is_archive = True
                    break
            if is_archive and getattr(cam, "expected_interval_sec", None) not in (None, 1800):
                if hasattr(cam, "expected_interval_sec"):
                    cam.expected_interval_sec = 1800
                    report["cadence_fixed"] += 1
        db.commit()

        remaining = [
            {"id": p.id, "name": p.name, "slug": project_slug(settings_of(p))}
            for p in db.query(Project).order_by(Project.id).all()
        ]
        # Сироты scenario_runs после удаления проектов
        try:
            r = db.execute(text("DELETE FROM scenario_run WHERE project_id NOT IN (SELECT id FROM project)"))
            report["orphan_scenarios_removed"] = r.rowcount or 0
            db.commit()
        except Exception as exc:
            print("skip orphan scenarios", exc)
        report["remaining_projects"] = remaining
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
