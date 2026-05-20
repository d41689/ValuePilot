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


def test_reconcile_skips_quarters_with_oracles_lens_signals(db_session, monkeypatch):
    """Skip quarters that have Oracle's Lens signals — the terminal output
    of quarterly_pipeline. Quarters with no signals (pipeline never finished,
    or never ran) ARE re-enqueued. This anchors the reconcile on the
    pipeline's last stage so a future pipeline bug fix self-heals."""
    from datetime import date, datetime, timezone
    from app.models.oracles_lens import OraclesLensSignal
    from app.models.stocks import Stock

    stock = Stock(ticker="TST", exchange="NYSE", company_name="Test Corp", is_active=True)
    db_session.add(stock)
    db_session.flush()
    # A signal row for 2025-Q4 marks that quarter as fully covered.
    signal = OraclesLensSignal(
        stock_id=stock.id,
        report_quarter="2025-Q4",
        quarter_end_date=date(2025, 12, 31),
        score_version="v1.0",
        score_confidence="high",
        computed_at=datetime.now(timezone.utc),
    )
    db_session.add(signal)
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
