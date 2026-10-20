"""V7.2 P0-02 — единый серверный источник health проекта / KPI портфеля."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Deviation, Frame, InferenceRun, Project, ScheduleItem
from app.services.product.v42_api import settings_of
from app.services.schedule.service import get_active_schedule

# Коды производственных / бизнес-рисков (в KPI портфеля)
PRODUCTION_CODES = {
    "REQUIRED_EQUIPMENT_GAP",
    "UNEXPECTED_EQUIPMENT_IN_ZONE",
    "UNCONFIRMED_ACTIVITY",
    "POSSIBLE_LATE_START",
    "POSSIBLE_PAUSE",
    "WORK_AFTER_PLAN",
    "SCHEDULE_LAG",
    "EARLY_START",
    "LOW_ACTIVITY",
}

# Шум качества данных / setup (уточнение, не равны производственному риску)
DATA_QUALITY_CODES = {
    "CAMERA_COVERAGE_GAP",
    "AMBIGUOUS_ASSIGNMENT",
    "NEEDS_CAMERA_SETUP",
}


@dataclass
class ProjectHealth:
    status: str
    status_reason: str
    status_source: str
    problem_works: int
    open_findings: int
    open_production_findings: int
    open_data_quality_findings: int
    max_deviation: int
    # Бакеты lag по работам (не max проекта). Donut/bar аналитики.
    works_critical: int  # lag > 10 days
    works_high: int  # lag 6–10 days
    works_medium: int  # lag 1–5 days
    works_normal: int  # no lag / on track
    progress: int
    progress_source: str
    last_analysis: str
    last_analysis_kind: str
    last_observation_at: str | None
    last_cv_analysis_at: str | None
    analysis_source: str
    data_freshness: str
    as_of: str


def _iso_day(dt: datetime | None) -> str | None:
    return dt.date().isoformat() if dt else None


def _diff_days(a: str, b: str) -> int:
    try:
        da = datetime.fromisoformat(a[:10])
        db = datetime.fromisoformat(b[:10])
        return abs((db - da).days)
    except Exception:
        return 0


def _work_lag_days(a: ScheduleItem, now: str) -> int:
    """Календарный lag одной листовой работы относительно as_of."""
    end = _iso_day(a.planned_finish)
    if end and end < now:
        return _diff_days(end, now)
    gap = float(a.planned_progress or 0) - float(a.actual_progress or 0)
    if gap > 10:
        return max(1, int(round(gap / 4)))
    return 0


def _is_active_as_of(a: ScheduleItem, now: str) -> bool:
    """Работа в scope аналитики на сегодня: стартовала, due, завершена — не будущий idle."""
    fact = float(a.actual_progress or 0)
    plan = float(a.planned_progress or 0)
    if fact > 0 or fact >= 100 or plan > 0:
        return True
    start = _iso_day(a.planned_start)
    end = _iso_day(a.planned_finish)
    if start and start <= now:
        return True
    if end and end <= now:
        return True
    return False


def _analysis_source(*, has_schedule: bool, has_obs: bool, expert: bool) -> str:
    if expert:
        return "EXPERT"
    if has_schedule and has_obs:
        return "COMBINED"
    if has_obs:
        return "OBSERVATION"
    if has_schedule:
        return "SCHEDULE"
    return "SCHEDULE"


def compute_project_health(
    db: Session,
    project: Project,
    *,
    as_of: str | None = None,
) -> ProjectHealth:
    settings = settings_of(project)
    from app.services.product.demo_clock import demo_as_of_iso

    ao = datetime.fromisoformat((as_of or demo_as_of_iso())[:19])
    now = ao.date().isoformat()

    version = get_active_schedule(db, project.id)
    acts: list[ScheduleItem] = []
    if version:
        acts = (
            db.query(ScheduleItem)
            .filter(
                ScheduleItem.schedule_version_id == version.id,
                ScheduleItem.is_summary.is_(False),
            )
            .all()
        )

    problem: list[ScheduleItem] = []
    works_critical = 0
    works_high = 0
    works_medium = 0
    works_normal = 0
    max_dev = 0
    for a in acts:
        fact = float(a.actual_progress or 0)
        plan = float(a.planned_progress or 0)
        end = _iso_day(a.planned_finish)
        is_problem = fact + 10 < plan or (end and end < now and fact < 100)
        if is_problem:
            problem.append(a)
            lag = _work_lag_days(a, now)
            max_dev = max(max_dev, lag)
            if lag > 10:
                works_critical += 1
            elif lag > 5:
                works_high += 1
            else:
                works_medium += 1
            continue
        # Будущие работы по плану (не начаты, ещё не due) вне donut.
        if _is_active_as_of(a, now):
            works_normal += 1

    progress = int(round(sum(float(a.actual_progress or 0) for a in acts) / len(acts))) if acts else 0
    progress_source = "SCHEDULE_CALCULATED" if acts else "NONE"

    open_rows = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project.id,
            (Deviation.lifecycle.is_(None))
            | (Deviation.lifecycle == "")
            | (Deviation.lifecycle.in_(("OPEN", "ACKNOWLEDGED"))),
        )
        .all()
    )
    open_findings = len(open_rows)
    open_prod = sum(1 for d in open_rows if d.code in PRODUCTION_CODES)
    open_dq = sum(1 for d in open_rows if d.code in DATA_QUALITY_CODES)

    expert_n = (
        db.query(Deviation)
        .filter(
            Deviation.project_id == project.id,
            Deviation.lifecycle.in_(("CONFIRMED", "VERIFIED", "RESOLVED")),
        )
        .count()
    )

    last_frame = (
        db.query(Frame)
        .filter(Frame.project_id == project.id, Frame.captured_at.isnot(None))
        .order_by(Frame.captured_at.desc())
        .first()
    )
    last_obs = last_frame.captured_at.isoformat() if last_frame and last_frame.captured_at else None
    last_run = (
        db.query(InferenceRun)
        .join(Frame, Frame.id == InferenceRun.frame_id)
        .filter(Frame.project_id == project.id, InferenceRun.status == "COMPLETED")
        .order_by(InferenceRun.id.desc())
        .first()
    )
    last_cv = None
    if last_run is not None:
        fr = db.get(Frame, last_run.frame_id)
        if fr and fr.captured_at:
            last_cv = fr.captured_at.isoformat()

    analysis_source = _analysis_source(
        has_schedule=bool(acts),
        has_obs=last_obs is not None,
        expert=expert_n > 0 and open_prod == 0,
    )

    # Статус из evidence — никогда из settings_json.status
    if not acts and not last_obs:
        status, reason, src = "NO_DATA", "Нет активного графика и наблюдений", "NONE"
    elif open_prod >= 3 or max_dev >= 14:
        status, reason, src = (
            "DELAYED",
            f"Открытых производственных сигналов: {open_prod}, макс. отставание {max_dev} дн.",
            "FINDINGS" if open_prod else "SCHEDULE",
        )
    elif open_prod >= 1 or max_dev >= 5 or len(problem) >= 3:
        status, reason, src = (
            "AT_RISK",
            f"Проблемных работ: {len(problem)}, производственных findings: {open_prod}",
            "FINDINGS" if open_prod else "SCHEDULE",
        )
    elif open_dq >= 5 and open_prod == 0 and max_dev == 0:
        status, reason, src = (
            "AT_RISK",
            f"Нужно уточнить данные наблюдений ({open_dq} сигналов качества)",
            "DATA_QUALITY",
        )
    else:
        status, reason, src = "ON_TRACK", "Календарный график без критических открытых рисков", "SCHEDULE"

    last_analysis = "—"
    last_kind = "NONE"
    if version and version.imported_at:
        last_analysis = version.imported_at.strftime("%d.%m.%Y %H:%M")
        last_kind = "SCHEDULE_IMPORT"
    if last_obs:
        last_analysis = last_obs.replace("T", " ")[:16]
        last_kind = "FRAME_CAPTURE"
    if last_cv:
        last_analysis = last_cv.replace("T", " ")[:16]
        last_kind = "CV_INFERENCE"

    freshness = "STALE"
    if last_obs:
        try:
            age = (ao - datetime.fromisoformat(last_obs[:19])).days
            freshness = "FRESH" if age <= 7 else ("AGING" if age <= 30 else "STALE")
        except Exception:
            freshness = "UNKNOWN"
    elif acts:
        freshness = "SCHEDULE_ONLY"

    return ProjectHealth(
        status=status,
        status_reason=reason,
        status_source=src,
        problem_works=len(problem),
        open_findings=open_findings,
        open_production_findings=open_prod,
        open_data_quality_findings=open_dq,
        max_deviation=max_dev,
        works_critical=works_critical,
        works_high=works_high,
        works_medium=works_medium,
        works_normal=works_normal,
        progress=progress,
        progress_source=progress_source,
        last_analysis=last_analysis,
        last_analysis_kind=last_kind,
        last_observation_at=last_obs,
        last_cv_analysis_at=last_cv,
        analysis_source=analysis_source,
        data_freshness=freshness,
        as_of=now,
    )


def health_to_dict(h: ProjectHealth) -> dict[str, Any]:
    return {
        "status": h.status,
        "status_reason": h.status_reason,
        "status_source": h.status_source,
        "problemWorks": h.problem_works,
        "openFindings": h.open_findings,
        "openProductionFindings": h.open_production_findings,
        "openDataQualityFindings": h.open_data_quality_findings,
        "maxDeviation": h.max_deviation,
        "severityWorks": {
            "critical": h.works_critical,
            "high": h.works_high,
            "medium": h.works_medium,
            "normal": h.works_normal,
        },
        "progress": h.progress,
        "progress_source": h.progress_source,
        "lastAnalysis": h.last_analysis,
        "last_analysis_kind": h.last_analysis_kind,
        "lastObservationAt": h.last_observation_at,
        "lastCvAnalysisAt": h.last_cv_analysis_at,
        "analysis_source": h.analysis_source,
        "data_freshness": h.data_freshness,
        "as_of": h.as_of,
    }
