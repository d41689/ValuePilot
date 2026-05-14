"""13F-1B-05: Parse Run Audit, Reparse, Watchdog, and Idempotent Ingestion tests.

Tests cover:
- Reparse creates new current parse_run and retains old holdings.
- Stage 2 failure leaves old current parse_run unchanged.
- Failed parse_run persists with error field.
- Watchdog marks stale running parse_runs as abandoned.
- Succeeded accession skip when parser/fingerprint version matches.
- Succeeded accession reparsed when fingerprint_version differs.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import count

import pytest

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    NoIndexExpectedDate,
    ParseRun13F,
    RawSourceDocument,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CIK_SEQ = count(8800000000)


def _clear(session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    session.query(OraclesLensScoreComponent).delete()
    session.query(OraclesLensSignal).delete()
    session.query(Holding13F).delete()
    session.query(ParseRun13F).delete()
    session.query(Filing13F).delete()
    session.query(RawSourceDocument).delete()
    session.query(NoIndexExpectedDate).delete()
    session.query(InstitutionManagerCikReviewEvent).delete()
    session.query(InstitutionManager).delete()
    session.flush()


def _manager(session, *, cik: str | None = None) -> InstitutionManager:
    cik = cik or str(next(_CIK_SEQ)).zfill(10)
    m = InstitutionManager(
        canonical_name=f"Reparse Manager {cik}",
        legal_name=f"Reparse Manager {cik}",
        edgar_legal_name=f"Reparse Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    session.add(m)
    session.flush()
    return m


def _hr_filing(session, manager: InstitutionManager, accession: str) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        filing_date=date(2024, 5, 15),
        accepted_at=datetime(2024, 5, 15, 17, tzinfo=timezone.utc),
        report_quarter="2024-Q1",
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True,
        parse_status="pending",
        report_type="holdings_report",
        coverage_completeness="complete",
    )
    session.add(filing)
    session.flush()
    return filing


def _minimal_infotable() -> bytes:
    return b"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>8000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>50000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>50000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>"""


# ---------------------------------------------------------------------------
# Test: Reparse creates new current parse_run and retains old holdings
# ---------------------------------------------------------------------------

def test_reparse_accession_creates_new_current_parse_run(db_session):
    """reparse_accession creates a second parse_run that is_current and keeps old holdings."""
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing, reparse_accession

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005001")

    # First ingest
    r1 = ingest_holdings_for_filing(db_session, filing, _minimal_infotable())
    run1_id = r1["parse_run_id"]

    # Reparse — pass infotable_bytes directly (no raw doc stored in unit tests)
    r2 = reparse_accession(db_session, filing.accession_number, infotable_bytes=_minimal_infotable())
    run2_id = r2["parse_run_id"]

    assert run2_id != run1_id, "Reparse must create a new parse_run, not reuse the old one"

    run1 = db_session.get(ParseRun13F, run1_id)
    run2 = db_session.get(ParseRun13F, run2_id)
    assert run1 is not None
    assert run2 is not None

    # After reparse, run2 is current; run1 is not
    assert run2.is_current is True
    assert run1.is_current is False
    assert run2.status == "succeeded"


def test_reparse_retains_old_holdings(db_session):
    """Old holdings from run1 survive after reparse; new holdings exist under run2."""
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing, reparse_accession

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005002")

    r1 = ingest_holdings_for_filing(db_session, filing, _minimal_infotable())
    run1_id = r1["parse_run_id"]

    r2 = reparse_accession(db_session, filing.accession_number, infotable_bytes=_minimal_infotable())
    run2_id = r2["parse_run_id"]

    # Holdings from run1 must not be deleted
    old_holdings = db_session.query(Holding13F).filter_by(parse_run_id=run1_id).all()
    new_holdings = db_session.query(Holding13F).filter_by(parse_run_id=run2_id).all()

    assert len(old_holdings) == 1, "Old holdings from run1 must be retained"
    assert len(new_holdings) == 1, "New holdings must be created under run2"


# ---------------------------------------------------------------------------
# Test: Stage 2 failure leaves old current parse_run unchanged
# ---------------------------------------------------------------------------

def test_reparse_stage2_failure_leaves_old_current_unchanged(db_session):
    """If holdings bulk insert fails, the old current parse_run must remain current."""
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing, reparse_accession

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005003")

    r1 = ingest_holdings_for_filing(db_session, filing, _minimal_infotable())
    run1_id = r1["parse_run_id"]

    # Simulate stage-2 failure by passing corrupt infotable bytes to reparse.
    # The exception must propagate; we catch it here only to continue the test.
    with pytest.raises(Exception):
        reparse_accession(db_session, filing.accession_number, infotable_bytes=b"not valid xml")

    # Old run must still be current
    db_session.expire_all()
    run1 = db_session.get(ParseRun13F, run1_id)
    assert run1.is_current is True, "Old current parse_run must survive a failed reparse"


