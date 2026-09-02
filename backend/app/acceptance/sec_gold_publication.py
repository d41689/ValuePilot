"""Locked FT-04 publication helpers for the SEC gold-set acceptance run.

The constants in this module deliberately do not have CLI counterparts.  The
acceptance runner may select a case and pass, but it cannot replace the
migration-owned mapping/method authorities, parser, or source precedence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.services.sec_metric_publication import (
    PublicationReceipt,
    PublicationRequest,
    VerifiedPublicationSource,
    finalize_sec_publication,
    publish_sec_mapping_result,
    resolve_latest_known_v1_sources,
)
from app.services.sec_financial_ingestion import (
    FinancialFilingSelection,
    FinancialIngestionReport,
    PARSER_V2,
)


ACCEPTANCE_MAPPING_VERSION_ID = "sec-us-gaap-v1"
ACCEPTANCE_METHOD_POLICY_VERSION_ID = "sec-method-gate-v1"
ACCEPTANCE_AMENDMENT_POLICY_ID = "latest-known-v1"
ACCEPTANCE_PARSER_VERSION = PARSER_V2
V1_METRIC_DENOMINATOR = 21


@dataclass(frozen=True)
class AcceptancePublicationExecution:
    receipt: PublicationReceipt
    requested_cutoff: datetime
    mapping_version_id: str
    method_policy_version_id: str
    amendment_policy_id: str
    sources: tuple[VerifiedPublicationSource, ...]
    normalizations_created: int


@dataclass
class AcceptanceCompletionClaimLease:
    """Nonblocking DB-session liveness for one case/pass completion owner."""

    run_id: str
    case_id: str
    acceptance_pass: int
    claim_id: int | None
    attempt_id: int | None
    generation: int | None
    _connection: Connection
    _engine: Engine
    _session: Session
    _closed: bool = False

    def release(self) -> None:
        if self._closed:
            return
        try:
            if self._session.in_transaction():
                self._session.rollback()
            self._connection.execute(
                text(
                    "SELECT set_config("
                    "'valuepilot.sec_acceptance_completion_owner_token','',false)"
                )
            )
            self._connection.execute(
                text(
                    "SELECT pg_advisory_unlock("
                    "sec_acceptance_completion_lock_namespace(),"
                    "sec_acceptance_completion_lock_local("
                    ":run,:case,CAST(:pass AS smallint)))"
                ),
                {
                    "run": self.run_id,
                    "case": self.case_id,
                    "pass": self.acceptance_pass,
                },
            )
            self._connection.commit()
        finally:
            self._session.bind = self._engine
            self._connection.close()
            self._closed = True

    def abandon_for_test(self) -> None:
        """Model a dead owner by terminating its physical DB connection."""

        if self._closed:
            return
        self._connection.invalidate()
        self._connection.close()
        self._session.bind = self._engine
        self._closed = True


def acquire_acceptance_completion_lease(
    db: Session,
    *,
    run_id: str,
    case_id: str,
    acceptance_pass: int,
    append_existing_claim: bool = True,
) -> AcceptanceCompletionClaimLease | None:
    """Bind a case/pass lease, optionally taking over its existing attempt."""

    bind = db.get_bind()
    engine = bind.engine if isinstance(bind, Connection) else bind
    connection = engine.connect()
    acquired = bool(
        connection.execute(
            text(
                "SELECT pg_try_advisory_lock("
                "sec_acceptance_completion_lock_namespace(),"
                "sec_acceptance_completion_lock_local("
                ":run,:case,CAST(:pass AS smallint)))"
            ),
            {"run": run_id, "case": case_id, "pass": acceptance_pass},
        ).scalar_one()
    )
    if not acquired:
        connection.close()
        return None
    row = connection.execute(
        text(
            """SELECT id,attempt_id,generation
               FROM sec_acceptance_case_completion_claims
               WHERE run_id=:run AND case_id=:case AND acceptance_pass=:pass
               ORDER BY generation DESC LIMIT 1"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).mappings().one_or_none()
    connection.commit()
    db.bind = connection
    lease = AcceptanceCompletionClaimLease(
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=acceptance_pass,
        claim_id=int(row.id) if row is not None else None,
        attempt_id=int(row.attempt_id) if row is not None else None,
        generation=int(row.generation) if row is not None else None,
        _connection=connection,
        _engine=engine,
        _session=db,
    )
    if row is not None and append_existing_claim:
        try:
            return append_acceptance_completion_claim(
                lease, attempt_id=int(row.attempt_id)
            )
        except BaseException:
            lease.release()
            raise
    return lease


def append_acceptance_completion_claim(
    lease: AcceptanceCompletionClaimLease, *, attempt_id: int
) -> AcceptanceCompletionClaimLease:
    """Append a crash-recoverable ownership generation under a held lease."""

    if lease._closed:
        raise ValueError("acceptance completion lease is closed")
    try:
        row = lease._connection.execute(
            text(
                """INSERT INTO sec_acceptance_case_completion_claims
                     (run_id,case_id,acceptance_pass,attempt_id,generation,
                      claimed_at,created_at,created_txid)
                   VALUES (:run,:case,:pass,:attempt,1,
                           clock_timestamp(),clock_timestamp(),txid_current())
                   RETURNING id,generation"""
            ),
            {
                "run": lease.run_id,
                "case": lease.case_id,
                "pass": lease.acceptance_pass,
                "attempt": attempt_id,
            },
        ).mappings().one()
        lease._connection.commit()
    except BaseException:
        lease._connection.rollback()
        raise
    lease.claim_id = int(row.id)
    lease.attempt_id = attempt_id
    lease.generation = int(row.generation)
    return lease


_PERSISTENT_DELTA_FIELDS = (
    "issuer_identities",
    "filings",
    "submission_snapshots",
    "artifacts",
    "parse_runs",
    "parse_run_artifacts",
    "raw_facts",
    "statement_report_references",
    "statement_occurrences",
    "statement_authorities",
    "numeric_normalizations",
    "publication_runs",
    "publication_run_sources",
    "publication_decisions",
    "publication_inputs",
    "publication_unresolved_inputs",
    "publication_audits",
    "publication_availabilities",
    "metric_facts",
)


