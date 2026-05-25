"""Historical-backfill ops harness.

Task doc: ``docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md``

Invoke:

    docker compose exec -T api python -m scripts.run_historical_backfill \\
        --start-quarter 2023-Q1 --end-quarter 2025-Q3

What it does (three chained stages per quarter range):

1. ``historical_backfill`` — discovers each manager's 13F filings for
   the quarter via SEC submissions API + fetches each accession's
   ``primary_doc.xml``. Creates ``Filing13F`` rows in
   ``parse_status='pending'``. Does NOT fetch holdings yet.
2. ``ingest_holdings`` per quarter — iterates the pending Filing13F
   rows for the quarter, fetches each ``infotable.xml``, parses, and
   writes ``Holding13F`` rows with ``cusip_mapping_status='pending_mapping'``.
3. ``enrich_cusip`` — final pass that maps pending CUSIPs to tickers
   via OpenFIGI.

All three stages run SYNCHRONOUSLY in-process. JobRuns are created
for traceability — the job system's audit trail is the authoritative
record, the script's stdout is the convenience surface.

Runtime cost: real SEC EDGAR + OpenFIGI traffic through Rate Guard.
Each quarter ≈ 80 managers × ~3 fetches (submissions, primary_doc,
infotable) ≈ 240 SEC requests. At Rate Guard's edgar throttle
(~10 req/s) plus parse time: roughly 1-3 minutes per quarter.
11 quarters: 15-30 minutes.

The script does NOT cover pre-2023 quarters — those require
``--dry-run`` because of the value-unit semantic transition (D1).
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.db import SessionLocal
from app.models.institutions import Filing13F, InstitutionManager, JobRun
from app.services.thirteenf_historical_backfill import (
    HistoricalBackfillError,
    enqueue_historical_backfill,
)


# Per review-1 B5 / review-2 O1: the harness sets ``lease_expires_at``
# on every manually-claimed JobRun so that ``mark_stale_running_jobs_abandoned``
# can recover a crashed run. 4 hours matches the longest production
# stage-job timeout (backfill_*); the harness itself shouldn't take
# anywhere near that long, but this gives the reaper a clear cutoff.
_HARNESS_LEASE_SECONDS = 4 * 60 * 60


def _complete_from_summary(
    session,
    *,
    job_id: int,
    worker_id: str,
    lease_token: str,
    summary: dict[str, Any] | None,
    error_message: str | None,
) -> str:
    """Complete a leased JobRun, deriving the final status from the
    executor's summary.

    Per review-1 B6 / review-2 B6: many ``_execute_job`` handlers
    return ``status='partial_success'`` when a job did real work but
    had per-item failures — that's success-with-caveat, not failure.
    The harness must accept it; otherwise downstream stages don't run
    and the per-quarter trace lies about progress.
    """
    from app.services.thirteenf_job_worker import complete_leased_job

    if error_message is not None:
        status = "failed"
    else:
        exec_status = (summary or {}).get("status", "succeeded")
        # ``failed`` from the executor (no exception, but explicit
        # status='failed' in the returned summary) must propagate as
        # failed — otherwise the harness's stage-failure tracking and
        # exit code lie about what happened. ``succeeded`` and
        # ``partial_success`` propagate as themselves. Anything else
        # (forward-compat for future statuses like 'skipped' /
        # 'cancelled') conservatively falls back to ``succeeded`` so a
        # new state doesn't crash the bookkeeping coordinator.
        if exec_status in {"succeeded", "partial_success", "failed"}:
            status = exec_status
        else:
            status = "succeeded"

    complete_leased_job(
        session,
        job_id=job_id,
        worker_id=worker_id,
        lease_token=lease_token,
        status=status,
        summary_json=summary,
        error_message=error_message,
    )
    return status


def _historical_depth_quarters(session) -> int:
    """Count distinct report_quarters with at least one active filing.

    Mirrors the metric the Readiness page surfaces as
    "Historical depth: N quarters". The fewer assumptions about
    completeness-per-quarter we bake in here, the more useful the
    'before vs after' number is — we just count how many distinct
    quarters now have any active 13F-HR data at all.
    """
    from sqlalchemy import distinct
    return int(
        session.query(distinct(Filing13F.report_quarter))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .count()
    )


def _holdings_depth_quarters(session) -> int:
    """Count distinct report_quarters with at least one ingested holding.

    This is the metric that matters for Oracle's Lens — without
    Holding13F rows, there's no signal. ``_historical_depth_quarters``
    counts filings; this counts holdings, which is the truer "we have
    usable data for this quarter" gate.
    """
    from sqlalchemy import distinct
    from app.models.institutions import Holding13F
    return int(
        session.query(distinct(Holding13F.report_quarter)).count()
    )


def _confirmed_manager_count(session) -> int:
    return int(
        session.query(InstitutionManager)
        .filter(
            InstitutionManager.match_status == "confirmed",
            InstitutionManager.cik.isnot(None),
        )
        .count()
    )


def _run_one_range(
    *,
    start_quarter: str,
    end_quarter: str,
    dry_run: bool,
) -> dict:
    """Enqueue + synchronously execute one historical-backfill batch.

    Returns the executor's summary_json so the caller can render it.
    Only does stage 1 (filing discovery + primary_doc). Holdings
    ingest is a separate per-quarter ``ingest_holdings`` job; see
    ``_run_ingest_holdings``.
    """
    # Lazy imports — the heavy ingestion deps shouldn't load just for
    # someone running --help.
    from app.services.thirteenf_admin_dashboard import _execute_job

    worker_id = f"backfill-harness-{uuid.uuid4().hex[:8]}"

    with SessionLocal() as session:
        try:
            job = enqueue_historical_backfill(
                session,
                start_quarter=start_quarter,
                end_quarter=end_quarter,
                dry_run=dry_run,
                trigger_source="ops_harness",
            )
        except HistoricalBackfillError as exc:
            print(f"  ENQUEUE FAILED: {exc}")
            return {"status": "enqueue_failed", "error": str(exc)}

        job_id = job.id
        # Claim the job manually (no live worker assumed).
        now = datetime.now(timezone.utc)
        job.status = "running"
        job.worker_id = worker_id
        job.lease_token = uuid.uuid4().hex
        job.started_at = now
        job.lease_expires_at = now + timedelta(seconds=_HARNESS_LEASE_SECONDS)
        session.add(job)
        session.commit()
        lease_token = job.lease_token

        payload = dict(job.input_json or {})
        payload["_job_id"] = job_id

        try:
            summary = _execute_job(session, "historical_backfill", payload)
            error_message = None
        except Exception as exc:  # noqa: BLE001 — surface every failure mode
            summary = {"error": str(exc)}
            error_message = str(exc)

        status = _complete_from_summary(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            summary=summary,
            error_message=error_message,
        )
        return {"job_id": job_id, "status": status, "summary": summary}


def _run_ingest_holdings(quarter: str) -> dict:
    """Synchronously run an ``ingest_holdings`` job for one quarter.

    This is stage 2 of the historical-backfill flow: take the
    ``Filing13F`` rows in ``parse_status='pending'`` for the quarter,
    fetch each ``infotable.xml``, parse, and write ``Holding13F`` rows.
    """
    from app.services.thirteenf_admin_dashboard import _execute_job

    worker_id = f"holdings-harness-{uuid.uuid4().hex[:8]}"
    lock_key = f"ingest_holdings:{quarter}"

    with SessionLocal() as session:
        # Skip if an active job already exists for this lock_key.
        from sqlalchemy import and_
        from app.services.thirteenf_admin_dashboard import ACTIVE_JOB_STATUSES
        active = (
            session.query(JobRun)
            .filter(and_(
                JobRun.lock_key == lock_key,
                JobRun.status.in_(ACTIVE_JOB_STATUSES),
            ))
            .first()
        )
        if active is not None:
            return {"status": "conflict", "active_job_id": active.id}

        now = datetime.now(timezone.utc)
        job = JobRun(
            job_type="ingest_holdings",
            status="running",
            trigger_source="ops_harness",
            lock_key=lock_key,
            dedupe_key=lock_key,
            quarter=quarter,
            started_at=now,
            worker_id=worker_id,
            lease_token=uuid.uuid4().hex,
            lease_expires_at=now + timedelta(seconds=_HARNESS_LEASE_SECONDS),
            input_json={"quarter": quarter},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id, lease_token = job.id, job.lease_token

        payload = {"quarter": quarter, "_job_id": job_id}
        try:
            summary = _execute_job(session, "ingest_holdings", payload)
            error_message = None
        except Exception as exc:  # noqa: BLE001
            summary = {"error": str(exc)}
            error_message = str(exc)

        status = _complete_from_summary(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            summary=summary,
            error_message=error_message,
        )
        return {"job_id": job_id, "status": status, "summary": summary}


def _run_score_backfill(quarter: str) -> dict:
    """Synchronously run ``oracles_lens_score_backfill`` for one quarter.

    Stage 4 (review-2 Q6): without this, the persisted
    ``oracles_lens_signals`` table has no rows for the backfilled
    quarters. The Oracle's Lens "All" universe path reads persisted
    scores, so without re-running this job the new historical data
    is invisible there. (The universe-filter "live recompute" path
    still works fine — it queries holdings directly.)
    """
    from app.services.thirteenf_admin_dashboard import _execute_job

    worker_id = f"score-harness-{uuid.uuid4().hex[:8]}"
    # Lock-key shape mirrors the production builder in _JOB_LOCK_BUILDERS.
    from app.services.oracles_lens.signal_weighted_score import SCORE_VERSION
    lock_key = f"oracles_lens_score:{quarter}:{SCORE_VERSION}"

    with SessionLocal() as session:
        from app.services.thirteenf_admin_dashboard import ACTIVE_JOB_STATUSES
        active = (
            session.query(JobRun)
            .filter(JobRun.lock_key == lock_key)
            .filter(JobRun.status.in_(ACTIVE_JOB_STATUSES))
            .first()
        )
        if active is not None:
            return {"status": "conflict", "active_job_id": active.id}

        now = datetime.now(timezone.utc)
        job = JobRun(
            job_type="oracles_lens_score_backfill",
            status="running",
            trigger_source="ops_harness",
            lock_key=lock_key,
            dedupe_key=lock_key,
            quarter=quarter,
            started_at=now,
            worker_id=worker_id,
            lease_token=uuid.uuid4().hex,
            lease_expires_at=now + timedelta(seconds=_HARNESS_LEASE_SECONDS),
            input_json={"quarter": quarter},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id, lease_token = job.id, job.lease_token

        payload = {"quarter": quarter, "_job_id": job_id}
        try:
            summary = _execute_job(session, "oracles_lens_score_backfill", payload)
            error_message = None
        except Exception as exc:  # noqa: BLE001
            summary = {"error": str(exc)}
            error_message = str(exc)

        status = _complete_from_summary(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            summary=summary,
            error_message=error_message,
        )
        return {"job_id": job_id, "status": status, "summary": summary}


def _run_enrich_cusip() -> dict:
    """Run the global CUSIP enrichment job once at the end."""
    from app.services.thirteenf_admin_dashboard import _execute_job

    worker_id = f"cusip-harness-{uuid.uuid4().hex[:8]}"
    lock_key = "enrich_cusip:global"

    with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        job = JobRun(
            job_type="enrich_cusip",
            status="running",
            trigger_source="ops_harness",
            lock_key=lock_key,
            dedupe_key=lock_key,
            started_at=now,
            worker_id=worker_id,
            lease_token=uuid.uuid4().hex,
            lease_expires_at=now + timedelta(seconds=_HARNESS_LEASE_SECONDS),
            input_json={},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id, lease_token = job.id, job.lease_token

        try:
            summary = _execute_job(session, "enrich_cusip", {})
            error_message = None
        except Exception as exc:  # noqa: BLE001
            summary = {"error": str(exc)}
            error_message = str(exc)

        status = _complete_from_summary(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            summary=summary,
            error_message=error_message,
        )
        return {"job_id": job_id, "status": status, "summary": summary}


def _render_quarter_row(quarter: str, q_summary: dict) -> str:
    cols = [
        quarter,
        str(q_summary.get("ingested", "—")),
        str(q_summary.get("already_present", "—")),
        str(q_summary.get("failed", "—")),
        "passed" if q_summary.get("validation_passed") else "failed",
    ]
    return " | ".join(f"{c:>20}" for c in cols)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_historical_backfill",
        description=(
            "Ops harness: synchronously run historical 13F-HR backfill "
            "for a quarter range against the confirmed-manager universe."
        ),
    )
    parser.add_argument(
        "--start-quarter", required=True,
        help="Earliest report quarter (inclusive). E.g. 2023-Q1.",
    )
    parser.add_argument(
        "--end-quarter", required=True,
        help="Latest report quarter (inclusive). E.g. 2025-Q3.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Pass dry_run=True to the executor (required for pre-2023).",
    )
    parser.add_argument(
        "--per-quarter", action="store_true",
        help=(
            "Run one JobRun per quarter (default: one JobRun for the "
            "full range, executor iterates internally). Per-quarter "
            "gives finer-grained traces but ~Nx the JobRun overhead."
        ),
    )
    parser.add_argument(
        "--skip-holdings", action="store_true",
        help=(
            "Skip stage 2 (ingest_holdings per quarter). Useful if you "
            "only want filing metadata for a fast test, or are running "
            "ingest_holdings separately."
        ),
    )
    parser.add_argument(
        "--skip-enrich-cusip", action="store_true",
        help="Skip the final enrich_cusip pass.",
    )
    parser.add_argument(
        "--skip-score-backfill", action="store_true",
        help=(
            "Skip stage 4 (oracles_lens_score_backfill per quarter). The "
            "universe-filter live-recompute path on Oracle's Lens works "
            "without it; the 'All' universe persisted-score path does NOT, "
            "so skipping leaves the All view incomplete for the backfilled "
            "quarters."
        ),
    )
    args = parser.parse_args(argv)

    # Stage outcomes that contribute to the final exit code. Any non-
    # success status across any stage flips ``exit_code`` to 1 so CI /
    # cron consumers can detect partial degradation without parsing
    # stdout. ``conflict`` and ``enqueue_failed`` count as failures —
    # the harness was asked to do work it didn't do.
    exit_code = 0

    def _mark_failure(stage: str, q: str | None, status: str) -> None:
        nonlocal exit_code
        exit_code = 1
        sys.stderr.write(
            f"[harness] FAILURE in stage={stage} "
            f"quarter={q or '-'} status={status}\n"
        )

    def _stage_ok(status: str | None) -> bool:
        return status in {"succeeded", "partial_success"}

    with SessionLocal() as s:
        depth_before = _historical_depth_quarters(s)
        holdings_before = _holdings_depth_quarters(s)
        manager_count = _confirmed_manager_count(s)
    print(
        f"Before: filings_depth={depth_before}q, holdings_depth={holdings_before}q, "
        f"confirmed_managers={manager_count}"
    )
    print()

    if args.per_quarter:
        # Iterate quarters newest → oldest so any early-fail surfaces
        # near the recent end (where validation matters most).
        from app.services.thirteenf_historical_backfill import (
            _enumerate_quarters, _normalize_start_quarter, _normalize_end_quarter,
        )
        start_q = _normalize_start_quarter(args.start_quarter)
        end_q = _normalize_end_quarter(args.end_quarter, start_q)
        quarters = list(reversed(_enumerate_quarters(start_q, end_q)))

        print(f"Running {len(quarters)} per-quarter jobs:")
        print(f"  {'quarter':>20} | {'ingested':>20} | {'already_present':>20} | "
              f"{'failed':>20} | {'validation':>20}")
        for q in quarters:
            result = _run_one_range(start_quarter=q, end_quarter=q, dry_run=args.dry_run)
            summary = result.get("summary") or {}
            per_quarter = summary.get("per_quarter") or []
            if per_quarter:
                print(f"  {_render_quarter_row(q, per_quarter[0])}")
            else:
                print(f"  {q:>20} | (no per_quarter data: status={result.get('status')})")
            if not _stage_ok(result.get("status")):
                _mark_failure("stage1_historical_backfill", q, result.get("status") or "unknown")
    else:
        # Single batch — executor walks internally.
        print(f"Running single batch for {args.start_quarter} → {args.end_quarter}:")
        result = _run_one_range(
            start_quarter=args.start_quarter,
            end_quarter=args.end_quarter,
            dry_run=args.dry_run,
        )
        summary = result.get("summary") or {}
        print(f"\nJob {result.get('job_id')} status={result.get('status')}")
        for q_summary in summary.get("per_quarter") or []:
            print(f"  {_render_quarter_row(q_summary.get('quarter', '?'), q_summary)}")
        impact = summary.get("impact_summary") or {}
        if impact:
            print(
                f"\nImpact: ingested={impact.get('filings_ingested')} "
                f"already_present={impact.get('filings_already_present')} "
                f"failed={impact.get('filings_failed')} "
                f"skipped={impact.get('filings_skipped')} "
                f"quarters_validated={impact.get('quarters_validated')}"
            )
        if not _stage_ok(result.get("status")):
            _mark_failure("stage1_historical_backfill", None, result.get("status") or "unknown")

    # Stage 2: ingest_holdings per quarter.
    if not args.skip_holdings and not args.dry_run:
        from app.services.thirteenf_historical_backfill import (
            _enumerate_quarters,
            _normalize_end_quarter,
            _normalize_start_quarter,
        )
        start_q = _normalize_start_quarter(args.start_quarter)
        end_q = _normalize_end_quarter(args.end_quarter, start_q)
        quarters_for_holdings = list(reversed(_enumerate_quarters(start_q, end_q)))
        print(f"\nStage 2: ingest_holdings per quarter ({len(quarters_for_holdings)} quarters):")
        for q in quarters_for_holdings:
            res = _run_ingest_holdings(q)
            summary = res.get("summary") or {}
            if res.get("status") in {"succeeded", "partial_success"}:
                tail = f" [partial_success]" if res.get("status") == "partial_success" else ""
                print(
                    f"  {q}: filings_processed={summary.get('filings_processed')} "
                    f"xml_fetched={summary.get('filings_xml_fetched')} "
                    f"holdings_inserted={summary.get('holdings_inserted')} "
                    f"failed={summary.get('filings_failed')}{tail}"
                )
            else:
                print(f"  {q}: STATUS={res.get('status')} error={summary.get('error')}")
                _mark_failure("stage2_ingest_holdings", q, res.get("status") or "unknown")

    # Stage 3: enrich_cusip global pass.
    if not args.skip_enrich_cusip and not args.dry_run:
        print("\nStage 3: enrich_cusip (global)")
        res = _run_enrich_cusip()
        summary = res.get("summary") or {}
        if res.get("status") in {"succeeded", "partial_success"}:
            print(
                f"  mappings_created={summary.get('mappings_created')} "
                f"new_stocks={summary.get('new_stocks')} "
                f"holdings_linked={summary.get('holdings_linked')} "
                f"still_unmapped={summary.get('holdings_still_unmapped')}"
            )
        else:
            print(f"  STATUS={res.get('status')} error={summary.get('error')}")
            _mark_failure("stage3_enrich_cusip", None, res.get("status") or "unknown")

    # Stage 4: oracles_lens_score_backfill per quarter (review-2 Q6).
    if not args.skip_score_backfill and not args.dry_run:
        from app.services.thirteenf_historical_backfill import (
            _enumerate_quarters,
            _normalize_end_quarter,
            _normalize_start_quarter,
        )
        start_q = _normalize_start_quarter(args.start_quarter)
        end_q = _normalize_end_quarter(args.end_quarter, start_q)
        quarters_for_score = list(reversed(_enumerate_quarters(start_q, end_q)))
        print(
            f"\nStage 4: oracles_lens_score_backfill per quarter "
            f"({len(quarters_for_score)} quarters):"
        )
        for q in quarters_for_score:
            res = _run_score_backfill(q)
            summary = res.get("summary") or {}
            if res.get("status") in {"succeeded", "partial_success"}:
                print(
                    f"  {q}: filings_scored={summary.get('filings_scored')} "
                    f"components_written={summary.get('components_written')}"
                )
            else:
                print(f"  {q}: STATUS={res.get('status')} error={summary.get('error')}")
                _mark_failure("stage4_score_backfill", q, res.get("status") or "unknown")

    with SessionLocal() as s:
        depth_after = _historical_depth_quarters(s)
        holdings_after = _holdings_depth_quarters(s)
    print(
        f"\nAfter:  filings_depth={depth_after}q (was {depth_before}q), "
        f"holdings_depth={holdings_after}q (was {holdings_before}q)"
    )
    if exit_code != 0:
        sys.stderr.write(
            f"[harness] one or more stages reported failure/conflict; "
            f"exit_code={exit_code}\n"
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
