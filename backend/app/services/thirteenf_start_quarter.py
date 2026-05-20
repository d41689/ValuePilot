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
from datetime import date, timedelta
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


# A 13F-HR for quarter Q is due ~45 days after Q ends. Until that window has
# substantially opened a quarter structurally cannot produce holdings (let
# alone Oracle's Lens signals), so the reconcile must not chase it — see
# latest_scoreable_quarter.
_FILING_LAG_DAYS = 45


def _quarter_end_date(quarter: str) -> date:
    """Calendar quarter-end date for a 'YYYY-QN' string."""
    year, q = _parse_quarter(quarter)
    return {1: date(year, 3, 31), 2: date(year, 6, 30),
            3: date(year, 9, 30), 4: date(year, 12, 31)}[q]


def latest_scoreable_quarter(today: date | None = None) -> str:
    """Most recent quarter whose 13F filing window has substantially opened
    (quarter end + ~45 days <= today).

    The reconcile uses this as its default ``end_quarter`` instead of the
    current calendar quarter (external review R2-P2). Chasing the in-progress
    quarter means enqueuing a `quarterly_pipeline` for a quarter that
    structurally has zero filings and therefore zero terminal signals — so
    `_has_meaningful_coverage` never returns True and the reconcile re-enqueues
    it on every boot, forever.
    """
    today = today or date.today()
    quarter = current_quarter(today)
    while _quarter_end_date(quarter) + timedelta(days=_FILING_LAG_DAYS) > today:
        year, q = _parse_quarter(quarter)
        q -= 1
        if q == 0:
            q = 4
            year -= 1
        quarter = _quarter_str(year, q)
    return quarter


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
    """Return True iff this quarter has Oracle's Lens signals — i.e. the
    quarterly_pipeline ran all the way through its final stage. Used by the
    reconcile to decide "skip — done" versus "re-enqueue — work missing".

    Why anchor on oracles_lens_signals specifically?

    This criterion has been moved twice. First it was JobRun.status ==
    'succeeded' — but stage status reflects whether stages threw, not
    whether they did useful work (a swallowed ImportError still returned
    'succeeded'). Then it was Filing13F.quarter_end_date populated — but
    that's an *intermediate* signal: once routing shipped and backfilled
    that column, the reconcile started skipping quarters whose later
    stages (CUSIP linking, is_active flags, Oracle's Lens scoring) had
    never run.

    The lesson: anchor on the pipeline's *terminal* output. oracles_lens_signals
    is written by the last stage (oracles_lens_score_backfill); nothing
    runs after it. If signal rows exist for the quarter, the whole pipeline
    completed. If they don't, something upstream is missing and a re-run is
    warranted — and because every stage is idempotent, re-running a
    near-complete quarter is cheap (cache hits, fingerprint-skip, upserts).

    Edge case: a quarter where no stock clears the min-holders floor will
    legitimately have 0 signals and be re-enqueued on each boot. That's an
    acceptable cost — the re-run is a fast no-op — and far better than the
    failure mode this method has hit twice (skipping incomplete quarters).
    """
    from app.models.oracles_lens import OraclesLensSignal

    if (
        db.query(OraclesLensSignal.id)
        .filter(OraclesLensSignal.report_quarter == quarter)
        .first()
        is not None
    ):
        return True

    # A succeeded oracles_lens_score_backfill means the terminal stage ran
    # to completion. This covers the legitimate "quarter with no stock above
    # min_holders → 0 signals" case (external review R2-P2): without it, such
    # a quarter would have 0 signal rows and be re-enqueued on every boot
    # forever. lock_key shape: "oracles_lens_score:<quarter>:<score_version>".
    return (
        db.query(JobRun.id)
        .filter(JobRun.lock_key.like(f"oracles_lens_score:{quarter}:%"))
        .filter(JobRun.status == "succeeded")
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
        - ``end_quarter`` from ``latest_scoreable_quarter()`` (the most
          recent quarter whose 13F filing window has opened — never the
          in-progress calendar quarter).

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

    # Default end at the latest quarter whose filing window has opened —
    # NOT the current calendar quarter, which would spin forever (R2-P2).
    end_quarter = end_quarter or latest_scoreable_quarter()
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