def initialize_acceptance_case_attempt(
    lease: AcceptanceCompletionClaimLease,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically stamp a fresh attempt, its owner claim, and evidence baseline."""

    if lease._closed:
        raise ValueError("acceptance completion lease is closed")
    if lease.attempt_id is not None or lease.claim_id is not None:
        raise ValueError("acceptance completion lease already owns an attempt")
    connection = lease._connection
    try:
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "sec_acceptance_completion_lock_namespace(),"
                "sec_acceptance_completion_lock_local("
                ":run,:case,CAST(:pass AS smallint)))"
            ),
            {
                "run": lease.run_id,
                "case": lease.case_id,
                "pass": lease.acceptance_pass,
            },
        )
        attempt = connection.execute(
            text(
                """INSERT INTO sec_acceptance_case_attempts
                     (run_id,case_id,acceptance_pass,attempt_ordinal,
                      attempted_at,created_at,created_txid)
                   VALUES (:run,:case,:pass,1,
                           clock_timestamp(),clock_timestamp(),txid_current())
                   RETURNING id,attempt_ordinal,attempted_at,created_at,created_txid"""
            ),
            {
                "run": lease.run_id,
                "case": lease.case_id,
                "pass": lease.acceptance_pass,
            },
        ).mappings().one()
        claim = connection.execute(
            text(
                """INSERT INTO sec_acceptance_case_completion_claims
                     (run_id,case_id,acceptance_pass,attempt_id,generation,
                      claimed_at,created_at,created_txid)
                   VALUES (:run,:case,:pass,:attempt,1,
                           clock_timestamp(),clock_timestamp(),txid_current())
                   RETURNING id,generation,claimed_at,created_at,created_txid"""
            ),
            {
                "run": lease.run_id,
                "case": lease.case_id,
                "pass": lease.acceptance_pass,
                "attempt": attempt.id,
            },
        ).mappings().one()
        checkpoint = connection.execute(
            text(
                """INSERT INTO sec_acceptance_evidence_checkpoints
                     (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
                      evidence_counts,captured_at,created_at,created_txid)
                   VALUES (:run,:case,:pass,'before',:attempt,NULL,'{}'::jsonb,
                           clock_timestamp(),clock_timestamp(),txid_current())
                   RETURNING evidence_counts,captured_at,created_at,created_txid,
                             attempt_id,operation_id"""
            ),
            {
                "run": lease.run_id,
                "case": lease.case_id,
                "pass": lease.acceptance_pass,
                "attempt": attempt.id,
            },
        ).mappings().one()
        counts = dict(checkpoint.evidence_counts)
        if (
            int(attempt.created_txid) != int(claim.created_txid)
            or int(claim.created_txid) != int(checkpoint.created_txid)
            or attempt.created_at != attempt.attempted_at
            or claim.created_at != claim.claimed_at
            or checkpoint.created_at != checkpoint.captured_at
            or set(counts) != set(_PERSISTENT_DELTA_FIELDS)
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in counts.values()
            )
        ):
            raise ValueError("fresh acceptance completion authority mismatch")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    lease.claim_id = int(claim.id)
    lease.attempt_id = int(attempt.id)
    lease.generation = int(claim.generation)
    return (
        {
            "id": int(attempt.id),
            "attempt_ordinal": int(attempt.attempt_ordinal),
            "attempted_at": attempt.attempted_at,
            "created_txid": int(attempt.created_txid),
        },
        {
            "evidence_counts": {key: int(value) for key, value in counts.items()},
            "captured_at": checkpoint.captured_at,
            "operation_id": None,
            "attempt_id": int(attempt.id),
        },
    )


def publication_idempotency_delta(
    database_delta: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the complete pass-two evidence delta and its zero-delta verdict."""

    missing = [field for field in _PERSISTENT_DELTA_FIELDS if field not in database_delta]
    if missing:
        raise ValueError(
            "publication idempotency delta is incomplete: " + ",".join(missing)
        )
    values = {field: int(database_delta[field]) for field in _PERSISTENT_DELTA_FIELDS}
    if any(value < 0 for value in values.values()):
        raise ValueError("publication idempotency delta cannot be negative")
    return {
        **values,
        "idempotent": all(value == 0 for value in values.values()),
    }


def record_acceptance_evidence_checkpoint(
    db: Session,
    *,
    run_id: str,
    case_id: str,
    acceptance_pass: int,
    phase: str,
    attempt_id: int,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Insert or read one DB-computed append-only evidence checkpoint."""

    db.execute(
        text(
            """INSERT INTO sec_acceptance_evidence_checkpoints
                 (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
                  evidence_counts,captured_at,created_at,created_txid)
               VALUES (:run,:case,:pass,:phase,:attempt,:operation,'{}'::jsonb,
                       clock_timestamp(),clock_timestamp(),txid_current())
               ON CONFLICT (run_id,case_id,acceptance_pass,phase) DO NOTHING"""
        ),
        {
            "run": run_id,
            "case": case_id,
            "pass": acceptance_pass,
            "phase": phase,
            "attempt": attempt_id,
            "operation": operation_id,
        },
    )
    db.commit()
    row = db.execute(
        text(
            """SELECT run_id,case_id,acceptance_pass,phase,evidence_counts,
                      captured_at,created_at,created_txid,attempt_id,operation_id
               FROM sec_acceptance_evidence_checkpoints
               WHERE run_id=:run AND case_id=:case
                 AND acceptance_pass=:pass AND phase=:phase"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass, "phase": phase},
    ).mappings().one()
    counts = dict(row.evidence_counts)
    owner_attempt_id = db.execute(
        text(
            """SELECT attempt_id FROM sec_acceptance_case_completion_claims
               WHERE run_id=:run AND case_id=:case AND acceptance_pass=:pass
               ORDER BY generation DESC LIMIT 1"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).scalar_one_or_none()
    expected_operation_id = None if phase == "before" else operation_id
    if (
        row.run_id != run_id
        or row.case_id != case_id
        or int(row.acceptance_pass) != acceptance_pass
        or row.phase != phase
        or int(row.attempt_id) != int(attempt_id)
        or row.operation_id != expected_operation_id
        or owner_attempt_id is None
        or int(owner_attempt_id) != int(attempt_id)
        or row.captured_at != row.created_at
        or int(row.created_txid) <= 0
        or set(counts) != set(_PERSISTENT_DELTA_FIELDS)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        )
    ):
        raise ValueError("acceptance checkpoint existing authority mismatch")
    return {
        "evidence_counts": {key: int(value) for key, value in counts.items()},
        "captured_at": row.captured_at,
        "operation_id": str(row.operation_id) if row.operation_id is not None else None,
        "attempt_id": int(row.attempt_id),
    }


def begin_acceptance_case_attempt(
    db: Session,
    *,
    run_id: str,
    case_id: str,
    acceptance_pass: int,
) -> dict[str, Any]:
    """DB-stamp a new crash/resume attempt before any ingestion work."""

    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {
            "key": (
                "sec-acceptance-case-attempt:"
                f"{run_id}:{case_id}:{acceptance_pass}"
            )
        },
    )
    row = db.execute(
        text(
            """INSERT INTO sec_acceptance_case_attempts
                 (run_id,case_id,acceptance_pass,attempt_ordinal,
                  attempted_at,created_at,created_txid)
               VALUES (:run,:case,:pass,1,clock_timestamp(),clock_timestamp(),txid_current())
               RETURNING id,attempt_ordinal,attempted_at,created_txid"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).mappings().one()
    db.commit()
    return {
        "id": int(row.id),
        "attempt_ordinal": int(row.attempt_ordinal),
        "attempted_at": row.attempted_at,
        "created_txid": int(row.created_txid),
    }


def link_acceptance_operation(
    db: Session,
    *,
    attempt_id: int,
    operation_id: str,
    operation_ordinal: int,
    operation_role: str,
) -> int:
    """Link an operation in its creation transaction, or as verified recovery."""

    if operation_role in {"main", "continuation"}:
        terminal_kind = db.execute(
            text(
                "SELECT result_kind FROM sec_financial_operation_results "
                "WHERE operation_id=:operation"
            ),
            {"operation": operation_id},
        ).scalar_one_or_none()
        if terminal_kind in {
            "acquisition_failure",
            "history_continuation_failure",
        }:
            operation_role = "failed"
    return int(
        db.execute(
            text(
                """INSERT INTO sec_acceptance_operation_links
                     (attempt_id,operation_id,operation_ordinal,operation_role,
                      linked_at,created_at,created_txid)
                   VALUES (:attempt,:operation,:ordinal,:role,
                           clock_timestamp(),clock_timestamp(),txid_current())
                   RETURNING id"""
            ),
            {
                "attempt": attempt_id,
                "operation": operation_id,
                "ordinal": operation_ordinal,
                "role": operation_role,
            },
        ).scalar_one()
    )


def acceptance_operation_authority(
    db: Session, *, run_id: str, case_id: str, acceptance_pass: int
) -> dict[str, Any]:
    attempts = list(
        db.execute(
            text(
                """SELECT id,attempt_ordinal,attempted_at,created_txid
                   FROM sec_acceptance_case_attempts
                   WHERE run_id=:run AND case_id=:case AND acceptance_pass=:pass
                   ORDER BY attempt_ordinal"""
            ),
            {"run": run_id, "case": case_id, "pass": acceptance_pass},
        ).mappings()
    )
    links = list(
        db.execute(
            text(
                """SELECT link.id,link.attempt_id,attempt.attempt_ordinal,
                          link.operation_id,link.operation_ordinal,
                          link.operation_role,link.linked_at,link.created_txid
                   FROM sec_acceptance_operation_links link
                   JOIN sec_acceptance_case_attempts attempt ON attempt.id=link.attempt_id
                   WHERE attempt.run_id=:run AND attempt.case_id=:case
                     AND attempt.acceptance_pass=:pass
                   ORDER BY attempt.attempt_ordinal,link.operation_ordinal"""
            ),
            {"run": run_id, "case": case_id, "pass": acceptance_pass},
        ).mappings()
    )
    creation_links = [row for row in links if row.operation_role != "recovered"]
    return {
        "attempts": [dict(row) for row in attempts],
        "links": [dict(row) for row in links],
        "creation_operation_ids": [str(row.operation_id) for row in creation_links],
    }


def completed_acceptance_checkpoint(
    db: Session, *, run_id: str, case_id: str, acceptance_pass: int
) -> dict[str, Any] | None:
    """Return the durable completed case/pass identity without mutating it."""

    row = db.execute(
        text(
            """SELECT attempt_id,operation_id,captured_at,evidence_counts
               FROM sec_acceptance_evidence_checkpoints
               WHERE run_id=:run AND case_id=:case
                 AND acceptance_pass=:pass AND phase='after'"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).mappings().one_or_none()
    if row is None:
        return None
    return {
        "attempt_id": int(row.attempt_id),
        "operation_id": str(row.operation_id),
        "captured_at": row.captured_at,
        "evidence_counts": {
            str(key): int(value) for key, value in dict(row.evidence_counts).items()
        },
    }


def recoverable_bound_acceptance_attempt(
    db: Session, *, run_id: str, case_id: str, acceptance_pass: int
) -> dict[str, Any] | None:
    """Return the sole unfinished attempt whose publication is durably bound."""

    rows = list(db.execute(text(
        """SELECT attempt.id AS attempt_id,binding.publication_run_id,
                  binding.requested_cutoff,
                  (SELECT link.operation_id
                   FROM sec_acceptance_operation_links link
                   WHERE link.attempt_id=attempt.id
                     AND link.operation_role<>'recovered'
                   ORDER BY link.operation_ordinal DESC LIMIT 1) AS operation_id
           FROM sec_acceptance_case_attempts attempt
           JOIN sec_acceptance_publication_bindings binding
             ON binding.attempt_id=attempt.id
           WHERE attempt.run_id=:run AND attempt.case_id=:case
             AND attempt.acceptance_pass=:pass
             AND NOT EXISTS (
               SELECT 1 FROM sec_acceptance_evidence_checkpoints checkpoint
               WHERE checkpoint.run_id=attempt.run_id
                 AND checkpoint.case_id=attempt.case_id
                 AND checkpoint.acceptance_pass=attempt.acceptance_pass
                 AND checkpoint.phase='after')
           ORDER BY attempt.attempt_ordinal"""
    ), {"run": run_id, "case": case_id, "pass": acceptance_pass}).mappings())
    if not rows:
        return None
    if len(rows) != 1 or rows[0].operation_id is None:
        raise ValueError(
            "acceptance_recovery_authority_incomplete: unfinished publication attempt is ambiguous"
        )
    return {
        "attempt_id": int(rows[0].attempt_id),
        "operation_id": str(rows[0].operation_id),
        "publication_run_id": str(rows[0].publication_run_id),
        "requested_cutoff": rows[0].requested_cutoff,
    }


def recoverable_finalized_acceptance_acquisition(
    db: Session, *, run_id: str, case_id: str, acceptance_pass: int
) -> dict[str, Any] | None:
    """Return committed acquisition authority that has not reached publication."""

    rows = list(
        db.execute(
            text(
                """SELECT link.operation_id,operation.created_at AS operation_created_at,
                          attempt.attempt_ordinal,
                          link.operation_ordinal,result.result_kind,
                          available.available_at
                   FROM sec_acceptance_case_attempts attempt
                   JOIN sec_acceptance_operation_links link
                     ON link.attempt_id=attempt.id
                    AND link.operation_role<>'recovered'
                   JOIN sec_financial_ingestion_operations operation
                     ON operation.id=link.operation_id
                   LEFT JOIN sec_financial_operation_results result
                     ON result.operation_id=link.operation_id
                   LEFT JOIN sec_financial_lineage_availabilities available
                     ON available.operation_id=link.operation_id
                   WHERE attempt.run_id=:run AND attempt.case_id=:case
                     AND attempt.acceptance_pass=:pass
                   ORDER BY attempt.attempt_ordinal,link.operation_ordinal"""
            ),
            {"run": run_id, "case": case_id, "pass": acceptance_pass},
        ).mappings()
    )
    if not rows or any(
        row.result_kind is None or row.available_at is None for row in rows
    ):
        return None
    if db.execute(
        text(
            """SELECT count(*)
               FROM sec_acceptance_publication_bindings binding
               JOIN sec_acceptance_case_attempts attempt
                 ON attempt.id=binding.attempt_id
               WHERE attempt.run_id=:run AND attempt.case_id=:case
                 AND attempt.acceptance_pass=:pass"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).scalar_one():
        return None
    final_operation_id = str(rows[-1].operation_id)
    open_cursors = list(
        db.execute(
            text(
                """SELECT continuation.id
                   FROM sec_financial_history_continuations continuation
                   WHERE continuation.source_operation_id=:operation
                     AND NOT EXISTS (
                       SELECT 1 FROM sec_financial_history_consumption_claims claim
                       WHERE claim.parent_id=continuation.id)
                   ORDER BY continuation.created_at,continuation.id"""
            ),
            {"operation": final_operation_id},
        ).scalars()
    )
    if len(open_cursors) > 1:
        raise ValueError(
            "acceptance_recovery_authority_incomplete: multiple open history cursors"
        )
    current_parser_rows = list(
        db.execute(
            text(
                """SELECT parse.status,parse.fact_count
                   FROM sec_acceptance_case_attempts attempt
                   JOIN sec_acceptance_operation_links link
                     ON link.attempt_id=attempt.id
                    AND link.operation_role<>'recovered'
                   JOIN sec_financial_accession_attempts accession
                     ON accession.operation_id=link.operation_id
                   JOIN sec_financial_parse_runs parse
                     ON parse.id=accession.parse_run_id
                   WHERE attempt.run_id=:run AND attempt.case_id=:case
                     AND attempt.acceptance_pass=:pass
                     AND parse.parser_version=:parser"""
            ),
            {
                "run": run_id,
                "case": case_id,
                "pass": acceptance_pass,
                "parser": ACCEPTANCE_PARSER_VERSION,
            },
        ).mappings()
    )
    return {
        "operations": tuple(
            {
                "operation_id": str(row.operation_id),
                "available_at": row.available_at,
                "result_kind": str(row.result_kind),
            }
            for row in rows
        ),
        "next_history_cursor": str(open_cursors[0]) if open_cursors else None,
        "latest_operation_created_at": rows[-1].operation_created_at,
        "requires_reparse": not bool(current_parser_rows),
        "has_succeeded_parse": any(
            str(row.status) == "succeeded" and int(row.fact_count) > 0
            for row in current_parser_rows
        ),
    }


def load_completed_acceptance_publication(
    db: Session,
    *,
    attempt_id: int,
    stock_id: int,
    issuer_identity_id: int,
    acceptance_pass: int,
    completed_at: datetime,
) -> AcceptancePublicationExecution:
    """Rebuild the attempt-bound finalized publication without global lookup."""

    authority = db.execute(
        text(
            """SELECT run.stock_id,run.issuer_identity_id,available.available_at
               FROM sec_acceptance_publication_bindings binding
               JOIN sec_metric_publication_runs run
                 ON run.id=binding.publication_run_id
               LEFT JOIN sec_metric_publication_availabilities available
                 ON available.publication_run_id=run.id
               WHERE binding.attempt_id=:attempt"""
        ),
        {"attempt": attempt_id},
    ).mappings().one_or_none()
    if (
        authority is None
        or int(authority.stock_id) != stock_id
        or int(authority.issuer_identity_id) != issuer_identity_id
        or authority.available_at is None
        or authority.available_at > completed_at
    ):
        raise ValueError(
            "acceptance_recovery_authority_incomplete: attempt publication binding is incomplete"
        )
    publication = _bound_acceptance_publication(
        db,
        attempt_id=attempt_id,
        acceptance_pass=acceptance_pass,
        stock_id=stock_id,
        issuer_identity_id=issuer_identity_id,
    )
    if publication is None or not publication.receipt.available or not publication.sources:
        raise ValueError(
            "acceptance_recovery_authority_incomplete: bound publication lineage is incomplete"
        )
    return publication


def _bound_acceptance_publication(
    db: Session,
    *,
    attempt_id: int,
    acceptance_pass: int,
    stock_id: int,
    issuer_identity_id: int,
) -> AcceptancePublicationExecution | None:
    row = db.execute(
        text(
            """SELECT binding.publication_run_id,binding.requested_cutoff,
                      binding.mapping_version_id,binding.amendment_policy,
                      run.stock_id,run.issuer_identity_id,
                      attempt.acceptance_pass AS bound_acceptance_pass,
                      available.publication_run_id IS NOT NULL AS available
               FROM sec_acceptance_publication_bindings binding
               JOIN sec_acceptance_case_attempts attempt ON attempt.id=binding.attempt_id
               JOIN sec_metric_publication_runs run ON run.id=binding.publication_run_id
               LEFT JOIN sec_metric_publication_availabilities available
                 ON available.publication_run_id=binding.publication_run_id
               WHERE binding.attempt_id=:attempt"""
        ),
        {"attempt": attempt_id},
    ).mappings().one_or_none()
    if row is None:
        return None
    if (
        int(row.stock_id) != stock_id
        or int(row.issuer_identity_id) != issuer_identity_id
        or int(row.bound_acceptance_pass) != acceptance_pass
    ):
        raise ValueError("bound publication differs from attempt request identity")
    sources = tuple(
        VerifiedPublicationSource(
            int(item.parse_run_id), int(item.filing_id), str(item.accession_no),
            str(item.parser_version), str(item.input_manifest_hash), item.source_available_at,
        )
        for item in db.execute(
            text(
                """SELECT parse_run_id,filing_id,accession_no,parser_version,
                          input_manifest_hash,source_available_at
                   FROM sec_metric_publication_run_sources
                   WHERE publication_run_id=:run ORDER BY source_ordinal"""
            ), {"run": str(row.publication_run_id)}
        ).mappings()
    )
    facts = tuple(int(value) for value in db.execute(text(
        "SELECT metric_fact_id FROM sec_metric_publications WHERE publication_run_id=:run "
        "AND metric_fact_id IS NOT NULL ORDER BY decision_ordinal"
    ), {"run": str(row.publication_run_id)}).scalars())
    return AcceptancePublicationExecution(
        PublicationReceipt(str(row.publication_run_id), acceptance_pass == 2,
                           bool(row.available), facts),
        row.requested_cutoff, str(row.mapping_version_id),
        ACCEPTANCE_METHOD_POLICY_VERSION_ID, str(row.amendment_policy), sources, 0,
    )


def linked_acceptance_ingestion_reports(
    db: Session,
    *,
    run_id: str,
    case_id: str,
    acceptance_pass: int,
    current_reports: Sequence[FinancialIngestionReport],
) -> tuple[FinancialIngestionReport, ...]:
    """Rebuild prior crash attempts and retain exact current failure dispositions."""

    current = {report.operation_id: report for report in current_reports}
    authority = acceptance_operation_authority(
        db, run_id=run_id, case_id=case_id, acceptance_pass=acceptance_pass
    )
    reports: list[FinancialIngestionReport] = []
    for operation_id in authority["creation_operation_ids"]:
        if operation_id in current:
            reports.append(current[operation_id])
            continue
        row = db.execute(
            text(
                """SELECT identity.stock_id,identity.cik,
                  (SELECT count(*) FROM sec_financial_accession_attempts a
                    WHERE a.operation_id=operation.id) AS discovered,
                  (SELECT count(DISTINCT filing.id) FROM sec_financial_filings filing
                    JOIN sec_financial_accession_attempts a ON a.filing_id=filing.id
                    WHERE a.operation_id=operation.id
                      AND filing.xmin::text::bigint=operation.created_txid) AS filings_created,
                  (SELECT count(DISTINCT artifact.id) FROM sec_filing_artifacts artifact
                    JOIN sec_financial_accession_attempts a ON a.filing_id=artifact.filing_id
                    WHERE a.operation_id=operation.id
                      AND artifact.xmin::text::bigint=operation.created_txid) AS artifacts_created,
                  (SELECT count(*) FROM sec_financial_parse_runs parse
                    WHERE parse.operation_id=operation.id) AS parse_runs_created,
                  (SELECT count(*) FROM sec_raw_xbrl_facts raw
                    JOIN sec_financial_parse_runs parse ON parse.id=raw.parse_run_id
                    WHERE parse.operation_id=operation.id) AS raw_facts_created
                 FROM sec_financial_ingestion_operations operation
                 JOIN sec_issuer_identities identity
                   ON identity.id=operation.issuer_identity_id
                 WHERE operation.id=:operation"""
            ),
            {"operation": operation_id},
        ).mappings().one()
        selections = tuple(
            FinancialFilingSelection(
                accession_no=str(item.accession_no),
                form_type=str(item.form_type),
                accepted_at=item.accepted_at,
                report_date=item.report_date,
            )
            for item in db.execute(
                text(
                    """SELECT a.accession_no,filing.form_type,
                              filing.accepted_at,filing.report_date
                       FROM sec_financial_accession_attempts a
                       JOIN sec_financial_filings filing ON filing.id=a.filing_id
                       WHERE a.operation_id=:operation
                       ORDER BY filing.accepted_at DESC,a.accession_no DESC"""
                ),
                {"operation": operation_id},
            ).mappings()
        )
        failures = tuple(
            str(value)
            for value in db.execute(
                text(
                    """SELECT error_code AS value FROM sec_financial_acquisition_failures
                         WHERE operation_id=:operation
                       UNION
                       SELECT reason_code AS value FROM sec_financial_history_continuation_failures
                         WHERE operation_id=:operation
                       UNION
                       SELECT error_code AS value FROM sec_financial_parse_runs
                         WHERE operation_id=:operation AND error_code IS NOT NULL
                       ORDER BY value"""
                ),
                {"operation": operation_id},
            ).scalars()
        )
        reports.append(
            FinancialIngestionReport(
                operation_id=operation_id,
                stock_id=int(row.stock_id),
                cik=str(row.cik),
                filings_discovered=int(row.discovered),
                filings_created=int(row.filings_created),
                artifacts_created=int(row.artifacts_created),
                parse_runs_created=int(row.parse_runs_created),
                raw_facts_created=int(row.raw_facts_created),
                failures=failures,
                selected_filings=selections,
            )
        )
    if not reports:
        raise ValueError("acceptance attempt authority has no created operations")
    return tuple(reports)


def mark_acceptance_report_ready(
    db: Session,
    *,
    run_id: str,
    case_id: str,
    acceptance_pass: int,
    attempt_id: int,
    operation_id: str,
    report_sha256: str,
) -> dict[str, Any]:
    existing = load_acceptance_report_readiness(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=acceptance_pass,
    )
    if existing is not None:
        validate_acceptance_report_readiness_replay(
            existing,
            attempt_id=attempt_id,
            operation_id=operation_id,
            report_sha256=report_sha256,
        )
        return existing
    db.execute(
        text(
            """INSERT INTO sec_acceptance_report_readiness
                 (run_id,case_id,acceptance_pass,attempt_id,operation_id,
                  report_sha256,report_ready_at,created_at,created_txid)
               VALUES (:run,:case,:pass,:attempt,:operation,:digest,
                       clock_timestamp(),clock_timestamp(),txid_current())
               ON CONFLICT (run_id,case_id,acceptance_pass) DO NOTHING"""
        ),
        {
            "run": run_id,
            "case": case_id,
            "pass": acceptance_pass,
            "attempt": attempt_id,
            "operation": operation_id,
            "digest": report_sha256,
        },
    )
    db.commit()
    row = db.execute(
        text(
            """SELECT attempt_id,operation_id,report_sha256,report_ready_at
               FROM sec_acceptance_report_readiness
               WHERE run_id=:run AND case_id=:case AND acceptance_pass=:pass"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).mappings().one()
    result = {
        "attempt_id": int(row.attempt_id),
        "operation_id": str(row.operation_id),
        "report_sha256": str(row.report_sha256).strip(),
        "report_ready_at": row.report_ready_at,
    }
    validate_acceptance_report_readiness_replay(
        result,
        attempt_id=attempt_id,
        operation_id=operation_id,
        report_sha256=report_sha256,
    )
    return result


def load_acceptance_report_readiness(
    db: Session,
    *,
    run_id: str,
    case_id: str,
    acceptance_pass: int,
) -> dict[str, Any] | None:
    """Read existing report readiness without attempting an owner-guarded write."""

    row = db.execute(
        text(
            """SELECT attempt_id,operation_id,report_sha256,report_ready_at
               FROM sec_acceptance_report_readiness
               WHERE run_id=:run AND case_id=:case AND acceptance_pass=:pass"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).mappings().one_or_none()
    if row is None:
        return None
    return {
        "attempt_id": int(row.attempt_id),
        "operation_id": str(row.operation_id),
        "report_sha256": str(row.report_sha256).strip(),
        "report_ready_at": row.report_ready_at,
    }


def validate_acceptance_report_readiness_replay(
    readiness: Mapping[str, Any],
    *,
    attempt_id: int,
    operation_id: str,
    report_sha256: str,
) -> None:
    if (
        int(readiness["attempt_id"]) != attempt_id
        or str(readiness["operation_id"]) != operation_id
        or str(readiness["report_sha256"]).strip() != report_sha256
    ):
        raise ValueError("acceptance report readiness exact replay mismatch")


def load_acceptance_evidence_delta(
    db: Session, *, run_id: str, case_id: str, acceptance_pass: int
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """SELECT checkpoint.run_id,checkpoint.case_id,
                      checkpoint.acceptance_pass,checkpoint.phase,
                      checkpoint.evidence_counts,checkpoint.attempt_id,
                      checkpoint.operation_id,owner.attempt_id AS owner_attempt_id
               FROM sec_acceptance_evidence_checkpoints checkpoint
               LEFT JOIN LATERAL (
                 SELECT claim.attempt_id
                 FROM sec_acceptance_case_completion_claims claim
                 WHERE claim.run_id=checkpoint.run_id
                   AND claim.case_id=checkpoint.case_id
                   AND claim.acceptance_pass=checkpoint.acceptance_pass
                 ORDER BY claim.generation DESC LIMIT 1
               ) owner ON true
               WHERE checkpoint.run_id=:run AND checkpoint.case_id=:case
                 AND checkpoint.acceptance_pass=:pass"""
        ),
        {"run": run_id, "case": case_id, "pass": acceptance_pass},
    ).mappings().all()
    by_phase = {str(row.phase): row for row in rows}
    if set(by_phase) != {"before", "after"}:
        raise ValueError("acceptance evidence checkpoint pair is incomplete")
    before = by_phase["before"]
    after = by_phase["after"]
    if (
        before.run_id != run_id
        or after.run_id != run_id
        or before.case_id != case_id
        or after.case_id != case_id
        or int(before.acceptance_pass) != acceptance_pass
        or int(after.acceptance_pass) != acceptance_pass
        or before.owner_attempt_id is None
        or after.owner_attempt_id is None
        or int(before.owner_attempt_id) != int(after.owner_attempt_id)
        or int(before.attempt_id) != int(after.attempt_id)
        or int(before.attempt_id) != int(before.owner_attempt_id)
        or before.operation_id is not None
        or after.operation_id is None
    ):
        raise ValueError("acceptance evidence checkpoint owner authority mismatch")
    return persistent_evidence_delta(
        dict(before.evidence_counts), dict(after.evidence_counts)
    )


def persistent_evidence_delta(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    delta = {
        field: int(after[field]) - int(before[field])
        for field in _PERSISTENT_DELTA_FIELDS
    }
    return publication_idempotency_delta(delta)


def build_metric_outcome_matrix(
    *,
    expected_fiscal_years: Sequence[int],
    metric_keys: Sequence[str],
    decisions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Account for every locked issuer/year/metric without treating gaps as coverage."""

    years = tuple(int(year) for year in expected_fiscal_years)
    metrics = tuple(str(metric) for metric in metric_keys)
    if len(metrics) != len(set(metrics)) or not metrics:
        raise ValueError("canonical metric denominator requires distinct metric keys")
    grouped: dict[tuple[int, str], list[Mapping[str, Any]]] = {}
    for decision in decisions:
        if decision.get("period_type") != "FY":
            continue
        key = (int(decision["fiscal_year"]), str(decision["metric_key"]))
        if key[0] in years and key[1] in metrics:
            grouped.setdefault(key, []).append(decision)

    outcomes: list[dict[str, Any]] = []
    published_count = typed_gap_count = missing_count = 0
    for year in years:
        for metric_key in metrics:
            rows = sorted(grouped.get((year, metric_key), ()), key=lambda row: int(row["id"]))
            published = [row for row in rows if row.get("status") == "published"]
            unresolved = [row for row in rows if row.get("status") != "published"]
            # A typed disposition remains visible even when another decision
            # for the same issuer/year/metric published. Counting that pair
            # as covered would hide an unresolved canonical slot.
            if unresolved:
                outcome = "typed_gap"
                typed_gap_count += 1
                reasons = sorted({str(row["reason_code"]) for row in unresolved})
            elif published:
                outcome = "published"
                published_count += 1
                reasons = []
            else:
                outcome = "missing"
                missing_count += 1
                reasons = ["missing_canonical_outcome"]
            outcomes.append(
                {
                    "fiscal_year": year,
                    "metric_key": metric_key,
                    "outcome": outcome,
                    "decision_ids": [int(row["id"]) for row in rows],
                    "metric_fact_ids": [
                        int(row["metric_fact_id"])
                        for row in published
                        if row.get("metric_fact_id") is not None
                    ],
                    "typed_reasons": reasons,
                }
            )
    denominator = len(years) * len(metrics)
    return {
        "metric_denominator": len(metrics),
        "issuer_year_metric_denominator": denominator,
        "published_count": published_count,
        "typed_gap_count": typed_gap_count,
        "missing_count": missing_count,
        "coverage_count": published_count,
        "outcomes": outcomes,
    }


def validate_migration_owned_acceptance_authorities(db: Session) -> tuple[str, ...]:
    """Load, rather than accept, the approved V1 authorities from migrations."""

    mapping = db.execute(
        text(
            """SELECT id,status,effective_from,known_at
               FROM sec_metric_mapping_versions WHERE id=:id"""
        ),
        {"id": ACCEPTANCE_MAPPING_VERSION_ID},
    ).mappings().one_or_none()
    method = db.execute(
        text(
            """SELECT id,status,effective_from,known_at
               FROM sec_method_policy_versions WHERE id=:id"""
        ),
        {"id": ACCEPTANCE_METHOD_POLICY_VERSION_ID},
    ).mappings().one_or_none()
    metric_keys = tuple(
        db.execute(
            text(
                """SELECT metric_key FROM sec_metric_mapping_rules
                   WHERE mapping_version_id=:id ORDER BY id"""
            ),
            {"id": ACCEPTANCE_MAPPING_VERSION_ID},
        ).scalars()
    )
    if (
        mapping is None
        or mapping.status != "approved"
        or method is None
        or method.status != "approved"
        or len(metric_keys) != V1_METRIC_DENOMINATOR
        or len(set(metric_keys)) != V1_METRIC_DENOMINATOR
    ):
        raise ValueError("migration-owned FT-04 acceptance authority is incomplete")
    return metric_keys


def select_ordered_authoritative_sources(
    db: Session,
    *,
    stock_id: int,
    issuer_identity_id: int,
    filing_selection_as_of: datetime,
    requested_cutoff: datetime,
) -> tuple[VerifiedPublicationSource, ...]:
    """Assert the locked selection boundary over production-owned authority."""

    if filing_selection_as_of.tzinfo is None or requested_cutoff.tzinfo is None:
        raise ValueError("acceptance cutoffs must be timezone-aware")
    if requested_cutoff < filing_selection_as_of:
        raise ValueError("publication cutoff cannot precede filing selection cutoff")
    sources = resolve_latest_known_v1_sources(
        db,
        stock_id=stock_id,
        issuer_identity_id=issuer_identity_id,
        requested_cutoff=requested_cutoff,
    )
    if not sources:
        raise ValueError("case has no finalized parser-v2 publication authority")
    eligible_count = int(
        db.execute(
            text(
                """SELECT count(*) FROM sec_financial_filings
                   WHERE issuer_identity_id=:issuer AND id=ANY(:filing_ids)
                     AND accepted_at<=:selection_cutoff"""
            ),
            {
                "issuer": issuer_identity_id,
                "filing_ids": [source.filing_id for source in sources],
                "selection_cutoff": filing_selection_as_of,
            },
        ).scalar_one()
    )
    if eligible_count != len(sources):
        raise ValueError(
            "production publication authority exceeds locked filing selection cutoff"
        )
    return sources


def ensure_database_numeric_normalizations(
    db: Session,
    *,
    sources: Sequence[VerifiedPublicationSource],
) -> int:
    """Ask PostgreSQL's migration-owned V1 function to normalize mapped raws."""

    parse_ids = [source.parse_run_id for source in sources]
    candidate_rows = db.execute(
        text(
            """SELECT DISTINCT raw.id AS raw_fact_id, rule.id AS mapping_rule_id
               FROM sec_raw_xbrl_facts raw
               JOIN sec_metric_mapping_version_namespaces ns
                 ON ns.mapping_version_id=:mapping
                AND ns.authority='us_gaap'
                AND ns.namespace_uri=raw.concept_namespace_uri
               JOIN sec_metric_mapping_rules rule
                 ON rule.mapping_version_id=ns.mapping_version_id
                AND rule.metadata_json->'ordered_concepts' ?
                    CASE WHEN strpos(raw.concept,':')>0
                         THEN split_part(raw.concept,':',2) ELSE raw.concept END
               JOIN sec_statement_fact_authorities authority
                 ON authority.raw_fact_id=raw.id AND authority.parse_run_id=raw.parse_run_id
               WHERE raw.parse_run_id=ANY(:parse_ids)
               ORDER BY raw.id,rule.id"""
        ),
        {"mapping": ACCEPTANCE_MAPPING_VERSION_ID, "parse_ids": parse_ids},
    ).mappings()
    created = 0
    for row in candidate_rows:
        try:
            with db.begin_nested():
                inserted = db.execute(
                    text(
                        """INSERT INTO sec_raw_numeric_normalizations
                             (raw_fact_id,mapping_rule_id,mapping_version_id,
                              normalization_version,normalized_value,
                              raw_semantic_sha256,transformation_identity)
                           SELECT raw.id,:rule,:mapping,'sec_numeric_v1',
                                  compute_sec_numeric_v1(raw),repeat('0',64),
                                  'database-computed'
                           FROM sec_raw_xbrl_facts raw WHERE raw.id=:raw
                           ON CONFLICT DO NOTHING RETURNING id"""
                    ),
                    {
                        "raw": int(row["raw_fact_id"]),
                        "rule": int(row["mapping_rule_id"]),
                        "mapping": ACCEPTANCE_MAPPING_VERSION_ID,
                    },
                ).scalar_one_or_none()
                created += int(inserted is not None)
        except DBAPIError:
            # The mapper retains the raw input and emits its approved typed
            # value disposition; unsupported lexical forms are not coerced.
            continue
    return created


def database_publication_cutoff(db: Session) -> datetime:
    cutoff = db.execute(text("SELECT clock_timestamp()" )).scalar_one()
    if cutoff.tzinfo is None:
        raise ValueError("database publication cutoff must be timezone-aware")
    return cutoff


def execute_acceptance_publication(
    db: Session,
    *,
    stock_id: int,
    issuer_identity_id: int,
    filing_selection_as_of: datetime,
    replay_cutoff: datetime | None = None,
    expected_run_id: str | None = None,
    attempt_id: int,
    acceptance_pass: int,
) -> AcceptancePublicationExecution:
    """Publish or exactly replay one case using only locked/database authority."""

    validate_migration_owned_acceptance_authorities(db)
    attempt_authority = db.execute(text(
        """SELECT attempt.acceptance_pass,
                  count(*) FILTER (WHERE issuer.id=:issuer AND issuer.stock_id=:stock) AS matched,
                  count(*) AS linked
           FROM sec_acceptance_case_attempts attempt
           LEFT JOIN sec_acceptance_operation_links link ON link.attempt_id=attempt.id
           LEFT JOIN sec_financial_ingestion_operations operation ON operation.id=link.operation_id
           LEFT JOIN sec_issuer_identities issuer ON issuer.id=operation.issuer_identity_id
           WHERE attempt.id=:attempt GROUP BY attempt.acceptance_pass"""
    ), {
        "attempt": attempt_id,
        "issuer": issuer_identity_id,
        "stock": stock_id,
    }).mappings().one_or_none()
    if (
        attempt_authority is None
        or int(attempt_authority.acceptance_pass) != acceptance_pass
        or int(attempt_authority.linked) == 0
        or int(attempt_authority.matched) != int(attempt_authority.linked)
    ):
        raise ValueError("acceptance publication attempt authority is incomplete")
    bound = _bound_acceptance_publication(
        db,
        attempt_id=attempt_id,
        acceptance_pass=acceptance_pass,
        stock_id=stock_id,
        issuer_identity_id=issuer_identity_id,
    )
    if bound is not None:
        if expected_run_id is not None and bound.receipt.run_id != expected_run_id:
            raise ValueError("bound publication is not the expected exact replay")
        if replay_cutoff is not None and bound.requested_cutoff != replay_cutoff:
            raise ValueError("bound publication cutoff differs from exact replay")
        if not bound.receipt.available:
            finalize_sec_publication(db, bound.receipt.run_id)
            db.commit()
            bound = _bound_acceptance_publication(
                db,
                attempt_id=attempt_id,
                acceptance_pass=acceptance_pass,
                stock_id=stock_id,
                issuer_identity_id=issuer_identity_id,
            )
        if bound is None or not bound.receipt.available:
            raise ValueError("bound publication could not be finalized")
        return bound
    source_cutoff = replay_cutoff or database_publication_cutoff(db)
    sources = select_ordered_authoritative_sources(
        db,
        stock_id=stock_id,
        issuer_identity_id=issuer_identity_id,
        filing_selection_as_of=filing_selection_as_of,
        requested_cutoff=source_cutoff,
    )
    normalizations_created = ensure_database_numeric_normalizations(db, sources=sources)
    if replay_cutoff is None:
        # Persist normalizations before fixing the knowledge boundary consumed
        # by the publication service.
        db.commit()
        requested_cutoff = database_publication_cutoff(db)
        sources = select_ordered_authoritative_sources(
            db,
            stock_id=stock_id,
            issuer_identity_id=issuer_identity_id,
            filing_selection_as_of=filing_selection_as_of,
            requested_cutoff=requested_cutoff,
        )
    else:
        if replay_cutoff.tzinfo is None:
            raise ValueError("replay publication cutoff must be timezone-aware")
        requested_cutoff = replay_cutoff
    request = PublicationRequest(
        stock_id=stock_id,
        issuer_identity_id=issuer_identity_id,
        mapping_version_id=ACCEPTANCE_MAPPING_VERSION_ID,
        requested_cutoff=requested_cutoff,
        amendment_policy=ACCEPTANCE_AMENDMENT_POLICY_ID,
        sources=sources,
    )
    receipt = publish_sec_mapping_result(db, request)
    if expected_run_id is not None and receipt.run_id != expected_run_id:
        raise ValueError("pass-two publication identity is not the exact pass-one replay")
    db.execute(
        text(
            """INSERT INTO sec_acceptance_publication_bindings
                 (attempt_id,requested_cutoff,source_set_sha256,
                  ordered_source_identities,mapping_version_id,amendment_policy,
                  expected_publication_run_id,publication_run_id,
                  bound_at,created_at,created_txid)
               SELECT :attempt,run.requested_cutoff,run.source_set_sha256,
                 (SELECT jsonb_agg(jsonb_build_object(
                   'parse_run_id',source.parse_run_id,'filing_id',source.filing_id,
                   'accession_no',source.accession_no,'parser_version',source.parser_version,
                   'input_manifest_hash',source.input_manifest_hash,
                   'available_at',source.source_available_at) ORDER BY source.source_ordinal)
                 FROM sec_metric_publication_run_sources source
                 WHERE source.publication_run_id=run.id),
                 run.mapping_version_id,run.amendment_policy,:expected,run.id,
                 clock_timestamp(),clock_timestamp(),txid_current()
               FROM sec_metric_publication_runs run WHERE run.id=:run"""
        ),
        {"attempt": attempt_id, "expected": expected_run_id, "run": receipt.run_id},
    )
    db.commit()
    finalized = finalize_sec_publication(db, receipt.run_id)
    db.commit()
    return AcceptancePublicationExecution(
        receipt=PublicationReceipt(
            run_id=receipt.run_id,
            replayed=receipt.replayed,
            available=finalized.available,
            fact_ids=receipt.fact_ids,
        ),
        requested_cutoff=requested_cutoff,
        mapping_version_id=ACCEPTANCE_MAPPING_VERSION_ID,
        method_policy_version_id=ACCEPTANCE_METHOD_POLICY_VERSION_ID,
        amendment_policy_id=ACCEPTANCE_AMENDMENT_POLICY_ID,
        sources=sources,
        normalizations_created=normalizations_created,
    )
