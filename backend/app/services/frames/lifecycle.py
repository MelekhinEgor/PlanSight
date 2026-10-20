"""Жизненный цикл кадров: архив / удаление с защитой evidence."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Deviation, Frame


def frame_is_evidence(db: Session, frame_id: int) -> list[dict[str, Any]]:
    """Найти предупреждения, где кадр указан в evidence_ids / source_frame_ids."""
    hits: list[dict[str, Any]] = []
    fr = db.get(Frame, frame_id)
    if fr is None:
        return []
    for d in db.query(Deviation).filter(Deviation.project_id == fr.project_id).all():
        try:
            ids = json.loads(d.evidence_ids_json or "[]")
        except Exception:
            ids = []
        linked = int(frame_id) in {int(x) for x in ids if x is not None}
        if not linked:
            try:
                details = json.loads(d.details_json or "{}")
                src = details.get("source_frame_ids") or []
                linked = int(frame_id) in {int(x) for x in src if x is not None}
            except Exception:
                linked = False
        if linked:
            hits.append({"deviation_id": d.id, "code": d.code, "lifecycle": d.lifecycle})
    return hits


def archive_or_delete_frame(
    db: Session,
    *,
    project_id: int,
    frame_id: int,
    force: bool = False,
) -> dict[str, Any]:
    """
    Вход: frame_id проекта.
    Выход: статус действия (ARCHIVED / DELETED).

    Правило: кадр в evidence finding нельзя жёстко удалить;
    по умолчанию — ARCHIVED (скрыт из ленты, provenance сохраняется).
    """
    fr = db.get(Frame, frame_id)
    if fr is None or fr.project_id != project_id:
        raise ValueError("frame not found")
    refs = frame_is_evidence(db, frame_id)
    if refs and not force:
        fr.ingest_status = "ARCHIVED"
        db.flush()
        return {
            "frame_id": frame_id,
            "action": "ARCHIVED",
            "reason": "referenced_as_evidence",
            "referenced_by": refs,
            "note_ru": "Кадр скрыт (архив): он является доказательством предупреждения. Жёсткое удаление только с force=true.",
        }
    if refs and force:
        fr.ingest_status = "ARCHIVED"
        db.flush()
        return {
            "frame_id": frame_id,
            "action": "ARCHIVED_FORCED",
            "reason": "evidence_protected",
            "referenced_by": refs,
            "note_ru": "Жёсткое удаление запрещено для evidence-кадров — оставлен ARCHIVED.",
        }
    # Не evidence — удаляем строку БД (файл на диске можно оставить для восстановления)
    fr.ingest_status = "DELETED"
    db.delete(fr)
    db.flush()
    return {
        "frame_id": frame_id,
        "action": "DELETED",
        "referenced_by": [],
        "note_ru": "Кадр удалён из БД (не был в evidence).",
    }
