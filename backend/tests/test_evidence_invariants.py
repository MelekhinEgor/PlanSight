"""Бизнес-инварианты evidence-first (SPEC §4, §16.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session


def _first_cv_finding(db: Session):
    from app.db.models import Deviation

    rows = (
        db.query(Deviation)
        .filter(Deviation.lifecycle != "RESOLVED")
        .order_by(Deviation.id.asc())
        .all()
    )
    for d in rows:
        import json

        details = json.loads(d.details_json or "{}")
        sk = details.get("signal_kind") or ""
        eids = details.get("evidence_frame_ids") or []
        if not eids:
            try:
                eids = json.loads(d.evidence_ids_json or "[]")
            except Exception:
                eids = []
        if sk in ("CV_VERIFIED_FINDING", "SYNTHETIC_DEMO_FINDING") or eids:
            return d
    return rows[0] if rows else None


def test_evidence_frames_belong_to_same_project(db_session: Session):
    from app.db.models import Frame
    from app.services.product.overview import deviation_evidence

    d = _first_cv_finding(db_session)
    if d is None:
        pytest.skip("нет Deviation в БД")
    payload = deviation_evidence(db_session, d.project_id, d.id)
    for fr in payload.get("frames") or []:
        row = db_session.get(Frame, int(fr["id"]))
        assert row is not None
        assert row.project_id == d.project_id


def test_foreign_frame_ids_dropped_from_evidence(db_session: Session):
    import json

    from app.db.models import Deviation, Frame
    from app.services.product.overview import deviation_evidence

    d = _first_cv_finding(db_session)
    if d is None:
        pytest.skip("нет Deviation в БД")
    other = (
        db_session.query(Frame)
        .filter(Frame.project_id != d.project_id)
        .order_by(Frame.id.asc())
        .first()
    )
    if other is None:
        pytest.skip("нет кадра другого проекта")
    details = json.loads(d.details_json or "{}")
    details["evidence_frame_ids"] = [other.id]
    d.details_json = json.dumps(details, ensure_ascii=False)
    d.evidence_ids_json = json.dumps([other.id])
    db_session.commit()

    payload = deviation_evidence(db_session, d.project_id, d.id)
    ids = {int(f["id"]) for f in payload.get("frames") or []}
    assert other.id not in ids


def test_decision_trace_reads_saved_evidence_only(db_session: Session):
    """Trace собирается из deviation_evidence / БД; модуль не импортирует YOLO."""
    import app.services.product.decision_trace as dt_mod

    d = _first_cv_finding(db_session)
    if d is None:
        pytest.skip("нет Deviation в БД")

    src = Path(dt_mod.__file__).read_text(encoding="utf-8")
    assert "ultralytics" not in src
    assert "from app.services.cv" not in src
    assert "import torch" not in src
    assert "run_inference" not in src

    with patch.object(dt_mod, "deviation_evidence", wraps=dt_mod.deviation_evidence) as mocked:
        trace = dt_mod.build_decision_trace(db_session, d.project_id, d.id)
        assert mocked.called
    assert isinstance(trace, dict)
    assert "user_logic" in trace or "rule" in trace or "source" in trace


def test_human_verdict_separate_and_survives(db_session: Session):
    from app.db.models import Deviation, HumanVerdict
    from app.services.product.overview import deviation_evidence
    from app.services.verification.service import submit_verdict

    d = _first_cv_finding(db_session)
    if d is None:
        pytest.skip("нет Deviation в БД")
    before_code = d.code
    submit_verdict(
        db_session,
        target_type="deviation",
        target_id=d.id,
        verdict="confirm",
        correction={"note": "pytest"},
        user_id="pytest",
    )
    db_session.commit()

    d2 = db_session.get(Deviation, d.id)
    assert d2 is not None
    assert d2.code == before_code  # model output не переписан
    hv = (
        db_session.query(HumanVerdict)
        .filter(HumanVerdict.target_type == "deviation", HumanVerdict.target_id == d.id)
        .order_by(HumanVerdict.id.desc())
        .first()
    )
    assert hv is not None
    assert hv.verdict == "confirm"

    payload = deviation_evidence(db_session, d.project_id, d.id)
    hist = payload.get("verdict_history") or []
    assert any((h.get("verdict") == "confirm") for h in hist if isinstance(h, dict))


def test_api_deviation_evidence_and_trace(client):
    from app.db import models as models_mod

    db = models_mod.SessionLocal()
    try:
        d = _first_cv_finding(db)
        if d is None:
            pytest.skip("нет Deviation в БД")
        pid, did = d.project_id, d.id
    finally:
        db.close()

    r = client.get(f"/api/projects/{pid}/deviations/{did}/evidence")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "frames" in body
    assert "verdict_history" in body

    t = client.get(f"/api/projects/{pid}/deviations/{did}/decision-trace")
    assert t.status_code == 200, t.text
    assert isinstance(t.json(), dict)


def test_poor_quality_limitation_labels_exist():
    """Плохое качество/разрыв покрытия маркируются ограничениями, а не «техника отсутствует»."""
    from app.services.product.ru_labels import limitations_ru

    lims = limitations_ru(["POOR_FRAME_QUALITY", "CAMERA_COVERAGE_GAP"])
    assert isinstance(lims, list)
    assert len(lims) >= 1
