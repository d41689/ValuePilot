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


def _stock(db, ticker):
    from app.models.stocks import Stock
    s = Stock(ticker=ticker, exchange="NASDAQ", company_name=ticker)
    db.add(s); db.flush()
    return s


def _holding(db, filing, *, discretion, status, cusip="111111111", stock=None):
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
        stock_id=stock.id if stock else None,
        cusip_mapping_status="linked" if stock else "unresolved",
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


def test_rollout_fails_on_hard_failed_ownership_stage(db_session, monkeypatch):
    """Re-review #1: a hard-`failed` ownership_changes stage means the read model
    was NOT refreshed — the rollout must report failure, not exit 0."""
    from app.services import thirteenf_attribution_rollout as roll

    def fake_stage(session, *, parent_payload, job_type, payload):
        status = "failed" if job_type == "compute_ownership_changes" else "succeeded"
        return {"stage": {"job_type": job_type, "job_id": 999, "status": status},
                "summary": {"status": status}}

    monkeypatch.setattr(roll, "_execute_pipeline_stage_job", fake_stage)
    report = roll.run_attribution_rollout(db_session, quarters=["2099-Q1"], log=lambda *_a: None)
    assert any("ownership_changes 2099-Q1 stage status=failed" in f for f in report["failures"])


def test_rollout_fails_on_hard_failed_lens_stage(db_session, monkeypatch):
    """Re-review #1: a hard-`failed` Oracle's Lens stage must also fail the rollout
    (the previous loop ignored Lens status entirely)."""
    from app.services import thirteenf_attribution_rollout as roll

    def fake_stage(session, *, parent_payload, job_type, payload):
        status = "failed" if job_type == "oracles_lens_score_backfill" else "succeeded"
        return {"stage": {"job_type": job_type, "job_id": 999, "status": status},
                "summary": {"status": status}}

    monkeypatch.setattr(roll, "_execute_pipeline_stage_job", fake_stage)
    report = roll.run_attribution_rollout(db_session, quarters=["2099-Q1"], log=lambda *_a: None)
    assert any("oracles_lens 2099-Q1 stage status=failed" in f for f in report["failures"])


def test_rollout_fails_on_partial_success_ownership_stage(db_session, monkeypatch):
    """Re-review #1: partial_success (some managers failed) must not silently pass."""
    from app.services import thirteenf_attribution_rollout as roll

    def fake_stage(session, *, parent_payload, job_type, payload):
        if job_type == "compute_ownership_changes":
            return {"stage": {"job_type": job_type, "job_id": 999, "status": "partial_success"},
                    "summary": {"status": "partial_success", "failure_count": 3}}
        return {"stage": {"job_type": job_type, "job_id": 999, "status": "succeeded"},
                "summary": {"status": "succeeded"}}

    monkeypatch.setattr(roll, "_execute_pipeline_stage_job", fake_stage)
    report = roll.run_attribution_rollout(db_session, quarters=["2099-Q1"], log=lambda *_a: None)
    assert any("partial_success" in f and "failures=3" in f for f in report["failures"])


def test_rollout_fails_on_noop_success_with_active_filers(db_session, monkeypatch):
    """Re-review #4 (P2): stages that report `succeeded` but write nothing, while
    active direct filers exist for the quarter, must fail — run-scoped freshness,
    not stale all-history data, decides. (Reproduces the no-op-success bug.)"""
    from app.services import thirteenf_attribution_rollout as roll

    # A real quarter with an active DIRECT filer (so work is expected).
    _holding(db_session, _filing(db_session, _manager(db_session)), discretion="SOLE", status="direct")

    def noop_stage(session, *, parent_payload, job_type, payload):
        summary = {"status": "succeeded"}
        summary["rows_created" if job_type == "compute_ownership_changes" else "filings_scored"] = 0
        return {"stage": {"job_type": job_type, "job_id": 111, "status": "succeeded"}, "summary": summary}

    monkeypatch.setattr(roll, "_execute_pipeline_stage_job", noop_stage)
    report = roll.run_attribution_rollout(db_session, quarters=["2026-Q1"], log=lambda *_a: None)
    assert report["failures"], "a no-op recompute with active filers must fail"
    assert any("wrote 0 rows" in f or "0 signals" in f for f in report["failures"])


def test_rollout_empty_quarter_noop_is_not_a_failure(db_session, monkeypatch):
    """Freshness must NOT false-fail a genuinely empty quarter (no active filers):
    0 rows is legitimate there, distinguishing a no-op from an empty quarter."""
    from app.services import thirteenf_attribution_rollout as roll

    def noop_stage(session, *, parent_payload, job_type, payload):
        summary = {"status": "succeeded"}
        summary["rows_created" if job_type == "compute_ownership_changes" else "filings_scored"] = 0
        return {"stage": {"job_type": job_type, "job_id": 222, "status": "succeeded"}, "summary": summary}

    monkeypatch.setattr(roll, "_execute_pipeline_stage_job", noop_stage)
    report = roll.run_attribution_rollout(db_session, quarters=["2099-Q1"], log=lambda *_a: None)
    assert report["failures"] == []


def test_lens_freshness_skips_ineligible_quarter(db_session):
    """Re-review #5 (P2) — false-fail guard: a quarter with active filers but no
    stock reaching the >=3-holder threshold legitimately scores 0; the per-quarter
    freshness check must NOT flag its Lens (mirrors real dev 2024-Q4)."""
    from app.services.thirteenf_attribution_rollout import _run_freshness_failures
    # Two managers hold one stock -> below the 3-holder Lens threshold.
    stock = _stock(db_session, "SMALL")
    for i in range(2):
        _holding(db_session, _filing(db_session, _manager(db_session)),
                 discretion="SOLE", status="direct", cusip=f"{i:09d}", stock=stock)
    # ownership wrote rows, lens legitimately wrote none -> no failure.
    failures = _run_freshness_failures(
        db_session, ["2026-Q1"], ownership_rows_by_quarter={"2026-Q1": 2}, lens_job_id_by_quarter={"2026-Q1": 5}
    )
    assert failures == []


def test_lens_freshness_fails_noop_on_eligible_quarter(db_session):
    """Re-review #5 (P2): a quarter WITH >=3 holders of a stock (Lens-eligible) whose
    Lens stage wrote no signal under its own job id is a no-op -> failure."""
    from app.services.thirteenf_attribution_rollout import _run_freshness_failures
    stock = _stock(db_session, "ELIG")
    for i in range(3):  # 3 distinct managers of one stock -> eligible
        _holding(db_session, _filing(db_session, _manager(db_session)),
                 discretion="SOLE", status="direct", cusip=f"{i:09d}", stock=stock)
    # Lens job 777 wrote no oracles_lens_signals rows.
    failures = _run_freshness_failures(
        db_session, ["2026-Q1"], ownership_rows_by_quarter={"2026-Q1": 3}, lens_job_id_by_quarter={"2026-Q1": 777}
    )
    assert any("0 signals for 2026-Q1" in f and "eligible" in f for f in failures)
