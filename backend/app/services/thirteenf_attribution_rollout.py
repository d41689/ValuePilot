"""T3 combination-attribution rollout logic — importable + testable.

Kept out of the thin `scripts/t3_attribution_rollout.py` wrapper so the ordering,
job-locking, and verification invariants can be unit-tested (including
failure-injection). See that script for the operator command.

Rollout order (so no product surface is left stale):
  1. backfill holding_attribution under the current rule (SOLE/DFND/OTR -> direct);
  2. recompute ownership_changes for every affected quarter — through the LOCKED
     JobRun mechanism, so a concurrent scheduled pipeline / admin job / second
     rollout is rejected rather than racing the delete/insert;
  3. recompute Oracle's Lens ONLY after ownership changes complete (also locked);
  4. verify hard invariants; any failure is returned so the caller exits non-zero.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.thirteenf_admin_dashboard import _execute_pipeline_stage_job
from app.services.thirteenf_holdings_ingest import backfill_holding_attribution


class RolloutConflictError(RuntimeError):
    """A conflicting compute_ownership_changes / oracles_lens job is already
    active for a quarter — the rollout refuses to race it. Quiesce jobs and retry."""


def verify_attribution_rollout(session: Session) -> list[str]:
    """Return hard-invariant violations (empty == healthy). Fails closed: it
    asserts the *positive* rule (every recognized discretion is direct), not just
    the absence of legacy statuses, so the original DFND/no-Column-7 ->
    `unresolved` bug cannot silently pass."""
    failures: list[str] = []

    legacy = session.execute(
        text(
            "SELECT COUNT(*) FROM holdings_13f "
            "WHERE holding_attribution_status IN ('reported_for_other', 'shared')"
        )
    ).scalar()
    if legacy:
        failures.append(f"{legacy} holdings still at legacy reported_for_other/shared status")

    # The exact invariant: any SOLE/DFND/OTR row that is not `direct` is a bug
    # (this is what the original ticket got wrong for DFND/no-Column-7 rows).
    misattributed = session.execute(
        text(
            "SELECT COUNT(*) FROM holdings_13f "
            "WHERE investment_discretion IN ('SOLE', 'DFND', 'OTR') "
            "AND holding_attribution_status IS DISTINCT FROM 'direct'"
        )
    ).scalar()
    if misattributed:
        failures.append(
            f"{misattributed} recognized-discretion (SOLE/DFND/OTR) holdings are not 'direct'"
        )

    zero_direct = session.execute(
        text(
            "SELECT COUNT(*) FROM (SELECT manager_id FROM holdings_13f GROUP BY 1 "
            "HAVING COUNT(*) FILTER (WHERE holding_attribution_status='direct')=0) x"
        )
    ).scalar()
    if zero_direct:
        failures.append(f"{zero_direct} managers have zero direct holdings")

    return failures


def _run_locked_stage(session: Session, *, job_type: str, quarter: str) -> dict:
    """Run one recompute through the canonical locked JobRun path. Raises
    RolloutConflictError if the per-quarter lock is already held."""
    result = _execute_pipeline_stage_job(
        session,
        parent_payload={},
        job_type=job_type,
        payload={"quarter": quarter},
    )
    if result["stage"]["status"] == "conflict":
        raise RolloutConflictError(
            f"{job_type} for {quarter} is already running (job_id="
            f"{result['stage'].get('job_id')}); quiesce jobs and retry"
        )
    return result


def run_attribution_rollout(
    session: Session,
    *,
    quarters: list[str] | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Execute the ordered rollout and return a report dict with `failures`
    (empty == success). Raises RolloutConflictError on a lock conflict."""
    reattributed = backfill_holding_attribution(session)
    session.commit()
    log(f"[1/4] re-attributed holdings: {reattributed}")

    if quarters is None:
        quarters = [
            row[0]
            for row in session.execute(
                text(
                    "SELECT DISTINCT report_quarter FROM filings_13f "
                    "WHERE report_quarter IS NOT NULL ORDER BY report_quarter"
                )
            ).fetchall()
        ]

    # Any stage status other than "succeeded" is a rollout failure: a hard
    # `failed` stage means a materialized product (ownership_changes / Oracle's
    # Lens) was NOT refreshed, and `partial_success` means some managers failed —
    # both must surface, not be swallowed.
    stage_failures: list[str] = []
    ownership_rows_by_quarter: dict[str, int] = {}
    lens_stage_job_ids: list[int] = []

    for quarter in quarters:
        result = _run_locked_stage(session, job_type="compute_ownership_changes", quarter=quarter)
        status = result["stage"]["status"]
        failure_count = result["summary"].get("failure_count")
        ownership_rows_by_quarter[quarter] = int(result["summary"].get("rows_created") or 0)
        log(f"[2/4] ownership_changes {quarter}: {status} rows={result['summary'].get('rows_created')} failures={failure_count}")
        if status != "succeeded":
            stage_failures.append(f"ownership_changes {quarter} stage status={status} (per-manager failures={failure_count})")

    for quarter in quarters:
        result = _run_locked_stage(session, job_type="oracles_lens_score_backfill", quarter=quarter)
        status = result["stage"]["status"]
        job_id = result["stage"].get("job_id")
        if job_id is not None:
            lens_stage_job_ids.append(job_id)
        log(f"[3/4] oracles_lens {quarter}: {status} scored={result['summary'].get('filings_scored')}")
        if status != "succeeded":
            stage_failures.append(f"oracles_lens {quarter} stage status={status}")

    failures = stage_failures + verify_attribution_rollout(session)
    failures += _run_freshness_failures(session, quarters, ownership_rows_by_quarter, lens_stage_job_ids)
    log(f"[4/4] verification: {'PASSED' if not failures else 'FAILED'}")
    return {"reattributed": reattributed, "quarters": quarters, "failures": failures}


