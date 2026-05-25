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
