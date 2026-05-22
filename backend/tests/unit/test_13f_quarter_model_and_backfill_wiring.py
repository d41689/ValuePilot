"""Regression tests for the 13F web-validation fixes (F1/F2 + F4).

F1/F2 — report-quarter vs filing-quarter model: a 13F is filed in the calendar
quarter *after* the one it reports on, so `next_quarter_label` is the bridge
between a report quarter and the EDGAR full-index that carries its filings.

F4 — the `historical_backfill` job type must be dispatchable by the worker
(`execute_job_payload`); before the fix it failed "Unsupported job_type".
"""
from __future__ import annotations

import pytest

from app.edgar.parsers.form_idx import next_quarter_label
from app.services.thirteenf_admin_dashboard import execute_job_payload
from app.services.thirteenf_historical_backfill import enqueue_historical_backfill


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