def _active_direct_manager_count(session: Session, quarter: str) -> int:
    return session.execute(
        text(
            "SELECT COUNT(DISTINCT h.manager_id) FROM holdings_13f h "
            "JOIN parse_runs pr ON h.parse_run_id = pr.id AND pr.is_current "
            "JOIN filings_13f f ON f.accession_number = pr.accession_number "
            "AND f.is_active_for_manager_period AND f.form_type IN ('13F-HR', '13F-HR/A') "
            "WHERE h.report_quarter = :q AND h.holding_attribution_status = 'direct'"
        ),
        {"q": quarter},
    ).scalar() or 0


def _run_freshness_failures(
    session: Session,
    quarters: list[str],
    ownership_rows_by_quarter: dict[str, int],
    lens_stage_job_ids: list[int],
) -> list[str]:
    """RUN-SCOPED postconditions — proof THIS run actually refreshed both
    materialized products, not that stale historical data happens to exist. A
    stage can report `succeeded` while doing zero work (the compute contracts
    treat a no-op as success), so stage status alone is insufficient.

    - Ownership: every active *direct* filer in a quarter yields ≥1 change row, so
      0 rows written for a quarter that has active direct filers is a no-op
      recompute (a genuinely empty quarter has 0 active filers and is skipped).
    - Lens: at least one signal must be written under THIS run's Lens stage job
      ids (`source_job_id`) when the universe has active direct filers — a no-op
      or a lying summary writes none. (Individual quarters may legitimately score
      0 below the holder threshold; the aggregate over a populated universe cannot.)
    """
    failures: list[str] = []
    total_active = 0
    for quarter in quarters:
        active = _active_direct_manager_count(session, quarter)
        total_active += active
        if active > 0 and ownership_rows_by_quarter.get(quarter, 0) == 0:
            failures.append(
                f"ownership recompute wrote 0 rows for {quarter} despite {active} "
                f"active direct filers (no-op recompute?)"
            )

    if total_active > 0:
        lens_written = 0
        if lens_stage_job_ids:
            lens_written = session.execute(
                text("SELECT COUNT(*) FROM oracles_lens_signals WHERE source_job_id = ANY(:ids)"),
                {"ids": lens_stage_job_ids},
            ).scalar() or 0
        if lens_written == 0:
            failures.append(
                f"Oracle's Lens recompute wrote 0 signals this run (source_job_id) "
                f"despite {total_active} active direct filers (no-op recompute?)"
            )
    return failures