def test_failed_reparse_parse_run_has_error(db_session):
    """A failed reparse creates a parse_run with status=failed and error set."""
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing, reparse_accession

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005004")

    ingest_holdings_for_filing(db_session, filing, _minimal_infotable())

    with pytest.raises(Exception):
        reparse_accession(db_session, filing.accession_number, infotable_bytes=b"BAD XML")

    db_session.expire_all()
    runs = (
        db_session.query(ParseRun13F)
        .filter_by(accession_number=filing.accession_number)
        .order_by(ParseRun13F.id)
        .all()
    )
    # At least one failed run must exist
    failed_runs = [r for r in runs if r.status == "failed"]
    assert len(failed_runs) >= 1, "Failed parse_run must be persisted"
    assert failed_runs[-1].error is not None, "Failed parse_run must have error set"


# ---------------------------------------------------------------------------
# Test: Watchdog marks stale running parse_runs as abandoned
# ---------------------------------------------------------------------------

def test_watchdog_marks_stale_running_parse_run_abandoned(db_session):
    """Watchdog marks running parse_runs whose lease_expires_at is in the past as abandoned."""
    from app.services.thirteenf_job_worker import mark_stale_parse_runs_abandoned

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005010")

    # Create a stale running parse_run (started long ago, no is_current)
    now = datetime.now(timezone.utc)
    stale_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="v1",
        fingerprint_version="v1",
        status="running",
        is_current=False,
        started_at=now - timedelta(hours=2),
    )
    db_session.add(stale_run)
    db_session.flush()

    result = mark_stale_parse_runs_abandoned(db_session, now=now, timeout_seconds=300)

    db_session.expire_all()
    run = db_session.get(ParseRun13F, stale_run.id)
    assert run.status == "abandoned"
    assert result["abandoned"] >= 1


def test_watchdog_does_not_abandon_fresh_running_parse_run(db_session):
    """Watchdog does not abandon a running parse_run that is still within timeout."""
    from app.services.thirteenf_job_worker import mark_stale_parse_runs_abandoned

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005011")

    now = datetime.now(timezone.utc)
    fresh_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="v1",
        fingerprint_version="v1",
        status="running",
        is_current=False,
        started_at=now - timedelta(seconds=30),  # Very fresh
    )
    db_session.add(fresh_run)
    db_session.flush()

    mark_stale_parse_runs_abandoned(db_session, now=now, timeout_seconds=300)

    db_session.expire_all()
    run = db_session.get(ParseRun13F, fresh_run.id)
    assert run.status == "running", "Fresh running parse_run must not be abandoned"


# ---------------------------------------------------------------------------
# Test: Idempotent skip — succeeded accession skips re-ingest
# ---------------------------------------------------------------------------

def test_ingest_skips_succeeded_accession_with_matching_fingerprint_version(db_session):
    """If a current parse_run exists with matching fingerprint_version, skip ingest."""
    from app.services.thirteenf_holdings_ingest import (
        FINGERPRINT_VERSION,
        ingest_holdings_for_filing,
        ingest_if_needed,
    )

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005020")

    # First ingest
    r1 = ingest_holdings_for_filing(db_session, filing, _minimal_infotable())

    # Second call with same fingerprint version → skip
    r2 = ingest_if_needed(db_session, filing, _minimal_infotable())

    assert r2["skipped"] is True
    assert r2["parse_run_id"] == r1["parse_run_id"], "Must return existing parse_run_id when skipped"

    # Only one parse_run must exist
    runs = db_session.query(ParseRun13F).filter_by(accession_number=filing.accession_number).all()
    assert len(runs) == 1


def test_ingest_reparsed_when_fingerprint_version_differs(db_session):
    """If the current parse_run has a stale fingerprint_version, reparse is triggered."""
    from app.services.thirteenf_holdings_ingest import (
        FINGERPRINT_VERSION,
        ingest_holdings_for_filing,
        ingest_if_needed,
    )

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001893830-24-005021")

    # First ingest; then artificially downgrade the fingerprint_version to simulate stale version
    r1 = ingest_holdings_for_filing(db_session, filing, _minimal_infotable())
    run1 = db_session.get(ParseRun13F, r1["parse_run_id"])
    run1.fingerprint_version = "v0"  # Stale version
    db_session.flush()

    # ingest_if_needed must reparse because fingerprint_version != FINGERPRINT_VERSION
    r2 = ingest_if_needed(db_session, filing, _minimal_infotable())

    assert r2.get("skipped") is not True, "Must not skip when fingerprint_version is stale"
    assert r2["parse_run_id"] != r1["parse_run_id"], "Must create a new parse_run"

    db_session.expire_all()
    run1_refreshed = db_session.get(ParseRun13F, r1["parse_run_id"])
    run2 = db_session.get(ParseRun13F, r2["parse_run_id"])
    assert run2.is_current is True
    assert run1_refreshed.is_current is False
