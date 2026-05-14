"""MVP3-07 validation-gated historical backfill contract.

D1 (decision-gate): MVP 3 production historical backfill starts at
``DEFAULT_BACKFILL_START_QUARTER=2023-Q1`` by default. Pre-2023-Q1 backfill is
out of default production scope and may run only as an admin-triggered
dry-run / validation mode for a curated manager-quarter subset with explicit
approval. Backfilled quarters must enter a ``needs_validation`` audit state
until a per-quarter validation gate clears them.

This service owns the orchestration contract:

- ``preview_historical_backfill`` — pure read; returns the proposed scope, the
  pre-2023 / value-unit risk flag, and the per-quarter discovery summary.
- ``enqueue_historical_backfill`` — creates a ``JobRun`` with a deterministic
  ``lock_key``/``dedupe_key``. The partial unique index
  ``uq_job_runs_active_lock_key`` plus an ``IntegrityError`` translator handles
  the TOCTOU race the same way MVP3-05 does. Pre-2023 ranges require an
  explicit ``dry_run=True`` flag.
- ``execute_historical_backfill`` — walks the quarter range in order, skips
  manager-quarters that already have an active filing (no overwrite),
  delegates discovery + per-accession ingest to caller-injected functions, and
  records per-filing outcomes. After each quarter it invokes the caller's
  ``validation_gate``; on success the per-filing
  ``HISTORICAL_BACKFILL_NEEDS_VALIDATION`` findings flip to ``resolved``,
  otherwise they stay open and downstream readiness surfaces see the quarter
  as ``needs_validation``.

Existing MVP1B ingestion paths still own the network + parsing work; this
service is the validation-gate orchestrator that sits on top of them.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.institutions import (
    Filing13F,
    InstitutionManager,
    JobRun,
    QualityFinding13F,
    QualityReport13F,
)
from app.services.thirteenf_quality_codes import HISTORICAL_BACKFILL_NEEDS_VALIDATION

logger = logging.getLogger(__name__)

# Module-local readability alias for the canonical constant in
# ``thirteenf_quality_codes`` (MVP4-09); the canonical name is the source
# of truth and is exported there.
HISTORICAL_BACKFILL_RULE_CODE = HISTORICAL_BACKFILL_NEEDS_VALIDATION
JOB_TYPE = "historical_backfill"
_ACTIVE_JOB_STATUSES = ("queued", "running", "cancel_requested")
# Conservative report-quarter proxy for PRD §7.2's canonical value-unit
# transition rule, which is keyed on filing ``accepted_at >= 2023-01-03`` (the
# parser at ``app/edgar/parsers/value_units.py`` enforces the accepted_at form
# correctly). Q4 2022 is the boundary case: filings for period_of_report
# 2022-12-31 are commonly submitted in Jan-Feb 2023 and parse correctly as
# dollars under the accepted_at rule, but at backfill-preview time we do not
# know each accession's accepted_at; flagging any report_quarter < 2023-Q1 is
# the safe over-approximation that keeps the value-unit risk visible to the
# admin. (SME C3, MVP3 end-to-end review.)
_PRE_DOLLARS_BOUNDARY_REPORT_QUARTER = (2023, 1)


# Discovery returns metadata for accessions to consider for a (manager, quarter).
# Tests inject a stub; the production caller wires this to the existing EDGAR
# submissions parser. The keys we read are accession_number, manager_id, and
# report_quarter; additional keys are ignored.
FilingDiscoveryFn = Callable[[InstitutionManager, str], Iterable[dict[str, Any]]]

# Per-accession ingest. Receives the discovery metadata for one filing and
# returns a result dict whose ``status`` is consumed by the aggregate counters.
# Status convention: ``succeeded`` or ``failed`` (anything other than
# ``succeeded`` counts as a failure).
IngestFn = Callable[[Session, InstitutionManager, dict[str, Any]], dict[str, Any]]

# Validation gate: ``(passed, errors)``. Called once per quarter after all
# discovered filings have been processed.
ValidationGate = Callable[
    [Session, str, list[dict[str, Any]]],
    tuple[bool, list[str]],
]


class HistoricalBackfillError(ValueError):
    """Raised when historical-backfill scope is invalid or a duplicate batch is requested."""


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview_historical_backfill(
    session: Session,
    *,
    start_quarter: str | None = None,
    end_quarter: str | None = None,
    manager_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Pure read: report the proposed scope + risk flags without mutation."""
    start_q = _normalize_start_quarter(start_quarter)
    end_q = _normalize_end_quarter(end_quarter, start_q)
    quarters = _enumerate_quarters(start_q, end_q)
    managers = _resolve_managers(session, manager_ids)
    pre_2023 = _range_includes_pre_2023(quarters)

    kahn_in_scope = any(m.cik == "0001039565" for m in managers)
    return {
        "start_quarter": start_q,
        "end_quarter": end_q,
        "quarters": quarters,
        "manager_count": len(managers),
        "manager_ids": [m.id for m in managers],
        "value_unit_risk_warning": pre_2023,
        "requires_dry_run": pre_2023,
        "kahn_brothers_in_scope": kahn_in_scope,
    }


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def enqueue_historical_backfill(
    session: Session,
    *,
    start_quarter: str | None = None,
    end_quarter: str | None = None,
    manager_ids: list[int] | None = None,
    dry_run: bool = False,
    requested_by_user_id: int | None = None,
    trigger_source: str = "admin",
) -> JobRun:
    """Create a ``JobRun`` representing one historical-backfill batch.

    Pre-2023 quarters require ``dry_run=True`` per D1 to keep value-unit risk
    explicit and to avoid silently rolling production data back through the
    parser-spec transition.
    """
    start_q = _normalize_start_quarter(start_quarter)
    end_q = _normalize_end_quarter(end_quarter, start_q)
    quarters = _enumerate_quarters(start_q, end_q)
    if _range_includes_pre_2023(quarters) and not dry_run:
        raise HistoricalBackfillError(
            f"Pre-2023 backfill range [{start_q}, {end_q}] requires dry_run=True "
            "(D1: pre-2023 is dry-run / validation-mode only)."
        )

    manager_scope = "all_active_managers" if not manager_ids else f"managers:{_hash_ids(manager_ids)}"
    lock_key = f"13f_historical_backfill:{start_q}:{end_q}:{manager_scope}"

    active = _active_job_for_lock_key(session, lock_key)
    if active is not None:
        raise HistoricalBackfillError(
            f"Historical backfill already active for [{start_q}, {end_q}] "
            f"(job_id={active.id}, status={active.status})."
        )

    job = JobRun(
        job_type=JOB_TYPE,
        status="queued",
        trigger_source=trigger_source,
        requested_by_user_id=requested_by_user_id,
        lock_key=lock_key,
        dedupe_key=lock_key,
        quarter=start_q,
        input_json={
            "start_quarter": start_q,
            "end_quarter": end_q,
            "manager_ids": manager_ids,
            "dry_run": bool(dry_run),
        },
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        # Two simultaneous admin requests can both pass the pre-check; the
        # partial unique index uq_job_runs_active_lock_key still catches the
        # race at commit. Translate the raw DB error to the typed scope error
        # so callers see a single, predictable failure mode (matches MVP3-05).
        session.rollback()
        raise HistoricalBackfillError(
            f"Historical backfill already active for [{start_q}, {end_q}] "
            "(rejected by lock_key uniqueness)."
        ) from exc
    session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def execute_historical_backfill(
    session: Session,
    *,
    job_run_id: int,
    validation_gate: ValidationGate | None,
    filing_discovery_fn: FilingDiscoveryFn,
    ingest_fn: IngestFn,
) -> dict[str, Any]:
    """Walk the quarter range; for each (manager, quarter):

    1. Skip if an active filing already exists (no overwrite, D1).
    2. Discover candidate accessions via ``filing_discovery_fn``.
    3. Ingest each via ``ingest_fn`` (skipped entirely in ``dry_run``).
    4. After the quarter, run ``validation_gate``; on success flip the
       per-filing ``HISTORICAL_BACKFILL_NEEDS_VALIDATION`` findings to
       ``resolved``; otherwise leave them ``open``.

    Returns the aggregate impact summary and per-quarter detail.
    """
    if validation_gate is None:
        raise ValueError("validation_gate is required for historical backfill")

    job = session.get(JobRun, job_run_id)
    if job is None:
        raise HistoricalBackfillError(f"job_run not found: {job_run_id}")

    payload = job.input_json or {}
    start_q = payload.get("start_quarter") or _normalize_start_quarter(None)
    end_q = payload.get("end_quarter") or start_q
    manager_ids = payload.get("manager_ids")
    dry_run = bool(payload.get("dry_run"))
    quarters = _enumerate_quarters(start_q, end_q)
    managers = _resolve_managers(session, manager_ids)

    aggregate: dict[str, Any] = {
        "dry_run": dry_run,
        "quarters_scanned": len(quarters),
        "quarters_validated": 0,
        "quarters_needs_validation": 0,
        "filings_already_present": 0,
        "filings_ingested": 0,
        "filings_failed": 0,
        "filings_skipped": 0,
    }
    per_quarter: list[dict[str, Any]] = []

    for quarter in quarters:
        quarter_summary = _execute_quarter(
            session,
            quarter=quarter,
            managers=managers,
            filing_discovery_fn=filing_discovery_fn,
            ingest_fn=ingest_fn,
            validation_gate=validation_gate,
            dry_run=dry_run,
            aggregate=aggregate,
            job_run_id=job_run_id,
        )
        per_quarter.append(quarter_summary)

    overall = _overall_status(aggregate)
    summary_payload = {
        "scope": {
            "start_quarter": start_q,
            "end_quarter": end_q,
            "manager_ids": manager_ids,
        },
        "impact_summary": aggregate,
        "per_quarter": per_quarter,
    }
    # Re-fetch in case any per-quarter rollback detached the original job
    # reference. (MVP3-05 added the same defensive re-fetch.)
    job = session.get(JobRun, job_run_id)
    job.status = overall
    job.summary_json = summary_payload
    session.add(job)
    session.commit()

    return {
        "job_run_id": job.id,
        "status": overall,
        "impact_summary": aggregate,
        "per_quarter": per_quarter,
        "scope": {"start_quarter": start_q, "end_quarter": end_q, "manager_ids": manager_ids},
    }


# ---------------------------------------------------------------------------
# Per-quarter execution
# ---------------------------------------------------------------------------


def _execute_quarter(
    session: Session,
    *,
    quarter: str,
    managers: list[InstitutionManager],
    filing_discovery_fn: FilingDiscoveryFn,
    ingest_fn: IngestFn,
    validation_gate: ValidationGate,
    dry_run: bool,
    aggregate: dict[str, Any],
    job_run_id: int,
) -> dict[str, Any]:
    quarter_results: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for manager in managers:
        if _has_active_filing(session, manager_id=manager.id, quarter=quarter):
            aggregate["filings_already_present"] += 1
            quarter_results.append(
                {
                    "manager_id": manager.id,
                    "quarter": quarter,
                    "status": "skipped",
                    "reason": "already_ingested",
                }
            )
            continue

        for meta in filing_discovery_fn(manager, quarter):
            accession = meta.get("accession_number")
            if accession is None:
                continue
            if dry_run:
                aggregate["filings_skipped"] += 1
                quarter_results.append(
                    {
                        "manager_id": manager.id,
                        "quarter": quarter,
                        "accession_number": accession,
                        "status": "dry_run_skipped",
                    }
                )
                continue
            result = ingest_fn(session, manager, meta)
            if result.get("status") == "succeeded":
                aggregate["filings_ingested"] += 1
                quarter_results.append(
                    {
                        "manager_id": manager.id,
                        "quarter": quarter,
                        "accession_number": accession,
                        "status": "ingested",
                    }
                )
            else:
                aggregate["filings_failed"] += 1
                quarter_results.append(
                    {
                        "manager_id": manager.id,
                        "quarter": quarter,
                        "accession_number": accession,
                        "status": "failed",
                        "error": result.get("error"),
                    }
                )

    ingested_now = [r for r in quarter_results if r["status"] == "ingested"]
    failed_now = [r for r in quarter_results if r["status"] == "failed"]

    # Write the per-quarter audit event regardless of dry-run state so that the
    # admin dashboard can show "we tried, here's what we found." Dry-run runs
    # write a report with zero ingest findings; that's intentional.
    report = QualityReport13F(
        quarter=quarter,
        status="warning" if (ingested_now or failed_now) else "passed",
        error_count=len(failed_now),
        warning_count=len(ingested_now),
        info_count=0,
        summary=(
            f"Historical backfill {quarter}: "
            f"{len(ingested_now)} ingested, {len(failed_now)} failed, "
            f"{aggregate['filings_already_present']} already present, "
            f"dry_run={dry_run}."
        ),
        issues_json=quarter_results,
        source_job_id=job_run_id,
        is_dry_run=dry_run,
        checked_at=now,
    )
    session.add(report)
    session.flush()

    findings: list[QualityFinding13F] = []
    for entry in ingested_now + failed_now:
        finding = QualityFinding13F(
            validation_run_id=report.id,
            rule_code=HISTORICAL_BACKFILL_RULE_CODE,
            severity="warning",
            entity_type="filing",
            entity_id=None,
            quarter=quarter,
            manager_id=entry["manager_id"],
            accession_number=entry.get("accession_number"),
            detail=f"Historical backfill {entry['status']} for {quarter}; awaiting validation.",
            value_json={"backfill_status": entry["status"], "error": entry.get("error")},
            status="open",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(finding)
        findings.append(finding)
    session.flush()

    passed, validation_errors = validation_gate(session, quarter, quarter_results)
    if passed and not dry_run:
        aggregate["quarters_validated"] += 1
        # Only flip findings whose underlying ingest actually succeeded; a
        # failed ingest cannot be "validated as correct."
        for finding in findings:
            if (finding.value_json or {}).get("backfill_status") == "ingested":
                finding.status = "resolved"
                finding.resolved_at = now
                finding.resolution_note = "Validation gate passed."
                session.add(finding)
        session.flush()
    else:
        aggregate["quarters_needs_validation"] += 1
        if validation_errors:
            existing_issues = list(report.issues_json or [])
            existing_issues.append({"validation_errors": validation_errors})
            report.issues_json = existing_issues
            session.add(report)
            session.flush()

    return {
        "quarter": quarter,
        "ingested": len(ingested_now),
        "failed": len(failed_now),
        "validation_passed": bool(passed),
        "validation_errors": list(validation_errors or []),
        "quality_report_id": report.id,
    }


def _overall_status(aggregate: dict[str, Any]) -> str:
    if aggregate["quarters_scanned"] == 0:
        return "skipped"
    if aggregate["filings_failed"] == 0 and aggregate["quarters_needs_validation"] == 0:
        return "succeeded"
    if aggregate["quarters_validated"] == 0 and aggregate["filings_ingested"] == 0:
        return "failed"
    return "partial_success"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _active_job_for_lock_key(session: Session, lock_key: str) -> JobRun | None:
    # The partial unique index uq_job_runs_active_lock_key guarantees at most
    # one active row per lock_key in production. We still call .first() rather
    # than .one_or_none() so the pre-check is resilient if a test fixture or
    # repair script briefly leaves duplicate rows.
    return (
        session.query(JobRun)
        .filter(JobRun.lock_key == lock_key)
        .filter(JobRun.status.in_(_ACTIVE_JOB_STATUSES))
        .order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .first()
    )


def _normalize_start_quarter(start_quarter: str | None) -> str:
    if start_quarter is not None and start_quarter.strip():
        _validate_quarter(start_quarter)
        return start_quarter
    default = getattr(settings, "DEFAULT_BACKFILL_START_QUARTER", None) or "2023-Q1"
    return default


def _normalize_end_quarter(end_quarter: str | None, start_quarter: str) -> str:
    if end_quarter is None or not end_quarter.strip():
        return start_quarter
    _validate_quarter(end_quarter)
    if _quarter_key(end_quarter) < _quarter_key(start_quarter):
        raise HistoricalBackfillError(
            f"end_quarter {end_quarter} must not precede start_quarter {start_quarter}."
        )
    return end_quarter


def _validate_quarter(value: str) -> None:
    if "-Q" not in value:
        raise HistoricalBackfillError(f"quarter {value!r} invalid; expected YYYY-Q[1-4].")
    year_text, qtr_text = value.split("-Q", 1)
    if not (year_text.isdigit() and qtr_text.isdigit()) or int(qtr_text) not in (1, 2, 3, 4):
        raise HistoricalBackfillError(f"quarter {value!r} invalid; expected YYYY-Q[1-4].")


def _quarter_key(quarter: str) -> tuple[int, int]:
    year_text, qtr_text = quarter.split("-Q", 1)
    return (int(year_text), int(qtr_text))


def _enumerate_quarters(start_quarter: str, end_quarter: str) -> list[str]:
    start = _quarter_key(start_quarter)
    end = _quarter_key(end_quarter)
    out: list[str] = []
    year, qtr = start
    while (year, qtr) <= end:
        out.append(f"{year}-Q{qtr}")
        qtr += 1
        if qtr > 4:
            qtr = 1
            year += 1
    return out


def _range_includes_pre_2023(quarters: list[str]) -> bool:
    return any(_quarter_key(q) < _PRE_DOLLARS_BOUNDARY_REPORT_QUARTER for q in quarters)


def _resolve_managers(
    session: Session, manager_ids: list[int] | None
) -> list[InstitutionManager]:
    query = session.query(InstitutionManager).filter(InstitutionManager.status == "active")
    if manager_ids:
        query = query.filter(InstitutionManager.id.in_(manager_ids))
    return query.order_by(InstitutionManager.id.asc()).all()


def _has_active_filing(session: Session, *, manager_id: int, quarter: str) -> bool:
    return (
        session.query(Filing13F.id)
        .filter(Filing13F.manager_id == manager_id)
        .filter(Filing13F.report_quarter == quarter)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .first()
        is not None
    )


def _hash_ids(manager_ids: list[int]) -> str:
    # Order-stable digest of the manager id set, short enough for a lock_key.
    sorted_ids = ",".join(str(i) for i in sorted(set(manager_ids)))
    return sorted_ids[:80]
