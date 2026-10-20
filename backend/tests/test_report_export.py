"""Экспорт PDF/DOCX из сохранённого evidence — без CV inference."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session


def _first_deviation(db: Session):
    from app.db.models import Deviation

    return db.query(Deviation).order_by(Deviation.id.asc()).first()


def test_finding_report_dto_no_inference(db_session: Session):
    from app.services.reporting import report_dto as mod

    d = _first_deviation(db_session)
    if d is None:
        pytest.skip("нет Deviation")

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "ultralytics" not in src
    assert "run_inference" not in src

    with patch("app.services.reporting.report_dto.build_decision_trace") as tr:
        tr.return_value = {
            "trace_status": "OK",
            "user_logic": [],
            "matching": {"assignment_status": "UNMATCHED"},
            "provenance": {"re_inferred": False},
        }
        dto = mod.build_single_finding_report_dto(db_session, d.project_id, d.id)
    assert dto["report_type"] == "finding"
    assert dto["finding"]["deviation_id"] == d.id
    assert "disclaimer" in dto
    # evidence_ids только Frame.id
    for fid in dto["finding"].get("evidence_frame_ids") or []:
        assert isinstance(fid, int)


def test_ambiguous_match_hides_schedule_as_fact(db_session: Session):
    from app.db.models import Deviation
    from app.services.reporting.report_dto import build_finding_report_section

    d = _first_deviation(db_session)
    if d is None:
        pytest.skip("нет Deviation")
    details = json.loads(d.details_json or "{}")
    details["match_status"] = "AMBIGUOUS"
    d.details_json = json.dumps(details, ensure_ascii=False)
    db_session.commit()

    section = build_finding_report_section(db_session, d.project_id, d.id)
    assert section["match_status"] == "AMBIGUOUS"
    assert section["schedule_item"] is None
    assert section.get("schedule_item_refused_reason")


def test_export_pdf_docx_files(db_session: Session, tmp_path: Path, monkeypatch):
    from app.core import config as cfg
    from app.services.reporting.export_service import generate_finding_export, generate_project_export

    d = _first_deviation(db_session)
    if d is None:
        pytest.skip("нет Deviation")

    # Направить отчёты во временную папку
    settings = cfg.get_settings()
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)

    pdf_meta = generate_finding_export(db_session, d.project_id, d.id, fmt="pdf")
    assert pdf_meta["format"] == "pdf"
    assert Path(pdf_meta["path"]).exists()
    assert pdf_meta["checksum_sha256"]
    assert pdf_meta["re_inferred"] is False

    docx_meta = generate_finding_export(db_session, d.project_id, d.id, fmt="docx")
    assert Path(docx_meta["path"]).exists()

    proj = generate_project_export(
        db_session,
        d.project_id,
        fmt="pdf",
        detail="brief",
        include_false_positives=True,
        include_no_data=True,
    )
    assert Path(proj["path"]).exists()
    assert "finding_ids" in proj


def test_evidence_ids_are_frame_ids_only(db_session: Session):
    from app.db.models import Frame
    from app.services.reporting.report_dto import build_finding_report_section

    d = _first_deviation(db_session)
    if d is None:
        pytest.skip("нет Deviation")
    section = build_finding_report_section(db_session, d.project_id, d.id)
    for fid in section.get("evidence_frame_ids") or []:
        fr = db_session.get(Frame, int(fid))
        # кадр может быть удалён — но id должен быть int Frame.id, не hypothesis
        assert isinstance(fid, int)
        if fr is not None:
            assert fr.project_id == d.project_id
