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


# ---------- latest_scoreable_quarter (external review R2-P2) -----------------

def test_latest_scoreable_quarter_excludes_in_progress_quarter():
    """On 2026-05-19 the current calendar quarter is 2026-Q2, but Q2 filings
    aren't due until ~Aug. The latest quarter worth scoring is 2026-Q1
    (ended 2026-03-31, filing window opened ~2026-05-15)."""
    assert ssq.latest_scoreable_quarter(date(2026, 5, 19)) == "2026-Q1"


def test_latest_scoreable_quarter_before_filing_window_opens():
    """2026-05-14 is before 2026-Q1's filing window (Q1 end + 45d = 05-15),
    so the latest scoreable quarter is still 2025-Q4."""
    assert ssq.latest_scoreable_quarter(date(2026, 5, 14)) == "2025-Q4"


def test_latest_scoreable_quarter_after_window_opens():
    """Once 2026-Q2's window has opened (Q2 end + 45d = 2026-08-14)."""
    assert ssq.latest_scoreable_quarter(date(2026, 8, 20)) == "2026-Q2"


# ---------- _has_meaningful_coverage: completed stage manifest is proof ------


def _completed_pipeline_job(quarter: str = "2025-Q4", **overrides) -> JobRun:
    stages = [
        {"job_type": job_type, "job_id": index, "status": "succeeded"}
        for index, job_type in enumerate(
            [
                "fetch_quarter_index",
                "ingest_holdings",
                "enrich_metadata",
                "quality_check",
                "compute_ownership_changes",
                "oracles_lens_score_backfill",
            ],
            start=1,
        )
    ]
    payload = {
        "job_type": "quarterly_pipeline",
        "status": "succeeded",
        "lock_key": f"quarterly_pipeline:{quarter}",
        "dedupe_key": f"quarterly_pipeline:{quarter}",
        "quarter": quarter,
        "trigger_source": "pipeline",
        "summary_json": {
            "summary_schema": "quarterly_pipeline_summary.v1",
            "quarter": quarter,
            "stages": stages,
        },
        "created_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return JobRun(**payload)

def test_has_meaningful_coverage_is_false_for_succeeded_job_with_zero_signals(db_session):
    """A succeeded oracles_lens_score_backfill job is NOT sufficient on its
    own (PR #56 re-review P1). Scoring can succeed with zero signals because
    upstream was incomplete (managers not seeded, routing partial, holdings
    not yet linked) — treating that as terminal would freeze the quarter
    forever. Only actual signal rows count as coverage."""
    job = JobRun(
        job_type="oracles_lens_score_backfill",
        status="succeeded",
        lock_key="oracles_lens_score:2025-Q4:v1.0",
        dedupe_key="oracles_lens_score:2025-Q4:v1.0",
        quarter="2025-Q4",
        trigger_source="pipeline",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.flush()

    # Succeeded scoring job but ZERO signal rows → NOT covered → reconcile
    # will re-enqueue and self-heal once the upstream gap is fixed.
    assert ssq._has_meaningful_coverage(db_session, "2025-Q4") is False


def test_has_meaningful_coverage_is_false_for_signal_without_completed_pipeline(db_session):
    """One score row cannot prove the SEC index and every manager completed."""
    from datetime import date
    from app.models.oracles_lens import OraclesLensSignal
    from app.models.stocks import Stock

    stock = Stock(ticker="COV", exchange="NYSE", company_name="Covered Co", is_active=True)
    db_session.add(stock)
    db_session.flush()
    db_session.add(OraclesLensSignal(
        stock_id=stock.id,
        report_quarter="2025-Q4",
        quarter_end_date=date(2025, 12, 31),
        score_version="v1.0",
        score_confidence="high_confidence",
        computed_at=datetime.now(timezone.utc),
    ))
    db_session.flush()

    assert ssq._has_meaningful_coverage(db_session, "2025-Q4") is False
    assert ssq._has_meaningful_coverage(db_session, "2025-Q3") is False


def test_has_meaningful_coverage_is_true_for_complete_pipeline_manifest(db_session):
    """A green parent plus all six green stages is the persisted completion marker."""
    db_session.add(_completed_pipeline_job())
    db_session.flush()

    assert ssq._has_meaningful_coverage(db_session, "2025-Q4") is True


def test_has_meaningful_coverage_accepts_only_fully_routed_review_filings(
    db_session,
):
    """An explicit old quarter-end is reviewable but not incomplete.

    Late filings with ``PERIOD_SUSPICIOUSLY_STALE`` still have a deterministic
    report quarter. Once all dependent read models were recomputed, restarting
    the API must not enqueue the same quarter forever merely because the ingest
    job preserved that human-review signal.
    """
    job = _completed_pipeline_job(status="partial_success")
    job.summary_json["stages"][1]["status"] = "partial_success"
    job.summary_json["holdings_ingestion"] = {
        "status": "partial_success",
        "filings_failed": 0,
        "filings_quarantined": 0,
        "filings_routing_failed": 0,
        "filings_routing_needs_review": 4,
        "filings_routing_needs_review_routed": 4,
        "filings_routing_needs_review_unrouted": 0,
    }
    job.summary_json["dependent_recompute_targets"] = ["2025-Q1"]
    job.summary_json["quarters_recomputed"] = ["2025-Q1"]
    db_session.add(job)
    db_session.flush()

    assert ssq._has_meaningful_coverage(db_session, "2025-Q4") is True


def test_has_meaningful_coverage_rejects_unrouted_review_filings(db_session):
    job = _completed_pipeline_job(status="partial_success")
    job.summary_json["stages"][1]["status"] = "partial_success"
    job.summary_json["holdings_ingestion"] = {
        "status": "partial_success",
        "filings_failed": 0,
        "filings_quarantined": 0,
        "filings_routing_failed": 0,
        "filings_routing_needs_review": 1,
        "filings_routing_needs_review_routed": 0,
        "filings_routing_needs_review_unrouted": 1,
    }
    db_session.add(job)
    db_session.flush()

    assert ssq._has_meaningful_coverage(db_session, "2025-Q4") is False


@pytest.mark.parametrize(
    "job_overrides",
    [
        {"status": "partial_success"},
        {
            "summary_json": {
                "summary_schema": "quarterly_pipeline_summary.v1",
                "quarter": "2025-Q4",
                "stages": [
                    {"job_type": "fetch_quarter_index", "job_id": 1, "status": "succeeded"},
                ],
            },
        },
        {
            "summary_json": {
                "summary_schema": "quarterly_pipeline_summary.v1",
                "quarter": "2025-Q4",
                "pipeline_warning": "incomplete ingestion",
                "stages": [],
            },
        },
    ],
)
def test_has_meaningful_coverage_rejects_incomplete_pipeline_manifest(
    db_session, job_overrides
):
    db_session.add(_completed_pipeline_job(**job_overrides))
    db_session.flush()

    assert ssq._has_meaningful_coverage(db_session, "2025-Q4") is False


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


def test_reconcile_skips_quarters_with_completed_pipeline(db_session, monkeypatch):
    """Skip only a quarter carrying the full six-stage completion manifest."""
    db_session.add(_completed_pipeline_job())
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
