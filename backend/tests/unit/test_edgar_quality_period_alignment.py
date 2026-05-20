from __future__ import annotations

from datetime import date

from app.models.institutions import Filing13F, InstitutionManager
from app.services.edgar_quality import QualityReport, _check_period_alignment


def _manager(db_session) -> InstitutionManager:
    mgr = InstitutionManager(
        canonical_name="Period Alignment Test Manager",
        legal_name="Period Alignment Test Manager",
        edgar_legal_name="Period Alignment Test Manager",
        cik="0009999999",
        status="active",
        match_status="confirmed",
    )
    db_session.add(mgr)
    db_session.flush()
    return mgr


def _filing(db_session, manager, accession, *, period: date, filed: date) -> None:
    db_session.add(
        Filing13F(
            manager_id=manager.id,
            accession_no=accession,
            accession_number=accession,
            cik=manager.cik,
            form_type="13F-HR",
            period_of_report=period,
            filed_at=filed,
        )
    )
    db_session.flush()


def test_period_alignment_passes_normal_prior_quarter_filing(db_session):
    """A 13F filed in 2026-Q1 reporting the 2025-Q4 quarter-end is normal —
    it must not raise a warning (the old check did, on every 13F)."""
    db_session.query(Filing13F).delete()
    db_session.flush()
    mgr = _manager(db_session)
    _filing(
        db_session, mgr, "0000000000-26-000001",
        period=date(2025, 12, 31), filed=date(2026, 2, 14),
    )

    report = QualityReport()
    _check_period_alignment(db_session, report, "2026-Q1")

    assert report.warnings == []
    pa = [i for i in report.issues if i.check == "period_alignment"]
    assert pa and all(i.severity == "info" for i in pa)


def test_period_alignment_flags_late_filing_as_info_not_warning(db_session):
    """A 13F filed in 2026-Q1 reporting an older period (2025-Q3) is a late
    filing — surfaced as info, never a warning, so it cannot block readiness."""
    db_session.query(Filing13F).delete()
    db_session.flush()
    mgr = _manager(db_session)
    _filing(
        db_session, mgr, "0000000000-26-000002",
        period=date(2025, 9, 30), filed=date(2026, 1, 20),
    )

    report = QualityReport()
    _check_period_alignment(db_session, report, "2026-Q1")

    assert report.warnings == []
    flagged = [
        i for i in report.issues
        if i.check == "period_alignment" and i.accession_no == "0000000000-26-000002"
    ]
    assert len(flagged) == 1
    assert flagged[0].severity == "info"
