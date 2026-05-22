"""Regression tests for the 13F web-validation fixes (F1/F2 + F4).

F1/F2 — report-quarter vs filing-quarter model: a 13F is filed in the calendar
quarter *after* the one it reports on, so `next_quarter_label` is the bridge
between a report quarter and the EDGAR full-index that carries its filings.

F4 — the `historical_backfill` job type must be dispatchable by the worker
(`execute_job_payload`); before the fix it failed "Unsupported job_type".
"""
from __future__ import annotations

import pytest

import app.services.edgar_ingestion as edgar_ingestion
from app.edgar.parsers.form_idx import next_quarter_label
from app.services.thirteenf_admin_dashboard import current_quarter, execute_job_payload
from app.services.thirteenf_historical_backfill import (
    enqueue_historical_backfill,
    execute_historical_backfill,
)


@pytest.mark.parametrize(
    ("report_quarter", "expected_filing_quarter"),
    [
        ("2025-Q1", "2025-Q2"),
        ("2025-Q2", "2025-Q3"),
        ("2025-Q3", "2025-Q4"),
        ("2025-Q4", "2026-Q1"),  # year rollover
    ],
)
def test_next_quarter_label(report_quarter: str, expected_filing_quarter: str) -> None:
    assert next_quarter_label(report_quarter) == expected_filing_quarter


def test_historical_backfill_job_is_dispatched(db_session) -> None:
    """`execute_job_payload` must route `historical_backfill` to its executor.

    Regression for F4: the job type had a lock builder (so it could be queued)
    but no `_execute_job` branch, so every run failed "Unsupported job_type".
    Run with zero managers + dry_run so the executor touches no EDGAR network.
    """
    job = enqueue_historical_backfill(
        db_session, start_quarter="2025-Q4", end_quarter="2025-Q4", dry_run=True
    )

    result = execute_job_payload(db_session, "historical_backfill", {"_job_id": job.id})

    assert result["status"] in {"succeeded", "partial_success", "failed"}
    assert result["impact_summary"]["quarters_scanned"] == 1


def test_backfill_quarters_does_not_request_a_future_filing_quarter(
    db_session, monkeypatch
) -> None:
    """`backfill_quarters` must enumerate *usable* report quarters.

    Regression for the review's P1: it used to start at the current calendar
    quarter, which — after `ingest_quarter_index` began translating report →
    filing quarter — asks EDGAR for a full-index quarter that has not started.
    """
    requested: list[str] = []

    def _fake_ingest(_db, quarter: str) -> int:
        requested.append(quarter)
        return 0

    monkeypatch.setattr(edgar_ingestion, "ingest_quarter_index", _fake_ingest)

    edgar_ingestion.backfill_quarters(db_session, num_quarters=4)

    assert len(requested) == 4
    current = current_quarter().label
    for report_quarter in requested:
        # the filing quarter ingest_quarter_index will actually fetch
        assert next_quarter_label(report_quarter) <= current, (
            f"backfill would fetch filing quarter {next_quarter_label(report_quarter)} "
            f"for report quarter {report_quarter}; current calendar quarter is {current}"
        )


def test_historical_backfill_executor_leaves_job_for_caller_to_finalize(
    db_session,
) -> None:
    """`execute_historical_backfill` must not write a terminal JobRun status.

    Regression for the review's P1: the worker's `complete_leased_job` only
    finalizes (`finished_at`, clears the lease) a row still `running`. If the
    executor commits a terminal status first, that completion no-ops.
    """
    job = enqueue_historical_backfill(
        db_session, start_quarter="2025-Q4", end_quarter="2025-Q4", dry_run=True
    )
    assert job.status == "queued"

    result = execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        filing_discovery_fn=lambda *_: [],
        ingest_fn=lambda *_: {"status": "succeeded"},
    )

    db_session.refresh(job)
    assert job.status == "queued"  # left untouched for the caller to finalize
    assert job.finished_at is None
    assert result["status"] in {"succeeded", "partial_success", "failed"}
