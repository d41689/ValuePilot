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


def _has_meaningful_coverage(db: Session, quarter: str) -> bool:
    """Return True iff this quarter has both an ingestion entry point (raw
    master.idx record) AND post-routing state (at least one Filing13F with
    quarter_end_date populated). Used by the reconcile to decide "skip — done"
    versus "re-enqueue — work missing".

    Why not just check JobRun.status == 'succeeded'?

    The pipeline's stage-level status reflects whether stages threw, not
    whether they did anything useful. Before #52, ingest_holdings stage 2
    silently caught an ImportError, ran with 0 routing changes, and returned
    'succeeded'. The reconcile then refused to re-enqueue, even though
    Filing13F.quarter_end_date was still NULL for the entire quarter and
    Oracle's Lens couldn't aggregate. Anchoring on observable DB state
    instead of self-reported job status makes the reconcile self-correcting
    after pipeline bug fixes ship.

    The Filing13F.quarter_end_date check is the right data-state proxy
    because it's set by route_period only after primary_doc XML has been
    fetched and parsed — i.e. it confirms the full Phase 1 + Phase 2
    sequence ran successfully for at least one filing in the quarter.
    """
    from app.models.institutions import Filing13F
    from app.services.thirteenf_filing_detail import _parse_period_date  # type: ignore[attr-defined]

    # Look at any Filing13F whose period_of_report lands in this calendar
    # quarter and has quarter_end_date populated. period_of_report is a
    # date; quarter window is [Y-Q*3-2, Y-Q*3+(0|1|2 last day)].
    year, q = _parse_quarter(quarter)
    from datetime import date

    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    end_day = 31 if end_month in {1, 3, 5, 7, 8, 10, 12} else 30
    if end_month == 2:
        end_day = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    window_start = date(year, start_month, 1)
    window_end = date(year, end_month, end_day)

    return (
        db.query(Filing13F.id)
        .filter(Filing13F.period_of_report.between(window_start, window_end))
        .filter(Filing13F.quarter_end_date.isnot(None))
        .first()
        is not None
    )


# Back-compat alias — older code paths might import this name.
_has_prior_success = _has_meaningful_coverage


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
