"""System-level start-quarter reconciliation (#40).

When ``THIRTEENF_START_QUARTER`` is configured, the API boot lifespan calls
``reconcile_start_quarter_coverage`` which walks each quarter from the
configured start through ``latest_scoreable_quarter()`` and enqueues a
``quarterly_pipeline`` job for any quarter that has no complete six-stage
pipeline manifest yet (see ``_has_meaningful_coverage``).

This implements the "set a start date and walk away" PRD vision: operators
configure one env var; the system fills the backfill end-to-end without
further button clicks. Re-runs across restarts are safe — quarters whose
pipeline completed all required stages are skipped, and every pipeline stage
is individually idempotent.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable, Iterator

from sqlalchemy.orm import Session

from app.core.config import settings

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


_REQUIRED_PIPELINE_STAGES = {
    "fetch_quarter_index",
    "ingest_holdings",
    "enrich_metadata",
    "quality_check",
    "compute_ownership_changes",
    "oracles_lens_score_backfill",
}


def _has_meaningful_coverage(db: Session, quarter: str) -> bool:
    """Return True only for a persisted, complete quarterly-pipeline manifest.

    Neither one filing nor one Oracle's Lens signal proves full-quarter
    ingestion. Conversely, a legitimately empty scoring result should not make
    an otherwise complete quarter run forever. The completion contract is the
    terminal parent job plus exactly the six required stages and no pipeline
    warning/error. A narrowly-defined exception accepts a partial ingest whose
    only degradation is fully-routed human-review evidence (for example a very
    late filing with an explicit quarter-end) after all dependent read models
    have been recomputed. The review signal remains visible, but rebooting does
    not enqueue the same deterministic data forever.

    This is deliberately stricter than ``JobRun.status == 'succeeded'``. Old
    jobs without the structured manifest, partial stage lists, and summaries
    produced by the former swallow-and-continue paths all fail closed and are
    re-enqueued. The current stage runner fails programming errors loudly and
    the parent downgrades any non-green stage or cross-stage warning.
    """
    from app.models.institutions import JobRun

    jobs = (
        db.query(JobRun)
        .filter(JobRun.job_type == "quarterly_pipeline")
        .filter(JobRun.quarter == quarter)
        .filter(JobRun.status.in_(["succeeded", "partial_success"]))
        .order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .all()
    )
    for job in jobs:
        summary = job.summary_json if isinstance(job.summary_json, dict) else {}
        if summary.get("summary_schema") != "quarterly_pipeline_summary.v1":
            continue
        if summary.get("quarter") != quarter:
            continue
        if summary.get("pipeline_warning") or summary.get("pipeline_error"):
            continue
        stages = summary.get("stages")
        if not isinstance(stages, list) or len(stages) != len(_REQUIRED_PIPELINE_STAGES):
            continue
        if any(not isinstance(stage, dict) for stage in stages):
            continue
        stage_types = {stage.get("job_type") for stage in stages}
        if stage_types != _REQUIRED_PIPELINE_STAGES:
            continue
        stages_all_green = all(
            stage.get("status") == "succeeded" for stage in stages
        )
        if job.status == "succeeded":
            if not stages_all_green:
                continue
        elif not _is_resolved_routing_review_manifest(job, summary, stages):
            continue
        return True
    return False


def _is_resolved_routing_review_manifest(
    job, summary: dict, stages: list[dict]
) -> bool:
    """True only for a terminal, fully-routed ingest review.

    Missing/invalid/off-quarter periods remain incomplete because they have no
    trustworthy report quarter. Fetch, parse, quarantine, and dependent-refresh
    failures also fail closed.
    """
    if job.status != "partial_success":
        return False
    non_green = [stage for stage in stages if stage.get("status") != "succeeded"]
    if len(non_green) != 1 or non_green[0].get("job_type") != "ingest_holdings":
        return False

    ingest = summary.get("holdings_ingestion")
    if not isinstance(ingest, dict) or ingest.get("status") != "partial_success":
        return False
    if any(
        int(ingest.get(key) or 0) > 0
        for key in (
            "filings_failed",
            "filings_quarantined",
            "filings_routing_failed",
        )
    ):
        return False

    review_total = int(ingest.get("filings_routing_needs_review") or 0)
    review_routed = int(ingest.get("filings_routing_needs_review_routed") or 0)
    review_unrouted = int(ingest.get("filings_routing_needs_review_unrouted") or 0)
    if review_total <= 0 or review_total != review_routed or review_unrouted:
        return False

    targets = set(summary.get("dependent_recompute_targets") or [])
    recomputed = set(summary.get("quarters_recomputed") or [])
    if targets - recomputed or summary.get("quarters_needing_recompute"):
        return False
    return True


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
    range that has no prior complete six-stage run.

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
