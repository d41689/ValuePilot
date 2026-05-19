"""Tests for issue #40: system-level start-quarter reconciliation.

Covers the helper that enqueues ``quarterly_pipeline`` jobs for every
quarter in the configured range that has no prior succeeded run.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.services import thirteenf_start_quarter as ssq
from app.models.institutions import JobRun


# ---------- pure helpers -----------------------------------------------------

def test_parse_quarter_ok():
    assert ssq._parse_quarter("2024-Q1") == (2024, 1)
    assert ssq._parse_quarter("2025-Q4") == (2025, 4)


@pytest.mark.parametrize("bad", ["", "2024", "2024-Q", "2024-Q0", "2024-Q5", "2024-QX", "2024Q1"])
def test_parse_quarter_rejects_garbage(bad):
    with pytest.raises(ValueError):
        ssq._parse_quarter(bad)


def test_current_quarter():
    assert ssq.current_quarter(date(2026, 1, 15)) == "2026-Q1"
    assert ssq.current_quarter(date(2026, 4, 1)) == "2026-Q2"
    assert ssq.current_quarter(date(2026, 7, 31)) == "2026-Q3"
    assert ssq.current_quarter(date(2026, 12, 31)) == "2026-Q4"


def test_quarters_in_range_inclusive():
    assert list(ssq.quarters_in_range("2024-Q3", "2025-Q2")) == [
        "2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2",
    ]


def test_quarters_in_range_single_quarter():
    assert list(ssq.quarters_in_range("2025-Q4", "2025-Q4")) == ["2025-Q4"]


def test_quarters_in_range_inverted_returns_empty():
    assert list(ssq.quarters_in_range("2025-Q4", "2024-Q1")) == []


# ---------- reconcile_start_quarter_coverage --------------------------------

def test_reconcile_short_circuits_without_config(db_session, monkeypatch):
    monkeypatch.setattr(ssq.settings, "THIRTEENF_START_QUARTER", None)
    result = ssq.reconcile_start_quarter_coverage(db_session)
    assert result["enqueued"] == []
    assert result.get("reason") == "no start_quarter configured"


def test_reconcile_enqueues_each_missing_quarter(db_session, monkeypatch):
    """With start=2025-Q3, end=2026-Q1, and no prior runs, enqueue all 3 quarters."""
    calls: list[dict] = []

    def fake_trigger(_db, *, requested_by_user_id, payload):
        calls.append(payload)
        return {"id": len(calls), "lock_key": f"quarterly_pipeline:{payload['quarter']}"}

    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.trigger_job",
        fake_trigger,
    )

    result = ssq.reconcile_start_quarter_coverage(
        db_session,
        start_quarter="2025-Q3",
        end_quarter="2026-Q1",
    )

    assert [c["quarter"] for c in calls] == ["2025-Q3", "2025-Q4", "2026-Q1"]
    for c in calls:
        assert c["job_type"] == "quarterly_pipeline"
        assert c["trigger_source"] == "start_quarter_reconcile"
    assert result["enqueued"] == ["2025-Q3", "2025-Q4", "2026-Q1"]
    assert result["skipped_existing"] == []
    assert result["skipped_conflict"] == []


def test_reconcile_skips_quarters_with_meaningful_coverage(db_session, monkeypatch):
    """Skip quarters that already have observable post-routing coverage:
    at least one Filing13F whose period_of_report lands in the quarter
    AND has quarter_end_date populated. Quarters where filings exist but
    routing hasn't run yet (quarter_end_date NULL) ARE re-enqueued —
    that's the post-pipeline-bug-fix self-healing path."""
    from datetime import date
    from app.models.institutions import Filing13F, InstitutionManager

    # Manager + routed filing for 2025-Q4 — should mark it as covered.
    mgr = InstitutionManager(
        cik="0001234567",
        legal_name="Test Mgr",
        display_name="Test",
        name_normalized="test",
        match_status="confirmed",
        is_superinvestor=False,
    )
    db_session.add(mgr)
    db_session.flush()
    routed = Filing13F(
        manager_id=mgr.id,
        accession_no="0001234567-26-000001",
        form_type="13F-HR",
        filed_at=date(2026, 1, 15),
        period_of_report=date(2025, 12, 31),
        quarter_end_date=date(2025, 12, 31),  # ← the signal
        is_latest_for_period=True,
    )
    db_session.add(routed)
    db_session.flush()

    calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.trigger_job",
        lambda _db, **kw: calls.append(kw["payload"]) or {"id": 99},
    )

    result = ssq.reconcile_start_quarter_coverage(
        db_session,
        start_quarter="2025-Q3",
        end_quarter="2026-Q1",
    )

    assert [c["quarter"] for c in calls] == ["2025-Q3", "2026-Q1"]
    assert result["skipped_existing"] == ["2025-Q4"]


def test_reconcile_records_conflicts_as_skipped(db_session, monkeypatch):
    """A conflict (active job already exists for the lock_key) is not an error —
    we just record it and continue."""
    def fake_trigger(_db, *, requested_by_user_id, payload):
        if payload["quarter"] == "2025-Q4":
            return {"conflict": True, "active_job_id": 42, "lock_key": "quarterly_pipeline:2025-Q4"}
        return {"id": 100, "lock_key": f"quarterly_pipeline:{payload['quarter']}"}

    monkeypatch.setattr(
        "app.services.thirteenf_admin_dashboard.trigger_job",
        fake_trigger,
    )

    result = ssq.reconcile_start_quarter_coverage(
        db_session,
        start_quarter="2025-Q3",
        end_quarter="2026-Q1",
    )

    assert result["enqueued"] == ["2025-Q3", "2026-Q1"]
    assert result["skipped_conflict"] == ["2025-Q4"]


def test_reconcile_rejects_malformed_start(db_session):
    result = ssq.reconcile_start_quarter_coverage(
        db_session,
        start_quarter="bogus",
        end_quarter="2025-Q4",
    )
    assert result["enqueued"] == []
    assert "Invalid quarter format" in result["reason"]
