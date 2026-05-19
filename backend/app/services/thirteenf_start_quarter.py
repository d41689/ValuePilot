"""System-level start-quarter reconciliation (#40).

When ``THIRTEENF_START_QUARTER`` is configured, the API boot lifespan calls
``reconcile_start_quarter_coverage`` which walks each quarter from the
configured start through the current calendar quarter and enqueues a
``quarterly_pipeline`` job for any quarter that has no prior succeeded run.

This implements the "set a start date and walk away" PRD vision: operators
configure one env var; the system fills the backfill end-to-end without
further button clicks. Re-runs across restarts are safe — already-succeeded
quarters are skipped via a JobRun status check, and the underlying pipeline
stages are individually idempotent.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, Iterator

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.institutions import JobRun

logger = logging.getLogger(__name__)


def _parse_quarter(quarter: str) -> tuple[int, int]:
    """``'2024-Q1' → (2024, 1)``. Raises ValueError on malformed input."""
    if not quarter or len(quarter) != 7 or quarter[4:6] != "-Q":
        raise ValueError(f"Invalid quarter format: {quarter!r} (expected YYYY-QN)")
    try:
        year = int(quarter[:4])
        q = int(quarter[6])
    except ValueError as exc:
        raise ValueError(f"Invalid quarter format: {quarter!r}") from exc
    if q < 1 or q > 4:
        raise ValueError(f"Quarter out of range: {quarter!r}")
    return year, q


def _quarter_str(year: int, q: int) -> str:
    return f"{year}-Q{q}"


def current_quarter(today: date | None = None) -> str:
    """Calendar quarter for ``today`` (default: real today). 2026-05-19 → '2026-Q2'."""
    today = today or date.today()
    q = (today.month - 1) // 3 + 1
    return _quarter_str(today.year, q)


def quarters_in_range(start: str, end: str) -> Iterator[str]:
    """Inclusive walk start→end. Empty if start > end."""
    sy, sq = _parse_quarter(start)
    ey, eq = _parse_quarter(end)
    if (sy, sq) > (ey, eq):
        return
    y, q = sy, sq
    while (y, q) <= (ey, eq):
        yield _quarter_str(y, q)
        q += 1
        if q > 4:
            q = 1
            y += 1


def _has_prior_success(db: Session, quarter: str) -> bool:
    """True if a quarterly_pipeline JobRun for this quarter has previously
    succeeded. Drives the "don't re-enqueue completed quarters" optimization."""
    return (
        db.query(JobRun.id)
        .filter(JobRun.lock_key == f"quarterly_pipeline:{quarter}")
        .filter(JobRun.status == "succeeded")
        .first()
        is not None
    )


def reconcile_start_quarter_coverage(
    db: Session,
    *,
    start_quarter: str | None = None,
    end_quarter: str | None = None,
    requested_by_user_id: int | None = None,
) -> dict[str, list[str] | str]:
    """Enqueue ``quarterly_pipeline`` jobs for every quarter in the configured
    range that has no prior successful run.

    Defaults:
        - ``start_quarter`` from ``settings.THIRTEENF_START_QUARTER``.
        - ``end_quarter`` from ``current_quarter()`` (today's calendar quarter).

    Returns a summary dict with three lists (``enqueued``, ``skipped_existing``,
    ``skipped_conflict``) plus an optional ``reason`` string when the function
    short-circuits (no config or invalid input).
    """
    # Lazy import to avoid circular dependency: thirteenf_admin_dashboard imports
    # from edgar_ingestion which can transitively reach back here through some
    # job-dispatch paths; lazy load breaks the cycle at import time.
    from app.services.thirteenf_admin_dashboard import trigger_job

    summary: dict[str, list[str] | str] = {
        "enqueued": [],
        "skipped_existing": [],
        "skipped_conflict": [],
    }
    start_quarter = start_quarter or settings.THIRTEENF_START_QUARTER
    if not start_quarter:
        summary["reason"] = "no start_quarter configured"
        return summary

    end_quarter = end_quarter or current_quarter()
    try:
        _parse_quarter(start_quarter)
        _parse_quarter(end_quarter)
    except ValueError as exc:
        logger.error("reconcile_start_quarter_coverage: %s", exc)
        summary["reason"] = str(exc)
        return summary

    enqueued: list[str] = []
    skipped_existing: list[str] = []
    skipped_conflict: list[str] = []
    for quarter in quarters_in_range(start_quarter, end_quarter):
        if _has_prior_success(db, quarter):
            skipped_existing.append(quarter)
            continue
        result = trigger_job(
            db,
            requested_by_user_id=requested_by_user_id,
            payload={
                "job_type": "quarterly_pipeline",
                "quarter": quarter,
                "trigger_source": "start_quarter_reconcile",
            },
        )
        if result.get("conflict"):
            skipped_conflict.append(quarter)
        else:
            enqueued.append(quarter)

    summary["enqueued"] = enqueued
    summary["skipped_existing"] = skipped_existing
    summary["skipped_conflict"] = skipped_conflict
    return summary
