"""T3 rollout — verification invariants (failure injection) + lock conflict.

The dev rollout passing on healthy data proves nothing about the guardrails, so
these inject each failure state and assert it is caught, and prove a conflicting
locked job aborts the rollout.
"""
from datetime import date, datetime, timezone

import pytest

from app.models.institutions import Filing13F, Holding13F, InstitutionManager, JobRun, ParseRun13F
from app.services.thirteenf_attribution_rollout import (
    RolloutConflictError,
    run_attribution_rollout,
    verify_attribution_rollout,
)

_CIK = iter(range(9300001, 9300999))


def _manager(db):
    cik = str(next(_CIK)).zfill(10)
    m = InstitutionManager(canonical_name=f"M{cik}", legal_name=f"M{cik}", cik=cik,
                           status="active", match_status="confirmed")
    db.add(m); db.flush()
    return m


def _filing(db, manager):
    f = Filing13F(
        manager_id=manager.id, accession_no=f"A{manager.id}", accession_number=f"A{manager.id}",
        cik=manager.cik, period_of_report=date(2026, 3, 31), filed_at=date(2026, 5, 14),
        filing_date=date(2026, 5, 14), form_type="13F-HR", report_type="holdings_report",
        coverage_completeness="complete", coverage_type="normal", report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31), is_active_for_manager_period=True, parse_status="succeeded",
        amendment_status="no_amendments_seen",
    )
    db.add(f); db.flush()
    return f


def _holding(db, filing, *, discretion, status, cusip="111111111"):
    run = ParseRun13F(accession_number=filing.accession_number, parser_version="t",
                      status="succeeded", is_current=True)
    db.add(run); db.flush()
    h = Holding13F(
        filing_id=filing.id, parse_run_id=run.id, manager_id=filing.manager_id,
        accession_number=filing.accession_number, report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date, row_fingerprint=filing.accession_number + cusip,
        holding_row_fingerprint=filing.accession_number + cusip + "v1", cusip=cusip,
        issuer_name="X", value_thousands=1, value_usd=1000, shares=10, ssh_prnamt=10,
        ssh_prnamt_type="SH", investment_discretion=discretion, holding_attribution_status=status,
        cusip_mapping_status="unresolved",
    )
    db.add(h); db.flush()
    return h


def test_verify_passes_on_healthy_direct_data(db_session):
    _holding(db_session, _filing(db_session, _manager(db_session)), discretion="SOLE", status="direct")
    assert verify_attribution_rollout(db_session) == []


def test_verify_fails_on_dfnd_left_non_direct(db_session):
    """The exact original bug: a DFND/no-Column-7 holding left `unresolved` must
    be caught — it is NOT reported_for_other/shared, so a legacy-only check misses it."""
    _holding(db_session, _filing(db_session, _manager(db_session)), discretion="DFND", status="unresolved")
    failures = verify_attribution_rollout(db_session)
    assert any("not 'direct'" in f for f in failures)


def test_verify_fails_on_zero_direct_manager(db_session):
    _holding(db_session, _filing(db_session, _manager(db_session)), discretion="XYZ", status="unresolved")
    failures = verify_attribution_rollout(db_session)
    assert any("zero direct holdings" in f for f in failures)


def test_verify_fails_on_legacy_status(db_session):
    _holding(db_session, _filing(db_session, _manager(db_session)), discretion="DFND", status="reported_for_other")
    failures = verify_attribution_rollout(db_session)
    assert any("legacy reported_for_other/shared" in f for f in failures)


def test_rollout_aborts_on_active_lock_conflict(db_session):
    """A conflicting compute_ownership_changes job already holding the per-quarter
    lock must abort the rollout (RolloutConflictError), not race it."""
    now = datetime.now(timezone.utc)
    db_session.add(JobRun(
        job_type="compute_ownership_changes", status="running", trigger_source="scheduler",
        dedupe_key="compute_ownership_changes:2026-Q1", lock_key="compute_ownership_changes:2026-Q1",
        quarter="2026-Q1", started_at=now, heartbeat_at=now,
        input_json={"job_type": "compute_ownership_changes", "quarter": "2026-Q1"},
    ))
    db_session.flush()

    with pytest.raises(RolloutConflictError):
        run_attribution_rollout(db_session, quarters=["2026-Q1"], log=lambda *_a: None)
