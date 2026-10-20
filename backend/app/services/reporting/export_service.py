"""Оркестрация экспорта PDF/DOCX через JobRun (без повторного inference)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Deviation, Project
from app.services.jobs.queue import get_job, submit_job, submit_job_async
from app.services.reporting.report_dto import (
    build_project_report_dto,
    build_single_finding_report_dto,
)
from app.services.reporting.render_docx import render_finding_docx, render_project_docx
from app.services.reporting.render_pdf import render_finding_pdf, render_project_pdf


def _safe_name(text: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE)
    return cleaned.strip("_")[:80] or "report"


def reports_dir(project_id: int) -> Path:
    root = get_settings().data_dir() / "reports" / f"project_{project_id}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _assert_project(db: Session, project_id: int) -> None:
    if not db.get(Project, project_id):
        raise ValueError("project not found")


def _assert_deviation(db: Session, project_id: int, deviation_id: int) -> None:
    d = db.get(Deviation, deviation_id)
    if not d or d.project_id != project_id:
        raise ValueError("deviation not found")


def generate_finding_export(
    db: Session,
    project_id: int,
    deviation_id: int,
    *,
    fmt: str = "pdf",
    author: str | None = None,
    include_all_frames: bool = True,
) -> dict[str, Any]:
    _assert_project(db, project_id)
    _assert_deviation(db, project_id, deviation_id)
    fmt = fmt.lower().strip()
    if fmt not in ("pdf", "docx"):
        raise ValueError("format must be pdf or docx")

    dto = build_single_finding_report_dto(
        db,
        project_id,
        deviation_id,
        include_all_frames=include_all_frames,
        author=author,
    )
    report_id = str(uuid.uuid4())
    date_tag = datetime.utcnow().strftime("%Y%m%d")
    filename = f"PlanSight_finding_{deviation_id}_{date_tag}.{fmt}"
    out = reports_dir(project_id) / f"{report_id}.{fmt}"
    if fmt == "pdf":
        render_finding_pdf(dto, out)
    else:
        render_finding_docx(dto, out)

    meta = {
        "report_id": report_id,
        "report_type": "finding",
        "project_id": project_id,
        "deviation_id": deviation_id,
        "format": fmt,
        "filename": filename,
        "path": str(out),
        "checksum_sha256": _checksum(out),
        "generated_at": dto.get("generated_at"),
        "finding_ids": [str(deviation_id)],
        "re_inferred": False,
        "dto_snapshot": {
            "match_status": (dto.get("finding") or {}).get("match_status"),
            "trace_status": ((dto.get("finding") or {}).get("decision_trace") or {}).get("trace_status"),
            "frames": len((dto.get("finding") or {}).get("frames") or []),
        },
    }
    meta_path = reports_dir(project_id) / f"{report_id}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def generate_project_export(
    db: Session,
    project_id: int,
    *,
    fmt: str = "pdf",
    date_from: str | None = None,
    date_to: str | None = None,
    include_false_positives: bool = True,
    include_no_data: bool = True,
    detail: str = "full",
    max_frames_per_finding: int = 3,
    include_all_frames: bool = False,
    author: str | None = None,
) -> dict[str, Any]:
    _assert_project(db, project_id)
    fmt = fmt.lower().strip()
    if fmt not in ("pdf", "docx"):
        raise ValueError("format must be pdf or docx")

    dto = build_project_report_dto(
        db,
        project_id,
        date_from=date_from,
        date_to=date_to,
        include_false_positives=include_false_positives,
        include_no_data=include_no_data,
        detail=detail,
        max_frames_per_finding=max_frames_per_finding,
        include_all_frames=include_all_frames,
        author=author,
    )
    report_id = str(uuid.uuid4())
    period = f"{date_from or 'all'}_{date_to or 'all'}"
    filename = f"PlanSight_{_safe_name(str((dto.get('project') or {}).get('name') or project_id))}_deviations_{_safe_name(period)}_{report_id[:8]}.{fmt}"
    out = reports_dir(project_id) / f"{report_id}.{fmt}"
    if fmt == "pdf":
        render_project_pdf(dto, out)
    else:
        render_project_docx(dto, out)

    meta = {
        "report_id": report_id,
        "report_type": "project",
        "project_id": project_id,
        "format": fmt,
        "filename": filename,
        "path": str(out),
        "checksum_sha256": _checksum(out),
        "generated_at": dto.get("generated_at"),
        "finding_ids": [r.get("finding_id") for r in (dto.get("registry") or [])],
        "summary": dto.get("summary"),
        "filters": dto.get("filters"),
        "re_inferred": False,
    }
    meta_path = reports_dir(project_id) / f"{report_id}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def enqueue_project_report(db_factory, project_id: int, payload: dict[str, Any], *, async_mode: bool = True):
    """db_factory: callable() -> Session, чтобы job открыл свою сессию."""

    def _work() -> dict[str, Any]:
        db = db_factory()
        try:
            return generate_project_export(
                db,
                project_id,
                fmt=str(payload.get("format") or "pdf"),
                date_from=payload.get("date_from"),
                date_to=payload.get("date_to"),
                include_false_positives=bool(payload.get("include_false_positives", True)),
                include_no_data=bool(payload.get("include_no_data", True)),
                detail=str(payload.get("detail") or "full"),
                max_frames_per_finding=int(payload.get("max_frames_per_finding") or 3),
                include_all_frames=bool(payload.get("include_all_frames", False)),
                author=payload.get("author"),
            )
        finally:
            db.close()

    if async_mode:
        return submit_job_async("project_report", _work, stage="report")
    return submit_job("project_report", _work, stage="report")


def enqueue_finding_report(db_factory, project_id: int, deviation_id: int, payload: dict[str, Any], *, async_mode: bool = False):
    def _work() -> dict[str, Any]:
        db = db_factory()
        try:
            return generate_finding_export(
                db,
                project_id,
                deviation_id,
                fmt=str(payload.get("format") or "pdf"),
                author=payload.get("author"),
                include_all_frames=bool(payload.get("include_all_frames", True)),
            )
        finally:
            db.close()

    if async_mode:
        return submit_job_async("finding_report", _work, stage="report")
    return submit_job("finding_report", _work, stage="report")


def load_report_meta(project_id: int, report_id: str) -> dict[str, Any] | None:
    meta_path = reports_dir(project_id) / f"{report_id}.json"
    if not meta_path.exists():
        # fallback: job result
        job = get_job(report_id)
        if job and isinstance(job.result, dict) and job.result.get("report_id"):
            return job.result
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_project_reports(project_id: int, limit: int = 50) -> list[dict[str, Any]]:
    root = reports_dir(project_id)
    items: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items


def resolve_download(project_id: int, report_id: str) -> tuple[Path, str, str]:
    meta = load_report_meta(project_id, report_id)
    if not meta or int(meta.get("project_id") or -1) != int(project_id):
        raise ValueError("report not found")
    path = Path(str(meta.get("path") or ""))
    if not path.exists():
        # безопасный путь только внутри reports_dir
        alt = reports_dir(project_id) / f"{report_id}.{meta.get('format') or 'pdf'}"
        if alt.exists():
            path = alt
        else:
            raise ValueError("report file missing")
    # path traversal guard
    root = reports_dir(project_id).resolve()
    if root not in path.resolve().parents and path.resolve() != root:
        # allow file directly in root
        if path.resolve().parent != root:
            raise ValueError("invalid report path")
    return path, str(meta.get("filename") or path.name), str(meta.get("format") or path.suffix.lstrip("."))
