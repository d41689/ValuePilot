"""Smoke tests for the historical-backfill ops harness.

Task doc: ``docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md``

The harness orchestrates real SEC/OpenFIGI fetches and is exercised
end-to-end during ops runs; here we just pin the small pure helpers
that surfaced as review blockers:

- ``_complete_from_summary`` treats ``partial_success`` from
  ``_execute_job`` as a success (per review-1 B6 / review-2 B6).
- The harness's lease setup uses ``_HARNESS_LEASE_SECONDS = 4 * 60 * 60``
  so a crashed run leaves the JobRun reachable by the stale-job reaper
  (per review-1 B5 / review-2 O1).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.run_historical_backfill import (
    _HARNESS_LEASE_SECONDS,
    _complete_from_summary,
)


def test_harness_lease_seconds_is_four_hours():
    """Matches the longest production stage-job timeout
    (``backfill_*`` jobs in thirteenf_job_worker.py:25).
    """
    assert _HARNESS_LEASE_SECONDS == 4 * 60 * 60


def test_complete_from_summary_treats_partial_success_as_success(db_session, monkeypatch):
    """Review-1 B6: a partial_success returned by ``_execute_job`` is
    success-with-caveat, NOT failure. Without this, downstream stages
    in the harness silently skip and the per-quarter trace lies about
    progress.
    """
    captured: dict = {}

    def _fake_complete_leased_job(_session, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(
        "app.services.thirteenf_job_worker.complete_leased_job",
        _fake_complete_leased_job,
    )

    status = _complete_from_summary(
        db_session,
        job_id=12345,
        worker_id="test-worker",
        lease_token="test-token",
        summary={"status": "partial_success", "filings_failed": 3, "holdings_inserted": 1234},
        error_message=None,
    )
    assert status == "partial_success"
    assert captured["status"] == "partial_success"


def test_complete_from_summary_treats_succeeded_as_success(db_session, monkeypatch):
    def _fake_complete_leased_job(_session, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.thirteenf_job_worker.complete_leased_job",
        _fake_complete_leased_job,
    )

    status = _complete_from_summary(
        db_session,
        job_id=12345,
        worker_id="test-worker",
        lease_token="test-token",
        summary={"status": "succeeded", "filings_scored": 4},
        error_message=None,
    )
    assert status == "succeeded"


def test_complete_from_summary_treats_error_message_as_failure(db_session, monkeypatch):
    captured: dict = {}

    def _fake_complete_leased_job(_session, **kwargs):
        captured.update(kwargs)
        return None
    monkeypatch.setattr(
        "app.services.thirteenf_job_worker.complete_leased_job",
        _fake_complete_leased_job,
    )

    status = _complete_from_summary(
        db_session,
        job_id=12345,
        worker_id="test-worker",
        lease_token="test-token",
        summary={"error": "boom"},
        error_message="boom",
    )
    assert status == "failed"
    assert captured["status"] == "failed"


def test_complete_from_summary_defaults_to_succeeded_when_status_missing(
    db_session, monkeypatch,
):
    """If the executor's summary doesn't carry a 'status' key (some
    handlers don't), fall back to 'succeeded' rather than crashing or
    silently marking failed."""
    def _fake_complete_leased_job(_session, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.thirteenf_job_worker.complete_leased_job",
        _fake_complete_leased_job,
    )

    status = _complete_from_summary(
        db_session,
        job_id=12345,
        worker_id="test-worker",
        lease_token="test-token",
        summary={"holdings_inserted": 100},
        error_message=None,
    )
    assert status == "succeeded"


def test_complete_from_summary_propagates_explicit_failed_status(
    db_session, monkeypatch,
):
    """Review-final blocker: an executor that returns
    ``{"status": "failed", ...}`` WITHOUT raising must be recorded as
    failed, not silently rewritten to succeeded. The old fallback
    ``status if status in {succeeded, partial_success} else 'succeeded'``
    swallowed the failure and would have masked any handler that
    surfaces failures via return value instead of exception.
    """
    captured: dict = {}

    def _fake_complete_leased_job(_session, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(
        "app.services.thirteenf_job_worker.complete_leased_job",
        _fake_complete_leased_job,
    )

    status = _complete_from_summary(
        db_session,
        job_id=12345,
        worker_id="test-worker",
        lease_token="test-token",
        summary={"status": "failed", "error": "downstream bad data"},
        error_message=None,  # no exception was raised; executor returned failed
    )
    assert status == "failed"
    assert captured["status"] == "failed"


def test_complete_from_summary_unknown_status_falls_back_to_succeeded(
    db_session, monkeypatch,
):
    """A handler returning an unknown status string (e.g. a future
    'skipped' / 'cancelled' that the harness doesn't yet recognize)
    falls back to 'succeeded' as the conservative default, NOT to
    failed — failing the entire harness for an unrecognized status
    string would be too brittle for a bookkeeping coordinator."""
    def _fake_complete_leased_job(_session, **kwargs):
        return None
    monkeypatch.setattr(
        "app.services.thirteenf_job_worker.complete_leased_job",
        _fake_complete_leased_job,
    )

    status = _complete_from_summary(
        db_session,
        job_id=12345,
        worker_id="test-worker",
        lease_token="test-token",
        summary={"status": "future_state_we_dont_recognize"},
        error_message=None,
    )
    assert status == "succeeded"


# ---------------------------------------------------------------------------
# main() exit-code propagation
# ---------------------------------------------------------------------------


def test_main_returns_zero_when_all_stages_succeed(monkeypatch, capsys):
    """Happy path — all four stages return succeeded → exit 0."""
    from scripts import run_historical_backfill as harness

    def _stub_one_range(**_):
        return {"job_id": 1, "status": "succeeded", "summary": {"per_quarter": [], "impact_summary": {}}}

    def _stub_ingest_holdings(_q):
        return {"job_id": 2, "status": "succeeded", "summary": {}}

    def _stub_enrich_cusip():
        return {"job_id": 3, "status": "succeeded", "summary": {}}

    def _stub_score_backfill(_q):
        return {"job_id": 4, "status": "succeeded", "summary": {}}

    monkeypatch.setattr(harness, "_run_one_range", _stub_one_range)
    monkeypatch.setattr(harness, "_run_ingest_holdings", _stub_ingest_holdings)
    monkeypatch.setattr(harness, "_run_enrich_cusip", _stub_enrich_cusip)
    monkeypatch.setattr(harness, "_run_score_backfill", _stub_score_backfill)

    rc = harness.main([
        "--start-quarter", "2025-Q3",
        "--end-quarter", "2025-Q3",
    ])
    assert rc == 0


def test_main_returns_nonzero_when_a_stage_fails(monkeypatch, capsys):
    """Review-1 follow-up blocker: a stage that returns ``status='failed'``
    or ``status='conflict'`` must propagate to the harness's exit code.
    Without this, CI / cron consumers think the run succeeded even when
    quarters were silently skipped or errored.
    """
    from scripts import run_historical_backfill as harness

    def _stub_one_range(**_):
        return {"job_id": 1, "status": "succeeded", "summary": {"per_quarter": [], "impact_summary": {}}}

    def _stub_ingest_holdings(_q):
        # Pretend one quarter failed.
        return {"job_id": 2, "status": "failed", "summary": {"error": "infotable XML 404"}}

    def _stub_enrich_cusip():
        return {"job_id": 3, "status": "succeeded", "summary": {}}

    def _stub_score_backfill(_q):
        return {"job_id": 4, "status": "succeeded", "summary": {}}

    monkeypatch.setattr(harness, "_run_one_range", _stub_one_range)
    monkeypatch.setattr(harness, "_run_ingest_holdings", _stub_ingest_holdings)
    monkeypatch.setattr(harness, "_run_enrich_cusip", _stub_enrich_cusip)
    monkeypatch.setattr(harness, "_run_score_backfill", _stub_score_backfill)

    rc = harness.main([
        "--start-quarter", "2025-Q3",
        "--end-quarter", "2025-Q3",
    ])
    assert rc == 1


def test_main_returns_nonzero_when_a_stage_returns_conflict(monkeypatch, capsys):
    """``conflict`` (a parallel job already holds the lock_key) is also
    non-success — the harness was asked to do work it didn't do."""
    from scripts import run_historical_backfill as harness

    def _stub_one_range(**_):
        return {"job_id": 1, "status": "succeeded", "summary": {"per_quarter": [], "impact_summary": {}}}

    def _stub_ingest_holdings(_q):
        return {"status": "conflict", "active_job_id": 9999}

    def _stub_enrich_cusip():
        return {"job_id": 3, "status": "succeeded", "summary": {}}

    def _stub_score_backfill(_q):
        return {"job_id": 4, "status": "succeeded", "summary": {}}

    monkeypatch.setattr(harness, "_run_one_range", _stub_one_range)
    monkeypatch.setattr(harness, "_run_ingest_holdings", _stub_ingest_holdings)
    monkeypatch.setattr(harness, "_run_enrich_cusip", _stub_enrich_cusip)
    monkeypatch.setattr(harness, "_run_score_backfill", _stub_score_backfill)

    rc = harness.main([
        "--start-quarter", "2025-Q3",
        "--end-quarter", "2025-Q3",
    ])
    assert rc == 1
