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

    change_failures = 0
    for quarter in quarters:
        result = _run_locked_stage(session, job_type="compute_ownership_changes", quarter=quarter)
        change_failures += int(result["summary"].get("failure_count", 0))
        log(
            f"[2/4] ownership_changes {quarter}: {result['stage']['status']} "
            f"rows={result['summary'].get('rows_created')} failures={result['summary'].get('failure_count')}"
        )

    for quarter in quarters:
        result = _run_locked_stage(session, job_type="oracles_lens_score_backfill", quarter=quarter)
        log(f"[3/4] oracles_lens {quarter}: {result['stage']['status']} scored={result['summary'].get('filings_scored')}")

    failures = verify_attribution_rollout(session)
    if change_failures:
        failures.append(f"{change_failures} per-manager ownership-change recompute failures")
    log(f"[4/4] verification: {'PASSED' if not failures else 'FAILED'}")
    return {"reattributed": reattributed, "quarters": quarters, "failures": failures}
