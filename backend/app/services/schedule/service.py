from __future__ import annotations

import io
import json
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import bytes_sha256, get_settings
from app.db.models import ScheduleItem, ScheduleVersion, WorkType
from app.services.knowledge_base.service import load_kb, sync_kb_to_db


REQUIRED_COLUMNS = {"work_name", "planned_start", "planned_finish"}
COLUMN_ALIASES = {
    "work_name": ["work_name", "name", "название", "работа"],
    "planned_start": ["planned_start", "start", "начало", "date_start"],
    "planned_finish": ["planned_finish", "end", "finish", "окончание", "date_end"],
    "work_id": ["work_id", "id", "external_id", "код"],
    "building": ["building", "корпус", "building_hint"],
    "workface": ["workface", "захватка"],
    "floor": ["floor", "этаж"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    lower = {c: str(c).strip().lower() for c in df.columns}
    for canonical, aliases in COLUMN_ALIASES.items():
        for col, low in lower.items():
            if low in aliases:
                rename[col] = canonical
                break
    out = df.rename(columns=rename)
    missing = REQUIRED_COLUMNS - set(out.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    return out


def _parse_dt(value) -> datetime:
    if pd.isna(value):
        raise ValueError("empty datetime")
    parsed = pd.to_datetime(value, utc=False)
    dt = parsed.to_pydatetime()
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def read_schedule_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    bio = io.BytesIO(content)
    if name.endswith(".csv"):
        df = pd.read_csv(bio)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(bio)
    else:
        raise ValueError("supported formats: CSV, XLSX")
    return _normalize_columns(df)


def import_schedule(
    db: Session,
    project_id: int,
    content: bytes,
    filename: str,
    activate: bool = True,
) -> ScheduleVersion:
    sync_kb_to_db(db)
    kb = load_kb()
    df = read_schedule_dataframe(content, filename)

    uploads = get_settings().uploads_dir() / "schedules"
    uploads.mkdir(parents=True, exist_ok=True)
    checksum = bytes_sha256(content)
    stored = uploads / f"p{project_id}_{checksum[:12]}_{Path(filename).name}"
    stored.write_bytes(content)

    if activate:
        db.query(ScheduleVersion).filter(
            ScheduleVersion.project_id == project_id,
            ScheduleVersion.is_active.is_(True),
        ).update({"is_active": False})

    version = ScheduleVersion(
        project_id=project_id,
        source_path=str(stored),
        checksum=checksum,
        is_active=activate,
    )
    db.add(version)
    db.flush()

    wt_by_code = {w.code: w for w in db.query(WorkType).all()}
    for _, row in df.iterrows():
        raw_name = str(row["work_name"]).strip()
        if not raw_name or raw_name.lower() == "nan":
            continue
        start = _parse_dt(row["planned_start"])
        finish = _parse_dt(row["planned_finish"])
        if finish <= start:
            raise ValueError(f"planned_finish must be after planned_start for '{raw_name}'")
        external = str(row["work_id"]).strip() if "work_id" in df.columns and not pd.isna(row.get("work_id")) else f"GEN-{uuid.uuid4().hex[:8]}"
        mapped = kb.map_work_name(raw_name)
        # также явная колонка work_type если есть
        if mapped is None and "work_type" in df.columns and not pd.isna(row.get("work_type")):
            mapped = kb.map_work_name(str(row["work_type"]))
            code = str(row["work_type"]).strip().lower()
            if mapped is None and code in wt_by_code:
                mapped = code
        work_type_id = wt_by_code[mapped].id if mapped and mapped in wt_by_code else None
        building = None
        if "building" in df.columns and not pd.isna(row.get("building")):
            building = str(row["building"]).strip() or None
        db.add(
            ScheduleItem(
                schedule_version_id=version.id,
                external_id=external,
                raw_name=raw_name,
                work_type_id=work_type_id,
                planned_start=start,
                planned_finish=finish,
                building=building,
                workface=str(row["workface"]).strip() if "workface" in df.columns and not pd.isna(row.get("workface")) else None,
                floor=str(row["floor"]).strip() if "floor" in df.columns and not pd.isna(row.get("floor")) else None,
            )
        )
    db.flush()
    return version


def get_active_schedule(db: Session, project_id: int) -> ScheduleVersion | None:
    return (
        db.query(ScheduleVersion)
        .filter(ScheduleVersion.project_id == project_id, ScheduleVersion.is_active.is_(True))
        .order_by(ScheduleVersion.id.desc())
        .first()
    )


def list_schedule_items(db: Session, project_id: int, *, leaf_only: bool = True) -> list[ScheduleItem]:
    version = get_active_schedule(db, project_id)
    if version is None:
        return []
    q = db.query(ScheduleItem).filter(ScheduleItem.schedule_version_id == version.id)
    rows = q.order_by(ScheduleItem.planned_start.asc()).all()
    if leaf_only:
        rows = [r for r in rows if not getattr(r, "is_summary", False) and not getattr(r, "is_milestone", False)]
    return rows


def list_candidates(
    db: Session,
    project_id: int,
    work_type_id: int | None,
    at: datetime,
    *,
    building: str | None = None,
    workface: str | None = None,
    floor: str | None = None,
    before_days: int = 7,
    after_days: int = 7,
) -> list[ScheduleItem]:
    """Кандидаты КСГ до ranking: жёсткие фильтры (версия, leaf, тип, корпус, окно)."""
    from datetime import timedelta

    items = list_schedule_items(db, project_id, leaf_only=True)
    out: list[ScheduleItem] = []
    win_lo = at - timedelta(days=max(0, int(before_days)))
    win_hi = at + timedelta(days=max(0, int(after_days)))
    bnorm = (building or "").strip().lower() or None
    wfnorm = (workface or "").strip().lower() or None
    flnorm = (floor or "").strip().lower() or None
    for item in items:
        if work_type_id is not None and item.work_type_id != work_type_id:
            continue
        if bnorm and item.building and item.building.lower() != bnorm:
            continue
        if wfnorm:
            wf = (getattr(item, "workface", None) or "").strip().lower()
            if wf and wf != wfnorm:
                continue
        if flnorm:
            fl = (getattr(item, "floor", None) or "").strip().lower()
            if fl and fl != flnorm:
                continue
        # Проверка временного окна (soft skip только если обе даты есть и полностью вне)
        ps, pf = item.planned_start, item.planned_finish
        if ps and pf and (pf < win_lo or ps > win_hi):
            # флаг override в payload item, если когда-либо появится
            if not getattr(item, "manual_match_override", False):
                continue
        out.append(item)
    return out


async def import_schedule_upload(db: Session, project_id: int, file: UploadFile) -> ScheduleVersion:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    try:
        return import_schedule(db, project_id, content, file.filename or "schedule.csv")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
