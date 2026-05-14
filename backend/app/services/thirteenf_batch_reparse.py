"""MVP3-05 batch 13F reparse contract.

Fans the MVP3-04 single-filing controlled reparse out across a quarter or a
manager scope. Preview, enqueue, and execute are intentionally separate steps:

- preview: pure read; returns candidate filings and the lock_key the eventual
  enqueue will use.
- enqueue: creates a ``job_runs`` row with a stable ``lock_key`` and
  ``dedupe_key``; the partial unique index on (lock_key WHERE active) prevents
  a second active batch for the same scope. We additionally pre-check and raise
  a typed error so the caller gets a meaningful 4xx instead of an IntegrityError.
- execute: loops candidate filings and delegates to
  :func:`controlled_reparse_accession` per filing. A single filing failure does
  not poison sibling filings; it is recorded in the per-filing report.

This service ships the contract only. Admin API/UI wiring (PRD §13
``reparse-by-quarter`` / ``reparse-by-manager``) is out of scope for MVP3-05.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.institutions import Filing13F, JobRun
from app.services.thirteenf_controlled_reparse import (
    ControlledReparseResult,
    ValidationGate,
    controlled_reparse_accession,
)

logger = logging.getLogger(__name__)


InfotableProvider = Callable[[str], bytes | None]


class BatchReparseScopeError(ValueError):
    """Raised when batch scope is invalid or a duplicate batch is requested."""


_QUARTER_JOB_TYPE = "batch_reparse_by_quarter"
_MANAGER_JOB_TYPE = "batch_reparse_by_manager"
_ACTIVE_JOB_STATUSES = ("queued", "running", "cancel_requested")


def preview_batch_reparse(
    session: Session,
    *,
    quarter: str | None = None,
    manager_id: int | None = None,
) -> dict[str, Any]:
    """Pure read: returns candidate filings and lock_key without mutation."""
    scope = _normalize_scope(quarter=quarter, manager_id=manager_id)
    candidates = _candidate_filings(session, scope)
    return {
        "scope": {"kind": scope.kind, "value": scope.value},
        "lock_key": scope.lock_key,
        "dedupe_key": scope.lock_key,
        "job_type": scope.job_type,
        "candidate_filings": [
            {
                "accession_number": filing.accession_number,
                "manager_id": filing.manager_id,
                "report_quarter": filing.report_quarter,
                "coverage_type": filing.coverage_type,
                "has_raw_infotable": filing.raw_infotable_doc_id is not None,
            }
            for filing in candidates
        ],
        "estimated_scope": {
            "candidate_count": len(candidates),
            "missing_raw_infotable_count": sum(
                1 for filing in candidates if filing.raw_infotable_doc_id is None
            ),
        },
        "requires_confirmation": True,
        "warnings": [
            "13F batch reparse calls the EDGAR client when raw documents are not cached.",
            "Validation/readiness gate is required at execute time.",
        ],
    }


def enqueue_batch_reparse(
    session: Session,
    *,
    quarter: str | None = None,
    manager_id: int | None = None,
    requested_by_user_id: int | None = None,
    trigger_source: str = "admin",
) -> JobRun:
    """Create a job_runs row for the batch.

    Raises ``BatchReparseScopeError`` if another batch is already active for
    the same scope (lock_key is unique among active statuses).
    """
    scope = _normalize_scope(quarter=quarter, manager_id=manager_id)

    active = _active_job_for_lock_key(session, scope.lock_key)
    if active is not None:
        raise BatchReparseScopeError(
            f"Batch reparse already active for {scope.kind}={scope.value!r} "
            f"(job_id={active.id}, status={active.status})."
        )

    job = JobRun(
        job_type=scope.job_type,
        status="queued",
        trigger_source=trigger_source,
        requested_by_user_id=requested_by_user_id,
        lock_key=scope.lock_key,
        dedupe_key=scope.lock_key,
        quarter=scope.value if scope.kind == "quarter" else None,
        input_json={"scope": {"kind": scope.kind, "value": scope.value}},
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        # TOCTOU: two simultaneous admin requests can both pass the pre-check;
        # the partial unique index uq_job_runs_active_lock_key still catches the
        # race at commit. Translate the raw DB error to the typed scope error
        # so callers see a single, predictable failure mode.
        session.rollback()
        raise BatchReparseScopeError(
            f"Batch reparse already active for {scope.kind}={scope.value!r} "
            "(rejected by lock_key uniqueness)."
        ) from exc
    session.refresh(job)
    return job


def execute_batch_reparse(
    session: Session,
    *,
    job_run_id: int,
    validation_gate: ValidationGate | None,
    infotable_provider: InfotableProvider | None = None,
) -> dict[str, Any]:
    """Run controlled reparse for each candidate filing under ``job_run_id``.

    Per-filing failures are isolated: a controlled reparse exception is caught,
    the session is rolled back so the next filing starts clean, and the failure
    is recorded in the per-filing report. The aggregate ``status`` is:

    - ``succeeded``      — every attempted filing succeeded
    - ``partial_success`` — at least one failed/skipped but at least one succeeded
    - ``failed``         — every attempted filing failed
    - ``skipped``        — no filings were attempted (all skipped or none in scope)

    Cancellation: MVP3-05 does not poll ``job_runs.status`` mid-batch. A
    ``cancel_requested`` flip after this loop starts runs to completion; the
    worker observes the cancel only after the aggregate is committed. Batches
    are expected to be short enough that this is acceptable; preemptive
    cancellation is a deferred concern for the future admin endpoint task.
    """
    if validation_gate is None:
        raise ValueError("validation_gate is required for batch reparse")

    job = session.get(JobRun, job_run_id)
    if job is None:
        raise BatchReparseScopeError(f"job_run not found: {job_run_id}")

    scope = _scope_from_job(job)
    # Snapshot candidates as a plain list of facts so we can survive a per-filing
    # rollback (which detaches/expires ORM-tracked objects) and still iterate.
    candidates = [
        {
            "accession_number": filing.accession_number,
            "manager_id": filing.manager_id,
            "has_raw_infotable": filing.raw_infotable_doc_id is not None,
        }
        for filing in _candidate_filings(session, scope)
    ]

    per_filing: list[dict[str, Any]] = []
    aggregate = _new_aggregate()
    aggregate["filings_scanned"] = len(candidates)

    for candidate in candidates:
        accession = candidate["accession_number"]
        manager_id = candidate["manager_id"]
        infotable_bytes = (
            infotable_provider(accession) if infotable_provider is not None else None
        )
        if infotable_bytes is None and not candidate["has_raw_infotable"]:
            per_filing.append(
                {
                    "accession_number": accession,
                    "manager_id": manager_id,
                    "status": "skipped",
                    "reason": "no_raw_infotable",
                }
            )
            aggregate["filings_skipped"] += 1
            continue

        try:
            result = controlled_reparse_accession(
                session,
                accession,
                infotable_bytes=infotable_bytes,
                validation_gate=validation_gate,
            )
        except Exception as exc:  # isolate sibling filings from invariant failures
            # controlled_reparse_accession only raises for invariant ValueErrors
            # (override mismatch, non-pending override, missing validation_gate).
            # Those happen before any session writes, so no rollback is needed
            # and sibling filings remain unaffected.
            logger.warning(
                "batch_reparse: controlled reparse rejected %s: %s",
                accession,
                exc,
            )
            per_filing.append(
                {
                    "accession_number": accession,
                    "manager_id": manager_id,
                    "status": "rejected",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            aggregate["filings_attempted"] += 1
            aggregate["filings_failed"] += 1
            continue

        _accumulate(aggregate, result)
        per_filing.append(
            {
                "accession_number": accession,
                "manager_id": manager_id,
                "status": result.status,
                "old_parse_run_id": result.old_parse_run_id,
                "new_parse_run_id": result.new_parse_run_id,
                "validation_errors": list(result.validation_errors),
            }
        )

    overall = _overall_status(aggregate)
    impact_summary = _finalize_impact(aggregate)

    summary_payload = {
        "scope": {"kind": scope.kind, "value": scope.value},
        "impact_summary": impact_summary,
        "per_filing": per_filing,
    }
    # Re-fetch in case a per-filing rollback detached the original job reference.
    job = session.get(JobRun, job_run_id)
    job.status = overall
    job.summary_json = summary_payload
    session.add(job)
    session.commit()

    return {
        "job_run_id": job.id,
        "status": overall,
        "impact_summary": impact_summary,
        "per_filing": per_filing,
        "scope": {"kind": scope.kind, "value": scope.value},
    }


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------


class _Scope:
    __slots__ = ("kind", "value", "lock_key", "job_type")

    def __init__(self, kind: str, value: str, lock_key: str, job_type: str) -> None:
        self.kind = kind
        self.value = value
        self.lock_key = lock_key
        self.job_type = job_type


def _normalize_scope(*, quarter: str | None, manager_id: int | None) -> _Scope:
    if quarter is None and manager_id is None:
        raise BatchReparseScopeError("Exactly one of quarter or manager_id is required.")
    if quarter is not None and manager_id is not None:
        raise BatchReparseScopeError("quarter and manager_id are mutually exclusive.")
    if quarter is not None:
        return _Scope(
            kind="quarter",
            value=str(quarter),
            lock_key=f"13f_batch_reparse:quarter:{quarter}",
            job_type=_QUARTER_JOB_TYPE,
        )
    return _Scope(
        kind="manager",
        value=str(manager_id),
        lock_key=f"13f_batch_reparse:manager:{manager_id}",
        job_type=_MANAGER_JOB_TYPE,
    )


def _scope_from_job(job: JobRun) -> _Scope:
    raw_scope = (job.input_json or {}).get("scope") or {}
    kind = raw_scope.get("kind")
    value = raw_scope.get("value")
    if kind == "quarter" and value is not None:
        return _normalize_scope(quarter=str(value), manager_id=None)
    if kind == "manager" and value is not None:
        return _normalize_scope(quarter=None, manager_id=int(value))
    raise BatchReparseScopeError(
        f"job_run {job.id} has unrecognized batch scope: {raw_scope!r}"
    )


def _active_job_for_lock_key(session: Session, lock_key: str) -> JobRun | None:
    return (
        session.query(JobRun)
        .filter(JobRun.lock_key == lock_key)
        .filter(JobRun.status.in_(_ACTIVE_JOB_STATUSES))
        .one_or_none()
    )


def _candidate_filings(session: Session, scope: _Scope) -> list[Filing13F]:
    query = (
        session.query(Filing13F)
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        # NT filings have no holdings table; PRD §7.3 query contract excludes them.
        .filter(Filing13F.coverage_type != "notice_reported_elsewhere")
    )
    if scope.kind == "quarter":
        query = query.filter(Filing13F.report_quarter == scope.value)
    else:
        query = query.filter(Filing13F.manager_id == int(scope.value))
    return query.order_by(Filing13F.manager_id.asc(), Filing13F.id.asc()).all()


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _new_aggregate() -> dict[str, Any]:
    return {
        "filings_scanned": 0,
        "filings_attempted": 0,
        "filings_succeeded": 0,
        "filings_failed": 0,
        "filings_skipped": 0,
        "parse_runs_created": 0,
        "current_pointers_changed": 0,
        "holdings_rows_before": 0,
        "holdings_rows_after": 0,
        "holdings_rows_created": 0,
        "holdings_row_count_delta": 0,
        "ownership_changes_recompute_count": 0,
        "ownership_changes_recompute_scope": [],
        "readiness_level_impact": {"parse_status_before": {}, "parse_status_after": {}},
        "quality_finding_delta": {"open_before": 0, "open_after": 0, "delta": 0},
    }


def _accumulate(aggregate: dict[str, Any], result: ControlledReparseResult) -> None:
    aggregate["filings_attempted"] += 1
    if result.status == "succeeded":
        aggregate["filings_succeeded"] += 1
    else:
        aggregate["filings_failed"] += 1

    impact = result.impact_summary
    aggregate["parse_runs_created"] += impact.parse_runs_created
    aggregate["current_pointers_changed"] += impact.current_pointers_changed
    aggregate["holdings_rows_before"] += impact.holdings_rows_before
    aggregate["holdings_rows_after"] += impact.holdings_rows_after
    aggregate["holdings_rows_created"] += impact.holdings_rows_created
    aggregate["holdings_row_count_delta"] += impact.holdings_row_count_delta
    aggregate["ownership_changes_recompute_count"] += impact.ownership_changes_recompute_count
    aggregate["ownership_changes_recompute_scope"].append(
        dict(impact.ownership_changes_recompute_scope)
    )

    readiness = impact.readiness_level_impact
    before_key = str(readiness.get("parse_status_before") or "unknown")
    after_key = str(readiness.get("parse_status_after") or "unknown")
    aggregate["readiness_level_impact"]["parse_status_before"][before_key] = (
        aggregate["readiness_level_impact"]["parse_status_before"].get(before_key, 0) + 1
    )
    aggregate["readiness_level_impact"]["parse_status_after"][after_key] = (
        aggregate["readiness_level_impact"]["parse_status_after"].get(after_key, 0) + 1
    )

    qfd = impact.quality_finding_delta
    aggregate["quality_finding_delta"]["open_before"] += int(qfd.get("open_before") or 0)
    aggregate["quality_finding_delta"]["open_after"] += int(qfd.get("open_after") or 0)
    aggregate["quality_finding_delta"]["delta"] += int(qfd.get("delta") or 0)


def _overall_status(aggregate: dict[str, Any]) -> str:
    attempted = aggregate["filings_attempted"]
    succeeded = aggregate["filings_succeeded"]
    failed = aggregate["filings_failed"]
    skipped = aggregate["filings_skipped"]
    if attempted == 0:
        return "skipped"
    if failed == 0 and skipped == 0:
        return "succeeded"
    if succeeded == 0:
        return "failed"
    return "partial_success"


def _finalize_impact(aggregate: dict[str, Any]) -> dict[str, Any]:
    # Deep copy is unnecessary: callers receive a freshly built payload, not the
    # in-place aggregate. Returning the dict is fine because we only build it
    # once per execute call.
    return dict(aggregate)
