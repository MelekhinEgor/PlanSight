"""V6 Sprint F / Stage 5b — реестр job с опциональным background worker + durability в SQLite.

По умолчанию submit_job синхронный (совместимость API).
submit_job_async ставит работу в очередь daemon-потока.
Строки job также пишутся в job_run, чтобы GET переживал рестарт процесса.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str = "QUEUED"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: str | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    mode: str = "sync"  # sync | async_thread


_JOBS: dict[str, JobRecord] = {}
_LOCK = threading.Lock()
_LATENCY: dict[str, list[float]] = {
    "yolo": [],
    "activity": [],
    "matching": [],
    "llm": [],
    "full_job": [],
}
_WORKER_NOTES = {
    "persistence": "sqlite_job_run",
    "broker": "none",
    "survives_restart": True,
    "note": "status/result in job_run; in-flight QUEUED lost on hard kill mid-run",
}


def record_latency(stage: str, ms: float) -> None:
    with _LOCK:
        bucket = _LATENCY.setdefault(stage, [])
        bucket.append(float(ms))
        if len(bucket) > 500:
            del bucket[: len(bucket) - 500]


def latency_summary() -> dict[str, Any]:
    with _LOCK:
        snapshot = {k: list(v) for k, v in _LATENCY.items()}
    out: dict[str, Any] = {}
    for stage, vals in snapshot.items():
        if not vals:
            out[stage] = {"n": 0, "p50_ms": None, "p95_ms": None}
            continue
        s = sorted(vals)

        def pct(p: float) -> float:
            i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
            return s[i]

        out[stage] = {
            "n": len(s),
            "p50_ms": pct(50),
            "p95_ms": pct(95),
            "mean_ms": statistics.fmean(s),
        }
    out["_worker"] = dict(_WORKER_NOTES)
    return out


def _persist(job: JobRecord) -> None:
    """Запись best-effort в SQLite; не ломает выполнение job."""
    try:
        from app.db.models import JobRun, SessionLocal

        db = SessionLocal()
        try:
            row = db.get(JobRun, job.id)
            if row is None:
                row = JobRun(id=job.id, kind=job.kind)
                db.add(row)
            row.kind = job.kind
            row.status = job.status
            row.mode = job.mode
            row.error = job.error
            row.result_json = json.dumps(job.result or {}, ensure_ascii=False, default=str)
            row.timings_json = json.dumps(job.timings_ms or {}, ensure_ascii=False)
            if job.finished_at:
                try:
                    row.finished_at = datetime.fromisoformat(job.finished_at)
                except ValueError:
                    row.finished_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _load_from_db(job_id: str) -> JobRecord | None:
    try:
        from app.db.models import JobRun, SessionLocal

        db = SessionLocal()
        try:
            row = db.get(JobRun, job_id)
            if not row:
                return None
            try:
                result = json.loads(row.result_json or "{}")
            except Exception:
                result = {}
            try:
                timings = json.loads(row.timings_json or "{}")
            except Exception:
                timings = {}
            return JobRecord(
                id=row.id,
                kind=row.kind,
                status=row.status,
                created_at=row.created_at.isoformat() if row.created_at else "",
                finished_at=row.finished_at.isoformat() if row.finished_at else None,
                error=row.error,
                result=result if isinstance(result, dict) else {},
                timings_ms=timings if isinstance(timings, dict) else {},
                mode=row.mode or "sync",
            )
        finally:
            db.close()
    except Exception:
        return None


def _run_job(job: JobRecord, fn: Callable[[], dict[str, Any]], stage: str) -> None:
    job.status = "RUNNING"
    _persist(job)
    t0 = time.perf_counter()
    try:
        job.result = fn() or {}
        job.status = "COMPLETED"
    except Exception as exc:  # noqa: BLE001 — surface to job record
        job.status = "FAILED"
        job.error = str(exc)
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        job.timings_ms[stage] = ms
        record_latency(stage, ms)
        job.finished_at = datetime.utcnow().isoformat()
        _persist(job)


def submit_job(kind: str, fn: Callable[[], dict[str, Any]], *, stage: str = "full_job") -> JobRecord:
    """Синхронное выполнение — контракт для существующих вызовов/тестов без изменений."""
    job = JobRecord(id=str(uuid.uuid4()), kind=kind, status="RUNNING", mode="sync")
    with _LOCK:
        _JOBS[job.id] = job
    _persist(job)
    _run_job(job, fn, stage)
    return job


def submit_job_async(
    kind: str,
    fn: Callable[[], dict[str, Any]],
    *,
    stage: str = "full_job",
) -> JobRecord:
    """Очередь в daemon-потоке; опрос через get_job. Результат в job_run."""
    job = JobRecord(id=str(uuid.uuid4()), kind=kind, status="QUEUED", mode="async_thread")
    with _LOCK:
        _JOBS[job.id] = job
    _persist(job)

    def _worker() -> None:
        _run_job(job, fn, stage)

    t = threading.Thread(target=_worker, name=f"plansight-job-{job.id[:8]}", daemon=True)
    t.start()
    return job


def get_job(job_id: str) -> JobRecord | None:
    with _LOCK:
        mem = _JOBS.get(job_id)
    if mem is not None:
        return mem
    return _load_from_db(job_id)


def list_jobs(limit: int = 50) -> list[JobRecord]:
    with _LOCK:
        rows = sorted(_JOBS.values(), key=lambda j: j.created_at, reverse=True)
    if rows:
        return rows[: max(1, min(limit, 200))]
    # запасной путь: недавние из БД
    try:
        from app.db.models import JobRun, SessionLocal

        db = SessionLocal()
        try:
            db_rows = db.query(JobRun).order_by(JobRun.created_at.desc()).limit(limit).all()
            out: list[JobRecord] = []
            for row in db_rows:
                loaded = _load_from_db(row.id)
                if loaded:
                    out.append(loaded)
            return out
        finally:
            db.close()
    except Exception:
        return []
