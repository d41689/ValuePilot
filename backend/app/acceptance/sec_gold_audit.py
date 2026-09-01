"""Integrity and idempotency helpers for the Step D SEC gold-set audit."""

from __future__ import annotations

import hashlib
import json
import errno
import os
import stat
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, literal_column, select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.models.sec_financials import (
    SecFilingArtifact,
    SecFinancialAccessionAttempt,
    SecFinancialAccessionAttemptArtifact,
    SecFinancialAcquisitionFailure,
    SecFinancialFiling,
    SecFinancialIngestionOperation,
    SecFinancialLineageAvailability,
    SecFinancialOperationResult,
    SecFinancialOperationSnapshot,
    SecFinancialParseRun,
    SecIssuerIdentity,
    SecRawXbrlFact,
    SecSubmissionSnapshot,
    SecStatementFactAuthority,
    SecStatementOccurrenceEvidence,
    SecStatementReportReference,
)
from app.models.sec_publication import (
    SecMetricPublication,
    SecMetricPublicationAudit,
    SecMetricPublicationAvailability,
    SecMetricPublicationInput,
    SecMetricPublicationRun,
    SecMetricPublicationRunSource,
    SecMetricPublicationUnresolvedInput,
    SecRawNumericNormalization,
)
from app.acceptance.sec_gold_publication import (
    ACCEPTANCE_AMENDMENT_POLICY_ID,
    ACCEPTANCE_MAPPING_VERSION_ID,
    ACCEPTANCE_METHOD_POLICY_VERSION_ID,
    build_metric_outcome_matrix,
    acceptance_operation_authority,
    load_acceptance_evidence_delta,
)
from app.acceptance.sec_gold_storage import (
    secure_atomic_write_bytes,
    secure_read_bytes,
    secure_read_json,
)
from app.models.stocks import Stock
from app.acceptance.financial_truth_gold_set import validate_gold_set
from app.services.sec_financial_ingestion import (
    FinancialHistoryTarget,
    _expected_completed_fiscal_years,
)


_IDEMPOTENCY_FIELDS = (
    "filings_created",
    "submission_snapshots_created",
    "artifacts_created",
    "parse_runs_created",
    "raw_facts_created",
)


def locked_case_contract(
    manifest: dict[str, Any], case: dict[str, Any]
) -> tuple[datetime, tuple[int, ...]]:
    """Rebuild the immutable selection/year contract from validated manifest data."""

    validate_gold_set(manifest)
    matches = [
        item for item in manifest["cases"] if item["case_id"] == case["case_id"]
    ]
    if len(matches) != 1 or matches[0] != case:
        raise ValueError("case is not the exact locked manifest member")
    cutoff = datetime.fromisoformat(
        str(manifest["cycle"]["cutoff_at"]).replace("Z", "+00:00")
    )
    if cutoff.tzinfo is None:
        raise ValueError("locked filing selection cutoff must be timezone-aware")
    target = FinancialHistoryTarget(
        filing_regime=str(case["filing_regime"]),
        fiscal_year_end_mmdd=str(case["fiscal_year_end_mmdd"]),
        available_start_on=date.fromisoformat(
            str(case["expected_history"]["available_start_on"])
        ),
        completed_fiscal_year_cap=int(
            case["expected_history"]["completed_fiscal_year_cap"]
        ),
        filing_selection_as_of=cutoff,
    )
    return cutoff, _expected_completed_fiscal_years(target)


def audit_retained_file(
    *,
    storage_root: Path,
    storage_key: str,
    expected_size: int,
    expected_sha256: str,
) -> dict[str, Any]:
    relative = PurePosixPath(storage_key)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ValueError("retained storage key must be a safe relative path")
    target = storage_root.joinpath(*relative.parts)
    content = secure_read_bytes(
        storage_root=storage_root,
        source=target,
        missing_ok=True,
    )
    if content is None:
        return {
            "actual_sha256": None,
            "actual_size": None,
            "exists": False,
            "integrity_ok": False,
            "sha256_ok": False,
            "size_ok": False,
        }
    actual_sha256 = hashlib.sha256(content).hexdigest()
    size_ok = len(content) == expected_size
    sha256_ok = actual_sha256 == expected_sha256
    return {
        "actual_sha256": actual_sha256,
        "actual_size": len(content),
        "exists": True,
        "integrity_ok": size_ok and sha256_ok,
        "sha256_ok": sha256_ok,
        "size_ok": size_ok,
    }


def build_idempotency_delta(
    database_created: dict[str, Any],
) -> dict[str, Any]:
    delta = {field: int(database_created[field]) for field in _IDEMPOTENCY_FIELDS}
    return {
        **dict(sorted(delta.items())),
        "idempotent": all(value == 0 for value in delta.values()),
    }


def validate_case_report_structure(
    payload: dict[str, Any],
    *,
    expected_run_id: str,
    expected_case_id: str,
    expected_pass: int,
) -> bool:
    identity = (
        payload.get("schema_version") == 2
        and payload.get("run_id") == expected_run_id
        and payload.get("case_id") == expected_case_id
        and payload.get("acceptance_pass") == expected_pass
        and isinstance(payload.get("operation_id"), str)
        and bool(payload.get("operation_id"))
    )
    if not identity:
        raise ValueError(f"acceptance report identity mismatch: {expected_case_id}")
    for field in ("typed_gaps", "typed_failures"):
        values = payload.get(field)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ValueError(
                f"acceptance report {field} is invalid: {expected_case_id}"
            )
    operations = payload.get("acquisition_operations")
    if (
        not isinstance(operations, list)
        or not operations
        or any(not isinstance(item, dict) for item in operations)
        or len({item.get("operation_id") for item in operations}) != len(operations)
        or operations[-1].get("operation_id") != payload.get("operation_id")
    ):
        raise ValueError(
            f"acceptance report acquisition operation identity is invalid: {expected_case_id}"
        )
    for operation in operations:
        if not isinstance(operation.get("operation_id"), str) or not operation[
            "operation_id"
        ]:
            raise ValueError(
                f"acceptance report acquisition operation identity is invalid: {expected_case_id}"
            )
        for field in ("attempted_at", "finalized_at", "available_at"):
            _report_datetime(operation, field, expected_case_id)
        accessions = operation.get("accessions")
        if not isinstance(accessions, list) or any(
            not isinstance(item, str) or not item for item in accessions
        ):
            raise ValueError(
                f"acceptance report acquisition accessions are invalid: {expected_case_id}"
            )
    required_publication_text = (
        "publication_run_id",
        "mapping_version_id",
        "method_policy_version_id",
        "amendment_policy_id",
    )
    if any(
        not isinstance(payload.get(field), str) or not payload[field]
        for field in required_publication_text
    ):
        raise ValueError(
            f"acceptance report publication identity is invalid: {expected_case_id}"
        )
    for field in (
        "publication_run_source_ids",
        "publication_source_parse_run_ids",
        "publication_source_accessions",
        "publication_decision_ids",
    ):
        values = payload.get(field)
        if not isinstance(values, list) or not values:
            raise ValueError(
                f"acceptance report publication lineage identity is invalid: {expected_case_id}"
            )
    if (
        not isinstance(payload.get("publication_replayed"), bool)
        or payload.get("publication_replayed") is not (expected_pass == 2)
    ):
        raise ValueError(
            f"acceptance report publication replay identity is invalid: {expected_case_id}"
        )
    for field in (
        "filing_selection_as_of",
        "operation_attempted_at",
        "evidence_finalized_at",
        "evidence_available_at",
        "publication_requested_cutoff",
        "publication_attempted_at",
        "publication_finalized_at",
        "publication_available_at",
    ):
        _report_datetime(payload, field, expected_case_id)
    metric = payload.get("metric_outcomes")
    expected_years = payload.get("expected_completed_fiscal_years")
    if (
        not isinstance(metric, dict)
        or metric.get("metric_denominator") != 21
        or not isinstance(expected_years, list)
        or metric.get("issuer_year_metric_denominator")
        != 21 * len(expected_years)
        or len(metric.get("outcomes", []))
        != metric.get("issuer_year_metric_denominator")
    ):
        raise ValueError(
            f"acceptance report metric denominator is invalid: {expected_case_id}"
        )
    persistent_delta = payload.get("persistent_delta")
    if not isinstance(persistent_delta, dict) or not isinstance(
        persistent_delta.get("idempotent"), bool
    ):
        raise ValueError(
            f"acceptance report persistent delta is invalid: {expected_case_id}"
        )
    return bool(
        payload["typed_gaps"]
        or payload["typed_failures"]
        or int(metric.get("typed_gap_count", 0))
        or int(metric.get("missing_count", 0))
        or (expected_pass == 2 and not persistent_delta["idempotent"])
    )


def _report_datetime(payload: dict[str, Any], field: str, case_id: str) -> datetime:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError(f"acceptance report {field} is invalid: {case_id}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"acceptance report {field} is invalid: {case_id}"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"acceptance report {field} is invalid: {case_id}")
    return parsed


def _case_database_identity(
    db: Session,
    *,
    case: dict[str, Any],
) -> tuple[SecIssuerIdentity, Stock]:
    cik = str(case["cik"])
    identity = db.scalar(
        select(SecIssuerIdentity)
        .where(SecIssuerIdentity.cik == cik)
        .order_by(SecIssuerIdentity.known_at.desc(), SecIssuerIdentity.id.desc())
        .limit(1)
    )
    if identity is None:
        raise ValueError(f"case has no retained SEC identity: {case['case_id']}")
    stock = db.get(Stock, identity.stock_id)
    if stock is None:
        raise ValueError(f"case SEC identity has no stock: {case['case_id']}")
    return identity, stock


def _schema_v2_acquisition_audit(
    db: Session,
    *,
    report: dict[str, Any],
    case_id: str,
    identity: SecIssuerIdentity,
) -> dict[str, Any]:
    audits: list[dict[str, Any]] = []
    totals = {field: 0 for field in _IDEMPOTENCY_FIELDS}
    total_discovered = 0
    selected_filings: dict[str, dict[str, Any]] = {}
    reported_operation_ids = [
        str(item["operation_id"]) for item in report["acquisition_operations"]
    ]
    authority = acceptance_operation_authority(
        db,
        run_id=str(report["run_id"]),
        case_id=case_id,
        acceptance_pass=int(report["acceptance_pass"]),
    )
    expected_operation_ids = authority["creation_operation_ids"]
    if not authority["attempts"] or not authority["links"]:
        raise ValueError(f"acceptance attempt/operation authority is incomplete: {case_id}")
    if reported_operation_ids != expected_operation_ids:
        raise ValueError(
            f"acceptance acquisition operation chain differs from database: {case_id}"
        )
    for reported in report["acquisition_operations"]:
        operation_id = str(reported["operation_id"])
        operation = db.get(SecFinancialIngestionOperation, operation_id)
        availability = db.get(SecFinancialLineageAvailability, operation_id)
        terminal = db.get(SecFinancialOperationResult, operation_id)
        if (
            operation is None
            or operation.issuer_identity_id != identity.id
            or availability is None
            or terminal is None
        ):
            raise ValueError(
                f"acceptance report operation is not finalized terminal lineage: {case_id}"
            )
        if _report_datetime(reported, "attempted_at", case_id) != operation.attempted_at:
            raise ValueError(f"acceptance report operation attempt mismatch: {case_id}")
        if any(
            _report_datetime(reported, field, case_id) != availability.available_at
            for field in ("finalized_at", "available_at")
        ):
            raise ValueError(f"acceptance report availability mismatch: {case_id}")
        attempts = list(
            db.execute(
                select(
                    SecFinancialAccessionAttempt.id,
                    SecFinancialAccessionAttempt.accession_no,
                    SecFinancialAccessionAttempt.filing_id,
                    SecFinancialFiling.form_type,
                    SecFinancialFiling.accepted_at,
                    SecFinancialFiling.report_date,
                )
                .outerjoin(
                    SecFinancialFiling,
                    SecFinancialFiling.id == SecFinancialAccessionAttempt.filing_id,
                )
                .where(SecFinancialAccessionAttempt.operation_id == operation_id)
                .order_by(
                    SecFinancialFiling.accepted_at.desc().nulls_last(),
                    SecFinancialAccessionAttempt.accession_no.desc(),
                )
            ).all()
        )
        total_discovered += len(attempts)
        if [str(item) for item in reported["accessions"]] != [
            str(item.accession_no) for item in attempts
        ]:
            raise ValueError(
                f"acceptance report selected filings do not match operation ownership: {case_id}"
            )
        if int(reported.get("filings_discovered", -1)) != len(attempts):
            raise ValueError(
                f"acceptance report discovered count does not match operation: {case_id}"
            )
        for item in attempts:
            if item.filing_id is None:
                continue
            selected_filings[str(item.accession_no)] = {
                "accession_no": str(item.accession_no),
                "form_type": str(item.form_type),
                "accepted_at": item.accepted_at.isoformat(),
                "report_date": (
                    item.report_date.isoformat() if item.report_date is not None else None
                ),
            }
        attempt_ids = [int(item.id) for item in attempts]
        counts = {
            "filings_created": int(
                db.scalar(
                    select(func.count(func.distinct(SecFinancialFiling.id)))
                    .select_from(SecFinancialFiling)
                    .join(
                        SecFinancialAccessionAttempt,
                        SecFinancialAccessionAttempt.filing_id == SecFinancialFiling.id,
                    )
                    .where(
                        SecFinancialAccessionAttempt.operation_id == operation_id,
                        literal_column("sec_financial_filings.xmin::text::bigint")
                        == operation.created_txid,
                    )
                )
                or 0
            ),
            "submission_snapshots_created": int(
                db.scalar(
                    select(func.count()).select_from(SecSubmissionSnapshot).where(
                        SecSubmissionSnapshot.operation_id == operation_id
                    )
                )
                or 0
            ),
            "artifacts_created": int(
                db.scalar(
                    select(func.count(func.distinct(SecFilingArtifact.id)))
                    .select_from(SecFilingArtifact)
                    .join(
                        SecFinancialAccessionAttempt,
                        SecFinancialAccessionAttempt.filing_id
                        == SecFilingArtifact.filing_id,
                    )
                    .where(
                        SecFinancialAccessionAttempt.operation_id == operation_id,
                        literal_column("sec_filing_artifacts.xmin::text::bigint")
                        == operation.created_txid,
                    )
                )
                or 0
            ),
            "parse_runs_created": int(
                db.scalar(
                    select(func.count()).select_from(SecFinancialParseRun).where(
                        SecFinancialParseRun.operation_id == operation_id
                    )
                )
                or 0
            ),
            "raw_facts_created": int(
                db.scalar(
                    select(func.count())
                    .select_from(SecRawXbrlFact)
                    .join(
                        SecFinancialParseRun,
                        SecFinancialParseRun.id == SecRawXbrlFact.parse_run_id,
                    )
                    .where(SecFinancialParseRun.operation_id == operation_id)
                )
                or 0
            ),
        }
        for field, value in counts.items():
            if int(reported.get(field, -1)) != value:
                raise ValueError(
                    f"acceptance report created counters do not match database-owned lineage: {case_id}"
                )
            totals[field] += value
        transaction_mismatches = {
            "accession_attempts": int(
                db.scalar(
                    select(func.count())
                    .select_from(SecFinancialAccessionAttempt)
                    .where(
                        SecFinancialAccessionAttempt.operation_id == operation_id,
                        SecFinancialAccessionAttempt.created_txid
                        != operation.created_txid,
                    )
                )
                or 0
            ),
            "attempt_artifact_links": int(
                db.scalar(
                    select(func.count())
                    .select_from(SecFinancialAccessionAttemptArtifact)
                    .where(
                        SecFinancialAccessionAttemptArtifact.attempt_id.in_(
                            attempt_ids or [-1]
                        ),
                        SecFinancialAccessionAttemptArtifact.created_txid
                        != operation.created_txid,
                    )
                )
                or 0
            ),
            "parse_runs": int(
                db.scalar(
                    select(func.count())
                    .select_from(SecFinancialParseRun)
                    .where(
                        SecFinancialParseRun.operation_id == operation_id,
                        SecFinancialParseRun.created_txid != operation.created_txid,
                    )
                )
                or 0
            ),
            "terminal_result": int(terminal.created_txid != operation.created_txid),
        }
        if any(transaction_mismatches.values()):
            raise ValueError(
                f"acceptance operation ownership transaction mismatch: {case_id}"
            )
        audits.append(
            {
                "operation_id": operation_id,
                "attempted_at": operation.attempted_at.isoformat(),
                "available_at": availability.available_at.isoformat(),
                "created_txid": operation.created_txid,
                "terminal_result_kind": terminal.result_kind,
                "database_created": counts,
                "ownership_transaction_mismatches": transaction_mismatches,
            }
        )
    top_level = {
        field: int(report[field])
        for field in _IDEMPOTENCY_FIELDS
    }
    if top_level != totals:
        raise ValueError(
            f"acceptance report aggregate created counters do not match operations: {case_id}"
        )
    if int(report.get("filings_discovered", -1)) != total_discovered:
        raise ValueError(
            f"acceptance report discovered count does not match database: {case_id}"
        )
    rebuilt_selected = list(selected_filings.values())
    if report.get("selected_filings") != rebuilt_selected:
        raise ValueError(
            f"acceptance report selected filing fields do not match database: {case_id}"
        )
    if report.get("selected_forms") != sorted(
        {item["form_type"] for item in rebuilt_selected}
    ):
        raise ValueError(
            f"acceptance report selected forms do not match database: {case_id}"
        )
    checkpoint_times = db.execute(
        text(
            """SELECT phase,captured_at FROM sec_acceptance_evidence_checkpoints
               WHERE run_id=:run AND case_id=:case AND acceptance_pass=:pass"""
        ),
        {
            "run": report["run_id"],
            "case": case_id,
            "pass": report["acceptance_pass"],
        },
    ).mappings().all()
    times = {str(row.phase): row.captured_at for row in checkpoint_times}
    if set(times) != {"before", "after"}:
        raise ValueError(f"acceptance evidence checkpoint window is incomplete: {case_id}")
    window_operations = {
        str(value)
        for value in db.execute(
            text(
                """SELECT id FROM sec_financial_ingestion_operations
                   WHERE issuer_identity_id=:identity
                     AND created_at>=:before AND created_at<=:after"""
            ),
            {
                "identity": identity.id,
                "before": times["before"],
                "after": times["after"],
            },
        ).scalars()
    }
    if window_operations != set(expected_operation_ids):
        raise ValueError(
            f"acceptance operation window contains unlinked or cross-case rows: {case_id}"
        )
    return {
        "operations": audits,
        "database_created": totals,
        "filings_discovered": total_discovered,
        "selected_filings": rebuilt_selected,
        "attempt_authority": authority,
    }


def _schema_v2_publication_audit(
    db: Session,
    *,
    report: dict[str, Any],
    case_id: str,
    stock: Stock,
    expected_attempt_id: int,
    expected_acceptance_pass: int,
    expected_completed_fiscal_years: tuple[int, ...],
) -> dict[str, Any]:
    run_id = str(report["publication_run_id"])
    run = db.get(SecMetricPublicationRun, run_id)
    availability = db.get(SecMetricPublicationAvailability, run_id)
    if (
        run is None
        or availability is None
        or run.status != "succeeded"
        or run.stock_id != stock.id
        or run.mapping_version_id != ACCEPTANCE_MAPPING_VERSION_ID
        or run.amendment_policy != ACCEPTANCE_AMENDMENT_POLICY_ID
        or report["mapping_version_id"] != ACCEPTANCE_MAPPING_VERSION_ID
        or report["method_policy_version_id"] != ACCEPTANCE_METHOD_POLICY_VERSION_ID
        or report["amendment_policy_id"] != ACCEPTANCE_AMENDMENT_POLICY_ID
    ):
        raise ValueError(f"acceptance publication authority mismatch: {case_id}")
    if _report_datetime(report, "publication_requested_cutoff", case_id) != run.requested_cutoff:
        raise ValueError(f"acceptance publication cutoff mismatch: {case_id}")
    if _report_datetime(report, "publication_attempted_at", case_id) != run.created_at:
        raise ValueError(f"acceptance publication attempt mismatch: {case_id}")
    for field in ("publication_finalized_at", "publication_available_at"):
        if _report_datetime(report, field, case_id) != availability.available_at:
            raise ValueError(f"acceptance publication availability mismatch: {case_id}")
    sources = list(
        db.scalars(
            select(SecMetricPublicationRunSource)
            .where(SecMetricPublicationRunSource.publication_run_id == run_id)
            .order_by(SecMetricPublicationRunSource.source_ordinal)
        )
    )
    if [item.accession_no for item in sources] != list(
        report["publication_source_accessions"]
    ) or [item.id for item in sources] != list(
        report.get("publication_run_source_ids", [])
    ) or [item.parse_run_id for item in sources] != list(
        report.get("publication_source_parse_run_ids", [])
    ):
        raise ValueError(f"acceptance publication source identity mismatch: {case_id}")
    if [item.source_ordinal for item in sources] != list(range(1, len(sources) + 1)):
        raise ValueError(f"acceptance publication source ordering mismatch: {case_id}")
    binding = db.execute(text(
        """SELECT binding.id,binding.requested_cutoff,binding.source_set_sha256,
                  binding.ordered_source_identities,binding.mapping_version_id,
                  binding.amendment_policy,binding.expected_publication_run_id,
                  binding.publication_run_id,attempt.acceptance_pass
           FROM sec_acceptance_publication_bindings binding
           JOIN sec_acceptance_case_attempts attempt ON attempt.id=binding.attempt_id
           WHERE binding.attempt_id=:attempt"""
    ), {"attempt": expected_attempt_id}).mappings().one_or_none()
    ordered_source_identities = [
        {
            "parse_run_id": item.parse_run_id,
            "filing_id": item.filing_id,
            "accession_no": item.accession_no,
            "parser_version": item.parser_version,
            "input_manifest_hash": item.input_manifest_hash,
            "available_at": item.source_available_at.isoformat(),
        }
        for item in sources
    ]
    if (
        binding is None
        or int(binding.acceptance_pass) != expected_acceptance_pass
        or str(binding.publication_run_id) != run_id
        or binding.requested_cutoff != run.requested_cutoff
        or str(binding.source_set_sha256) != run.source_set_sha256
        or binding.mapping_version_id != run.mapping_version_id
        or binding.amendment_policy != run.amendment_policy
        or list(binding.ordered_source_identities) != ordered_source_identities
        or (
            expected_acceptance_pass == 1
            and binding.expected_publication_run_id is not None
        )
        or (
            expected_acceptance_pass == 2
            and str(binding.expected_publication_run_id) != run_id
        )
    ):
        raise ValueError(f"acceptance attempt publication binding mismatch: {case_id}")
    decisions = list(
        db.execute(
            select(
                SecMetricPublication.id,
                SecMetricPublication.metric_key,
                SecMetricPublication.fiscal_year,
                SecMetricPublication.period_type,
                SecMetricPublication.status,
                SecMetricPublication.reason_code,
                SecMetricPublication.metric_fact_id,
            )
            .where(SecMetricPublication.publication_run_id == run_id)
            .order_by(SecMetricPublication.decision_ordinal)
        ).mappings()
    )
    if [int(item["id"]) for item in decisions] != list(
        report["publication_decision_ids"]
    ):
        raise ValueError(f"acceptance publication decision identity mismatch: {case_id}")
    decision_ids = [int(item["id"]) for item in decisions]
    parse_ids = [int(item.parse_run_id) for item in sources]
    durable_counts = {
        "raw_facts": int(
            db.scalar(
                select(func.count()).select_from(SecRawXbrlFact).where(
                    SecRawXbrlFact.parse_run_id.in_(parse_ids or [-1])
                )
            )
            or 0
        ),
        "statement_report_references": int(
            db.scalar(
                select(func.count()).select_from(SecStatementReportReference).where(
                    SecStatementReportReference.parse_run_id.in_(parse_ids or [-1])
                )
            )
            or 0
        ),
        "statement_occurrences": int(
            db.scalar(
                select(func.count()).select_from(SecStatementOccurrenceEvidence).where(
                    SecStatementOccurrenceEvidence.parse_run_id.in_(parse_ids or [-1])
                )
            )
            or 0
        ),
        "statement_authorities": int(
            db.scalar(
                select(func.count()).select_from(SecStatementFactAuthority).where(
                    SecStatementFactAuthority.parse_run_id.in_(parse_ids or [-1])
                )
            )
            or 0
        ),
        "numeric_normalizations": int(
            db.execute(
                text(
                    """SELECT count(*) FROM sec_raw_numeric_normalizations n
                       JOIN sec_raw_xbrl_facts raw ON raw.id=n.raw_fact_id
                       WHERE raw.parse_run_id=ANY(:ids)
                         AND n.mapping_version_id=:mapping"""
                ),
                {"ids": parse_ids, "mapping": ACCEPTANCE_MAPPING_VERSION_ID},
            ).scalar_one()
        ),
        "publication_runs": 1,
        "publication_sources": len(sources),
        "publication_decisions": len(decisions),
        "publication_inputs": int(
            db.scalar(
                select(func.count()).select_from(SecMetricPublicationInput).where(
                    SecMetricPublicationInput.publication_id.in_(decision_ids or [-1])
                )
            )
            or 0
        ),
        "publication_unresolved_inputs": int(
            db.scalar(
                select(func.count())
                .select_from(SecMetricPublicationUnresolvedInput)
                .where(
                    SecMetricPublicationUnresolvedInput.publication_id.in_(
                        decision_ids or [-1]
                    )
                )
            )
            or 0
        ),
        "published_decisions": sum(item["status"] == "published" for item in decisions),
        "unresolved_decisions": sum(item["status"] == "unresolved" for item in decisions),
        "publication_audits": int(
            db.scalar(
                select(func.count()).select_from(SecMetricPublicationAudit).where(
                    SecMetricPublicationAudit.publication_run_id == run_id
                )
            )
            or 0
        ),
        "publication_availabilities": 1,
        "metric_facts": int(
            db.scalar(
                select(func.count()).select_from(MetricFact).where(
                    MetricFact.stock_id == stock.id,
                    MetricFact.source_type == "sec",
                )
            )
            or 0
        ),
    }
    if durable_counts != report["lineage_counts"]:
        raise ValueError(f"acceptance publication lineage count mismatch: {case_id}")
    if (
        run.published_count != durable_counts["published_decisions"]
        or run.unresolved_count != durable_counts["unresolved_decisions"]
        or run.rejected_count != durable_counts["publication_audits"]
    ):
        raise ValueError(f"acceptance publication terminal counts mismatch: {case_id}")
    metric_keys = tuple(
        db.execute(
            text(
                """SELECT metric_key FROM sec_metric_mapping_rules
                   WHERE mapping_version_id=:mapping ORDER BY id"""
            ),
            {"mapping": ACCEPTANCE_MAPPING_VERSION_ID},
        ).scalars()
    )
    rebuilt = build_metric_outcome_matrix(
        expected_fiscal_years=expected_completed_fiscal_years,
        metric_keys=metric_keys,
        decisions=decisions,
    )
    if rebuilt != report["metric_outcomes"]:
        raise ValueError(f"acceptance metric outcomes do not match database: {case_id}")
    integrity = db.execute(
        text(
            """SELECT
              count(*) FILTER (WHERE f.source_type='sec' AND
                (f.user_id IS NOT NULL OR f.source_document_id IS NOT NULL OR
                 f.source_ref_id IS NULL OR p.id IS NULL OR
                 p.metric_fact_id IS DISTINCT FROM f.id)) AS bad_sec,
              count(*) FILTER (WHERE f.source_type<>'sec' OR f.user_id IS NOT NULL) AS non_sec,
              count(*) FILTER (WHERE f.source_type='sec' AND p.status<>'published')
                AS bad_reciprocal
            FROM metric_facts f
            LEFT JOIN sec_metric_publications p ON p.id=f.source_ref_id"""
        )
    ).mappings().one()
    if any(int(value) for value in integrity.values()):
        raise ValueError(f"acceptance metric fact ownership/provenance violation: {case_id}")
    incomplete_decisions = int(
        db.execute(
            text(
                """SELECT count(*) FROM sec_metric_publications p
                   WHERE p.publication_run_id=:run AND (
                     (p.status='published' AND p.metric_fact_id IS NULL) OR
                     (p.status='published' AND p.derivation_kind='direct' AND
                       (SELECT count(*) FROM sec_metric_publication_inputs i
                        WHERE i.publication_id=p.id)<>1) OR
                     (p.status='published' AND p.derivation_kind<>'direct' AND
                       (SELECT count(*) FROM sec_metric_publication_inputs i
                        WHERE i.publication_id=p.id)<>2) OR
                     (p.status<>'published' AND p.metric_fact_id IS NOT NULL)
                   )"""
            ),
            {"run": run_id},
        ).scalar_one()
    )
    if incomplete_decisions:
        raise ValueError(f"acceptance publication input/decision completeness violation: {case_id}")
    duplicate_current_slots = int(
        db.execute(
            text(
                """SELECT coalesce(sum(count_value-1),0) FROM (
                     SELECT count(*) AS count_value FROM metric_facts
                     WHERE source_type='sec' AND is_current
                     GROUP BY stock_id,metric_key,period_type,period_end_date
                     HAVING count(*)>1
                   ) duplicates"""
            )
        ).scalar_one()
    )
    if duplicate_current_slots:
        raise ValueError(f"acceptance SEC current slot duplicates: {case_id}")
    return {
        "publication_binding_id": int(binding.id),
        "publication_run_id": run_id,
        "source_ids": [item.id for item in sources],
        "decision_ids": [int(item["id"]) for item in decisions],
        "durable_counts": durable_counts,
        "metric_outcomes": rebuilt,
        "current_slot_duplicates": duplicate_current_slots,
    }


def _operation_database_audit(
    db: Session,
    *,
    report: dict[str, Any],
    acceptance_pass: int,
    expected_run_id: str,
    case_id: str,
    identity: SecIssuerIdentity,
    stock: Stock,
) -> dict[str, Any]:
    validate_case_report_structure(
        report,
        expected_run_id=expected_run_id,
        expected_case_id=case_id,
        expected_pass=acceptance_pass,
    )
    if str(report.get("cik")) != identity.cik or int(
        report.get("stock_id", -1)
    ) != stock.id:
        raise ValueError(
            f"acceptance report issuer identity mismatch: {case_id} pass {acceptance_pass}"
        )
    operation_id = str(report["operation_id"])
    operation = db.get(SecFinancialIngestionOperation, operation_id)
    availability = db.get(SecFinancialLineageAvailability, operation_id)
    terminal = db.get(SecFinancialOperationResult, operation_id)
    if (
        operation is None
        or operation.issuer_identity_id != identity.id
        or availability is None
        or terminal is None
    ):
        raise ValueError(
            f"acceptance report operation is not finalized terminal lineage: "
            f"{case_id} pass {acceptance_pass}"
        )
    if _report_datetime(report, "operation_attempted_at", case_id) != operation.attempted_at:
        raise ValueError(
            f"acceptance report operation attempt mismatch: {case_id} pass {acceptance_pass}"
        )
    for field in ("evidence_finalized_at", "evidence_available_at"):
        if _report_datetime(report, field, case_id) != availability.available_at:
            raise ValueError(
                f"acceptance report availability mismatch: {case_id} pass {acceptance_pass}"
            )

    attempt_accessions = list(
        db.scalars(
            select(SecFinancialAccessionAttempt.accession_no).where(
                SecFinancialAccessionAttempt.operation_id == operation_id
            )
        ).all()
    )
    selected_filings = report.get("selected_filings")
    if not isinstance(selected_filings, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("accession_no"), str)
        for item in selected_filings
    ):
        raise ValueError(
            f"acceptance report selected filings are invalid: {case_id} pass {acceptance_pass}"
        )
    reported_accessions = [str(item["accession_no"]) for item in selected_filings]
    try:
        filings_discovered = int(report["filings_discovered"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"acceptance report discovered count is invalid: {case_id} pass {acceptance_pass}"
        ) from exc
    if (
        filings_discovered != len(attempt_accessions)
        or len(reported_accessions) != len(set(reported_accessions))
        or sorted(reported_accessions) != sorted(attempt_accessions)
    ):
        raise ValueError(
            f"acceptance report selected filings do not match operation ownership: "
            f"{case_id} pass {acceptance_pass}"
        )

    attempt_ids = select(SecFinancialAccessionAttempt.id).where(
        SecFinancialAccessionAttempt.operation_id == operation_id
    )
    database_created = {
        "filings_created": int(
            db.scalar(
                select(func.count(func.distinct(SecFinancialFiling.id)))
                .select_from(SecFinancialFiling)
                .join(
                    SecFinancialAccessionAttempt,
                    SecFinancialAccessionAttempt.filing_id == SecFinancialFiling.id,
                )
                .where(
                    SecFinancialAccessionAttempt.operation_id == operation_id,
                    literal_column(
                        "sec_financial_filings.xmin::text::bigint"
                    )
                    == operation.created_txid,
                )
            )
            or 0
        ),
        "submission_snapshots_created": int(
            db.scalar(
                select(func.count())
                .select_from(SecSubmissionSnapshot)
                .where(SecSubmissionSnapshot.operation_id == operation_id)
            )
            or 0
        ),
        "artifacts_created": int(
            db.scalar(
                select(func.count(func.distinct(SecFilingArtifact.id)))
                .select_from(SecFilingArtifact)
                .join(
                    SecFinancialAccessionAttempt,
                    SecFinancialAccessionAttempt.filing_id
                    == SecFilingArtifact.filing_id,
                )
                .where(
                    SecFinancialAccessionAttempt.operation_id == operation_id,
                    literal_column(
                        "sec_filing_artifacts.xmin::text::bigint"
                    )
                    == operation.created_txid,
                )
            )
            or 0
        ),
        "parse_runs_created": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialParseRun)
                .where(SecFinancialParseRun.operation_id == operation_id)
            )
            or 0
        ),
        "raw_facts_created": int(
            db.scalar(
                select(func.count())
                .select_from(SecRawXbrlFact)
                .join(
                    SecFinancialParseRun,
                    SecFinancialParseRun.id == SecRawXbrlFact.parse_run_id,
                )
                .where(SecFinancialParseRun.operation_id == operation_id)
            )
            or 0
        ),
    }
    reported_created: dict[str, int] = {}
    for field in _IDEMPOTENCY_FIELDS:
        if field not in report:
            raise ValueError(
                f"acceptance report created counters missing: {case_id} pass {acceptance_pass}"
            )
        try:
            value = int(report[field])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"acceptance report created counters invalid: {case_id} pass {acceptance_pass}"
            ) from exc
        if value < 0:
            raise ValueError(
                f"acceptance report created counters invalid: {case_id} pass {acceptance_pass}"
            )
        reported_created[field] = value
    if reported_created != database_created:
        raise ValueError(
            f"acceptance report created counters do not match database-owned lineage: "
            f"{case_id} pass {acceptance_pass}; reported={reported_created} "
            f"database={database_created}"
        )

    ownership = {
        "accession_attempts": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialAccessionAttempt)
                .where(SecFinancialAccessionAttempt.operation_id == operation_id)
            )
            or 0
        ),
        "operation_snapshot_links": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialOperationSnapshot)
                .where(SecFinancialOperationSnapshot.operation_id == operation_id)
            )
            or 0
        ),
        "attempt_artifact_links": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialAccessionAttemptArtifact)
                .where(SecFinancialAccessionAttemptArtifact.attempt_id.in_(attempt_ids))
            )
            or 0
        ),
    }
    ownership_transaction_mismatches = {
        "accession_attempts": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialAccessionAttempt)
                .where(
                    SecFinancialAccessionAttempt.operation_id == operation_id,
                    SecFinancialAccessionAttempt.created_txid
                    != operation.created_txid,
                )
            )
            or 0
        ),
        "operation_snapshot_links": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialOperationSnapshot)
                .where(
                    SecFinancialOperationSnapshot.operation_id == operation_id,
                    SecFinancialOperationSnapshot.created_txid
                    != operation.created_txid,
                )
            )
            or 0
        ),
        "attempt_artifact_links": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialAccessionAttemptArtifact)
                .where(
                    SecFinancialAccessionAttemptArtifact.attempt_id.in_(attempt_ids),
                    SecFinancialAccessionAttemptArtifact.created_txid
                    != operation.created_txid,
                )
            )
            or 0
        ),
        "parse_runs": int(
            db.scalar(
                select(func.count())
                .select_from(SecFinancialParseRun)
                .where(
                    SecFinancialParseRun.operation_id == operation_id,
                    SecFinancialParseRun.created_txid != operation.created_txid,
                )
            )
            or 0
        ),
        "terminal_result": int(terminal.created_txid != operation.created_txid),
    }
    if any(ownership_transaction_mismatches.values()):
        raise ValueError(
            f"acceptance operation ownership transaction mismatch: "
            f"{case_id} pass {acceptance_pass}"
        )
    return {
        "operation_id": operation_id,
        "attempted_at": operation.attempted_at.isoformat(),
        "available_at": availability.available_at.isoformat(),
        "created_txid": operation.created_txid,
        "terminal_result_kind": terminal.result_kind,
        "reported_created": dict(sorted(reported_created.items())),
        "database_created": dict(sorted(database_created.items())),
        "ownership": ownership,
        "ownership_transaction_mismatches": ownership_transaction_mismatches,
    }


def audit_case_report_operation(
    db: Session,
    *,
    expected_run_id: str,
    case: dict[str, Any],
    report: dict[str, Any],
    acceptance_pass: int,
    expected_filing_selection_as_of: datetime,
    expected_completed_fiscal_years: tuple[int, ...],
) -> dict[str, Any]:
    """Validate one stable case report against its finalized DB operation."""

    case_id = str(case["case_id"])
    if (
        report.get("schema_version") != 2
        or report.get("run_id") != expected_run_id
        or report.get("case_id") != case_id
        or report.get("acceptance_pass") != acceptance_pass
    ):
        validate_case_report_structure(
            report,
            expected_run_id=expected_run_id,
            expected_case_id=case_id,
            expected_pass=acceptance_pass,
        )
    if _report_datetime(report, "filing_selection_as_of", case_id) != expected_filing_selection_as_of:
        raise ValueError(f"acceptance report filing selection cutoff mismatch: {case_id}")
    if tuple(report.get("expected_completed_fiscal_years", ())) != expected_completed_fiscal_years:
        raise ValueError(f"acceptance report expected fiscal years mismatch: {case_id}")
    validate_case_report_structure(
        report,
        expected_run_id=expected_run_id,
        expected_case_id=case_id,
        expected_pass=acceptance_pass,
    )
    identity, stock = _case_database_identity(db, case=case)
    if str(report.get("cik")) != identity.cik or int(
        report.get("stock_id", -1)
    ) != stock.id:
        raise ValueError(
            f"acceptance report issuer identity mismatch: {case_id} pass {acceptance_pass}"
        )
    acquisition = _schema_v2_acquisition_audit(
        db,
        report=report,
        case_id=case_id,
        identity=identity,
    )
    final_links = [
        item
        for item in acquisition["attempt_authority"]["links"]
        if str(item["operation_id"]) == str(report["operation_id"])
        and str(item["operation_role"]) != "recovered"
    ]
    if len(final_links) != 1:
        raise ValueError(f"acceptance final operation attempt mismatch: {case_id}")
    publication = _schema_v2_publication_audit(
        db,
        report=report,
        case_id=case_id,
        stock=stock,
        expected_attempt_id=int(final_links[0]["attempt_id"]),
        expected_acceptance_pass=acceptance_pass,
        expected_completed_fiscal_years=expected_completed_fiscal_years,
    )
    return {
        "operation_id": report["operation_id"],
        "acquisition": acquisition,
        "publication": publication,
    }


def _counter_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> int:
    value = int(after.get(key, 0)) - int(before.get(key, 0))
    if value < 0:
        raise ValueError(f"Rate Guard cumulative counter decreased: {key}")
    return value


def build_aggregate_payload(
    *,
    run_id: str,
    expected_case_ids: tuple[str, ...],
    before: dict[str, Any],
    after: dict[str, Any],
    cases: list[dict[str, Any]],
    source_path_proof: dict[str, Any],
) -> dict[str, Any]:
    if (
        before.get("run_id") != run_id
        or after.get("run_id") != run_id
        or before.get("database") != after.get("database")
        or before.get("source_path_proof") != source_path_proof
        or after.get("source_path_proof") != source_path_proof
    ):
        raise ValueError("runtime snapshot identity/source path mismatch")
    before_guard = dict(before["rate_guard"])
    after_guard = dict(after["rate_guard"])
    before_metrics = dict(before_guard["metrics"])
    after_metrics = dict(after_guard["metrics"])
    shared_observed_window_delta = {
        "requests": _counter_delta(
            before_metrics, after_metrics, "total_request_count"
        ),
        "403": _counter_delta(before_metrics, after_metrics, "total_403_count"),
        "429": _counter_delta(before_metrics, after_metrics, "total_429_count"),
        "503": _counter_delta(before_metrics, after_metrics, "total_503_count"),
        "cache_hits": _counter_delta(before_metrics, after_metrics, "cache_hits"),
        "cache_misses": _counter_delta(
            before_metrics, after_metrics, "cache_misses"
        ),
    }
    retained = {
        key: sum(int(case["retained_integrity"][key]) for case in cases)
        for key in ("checked", "failed", "bytes")
    }
    duplicates = {
        key: sum(int(case["duplicates"][key]) for case in cases)
        for key in (
            "filings",
            "artifacts",
            "parse_runs",
            "raw_facts",
            "current_sec_slots",
        )
    }
    metric_outcomes = {
        "metric_denominator": 21,
        "issuer_year_metric_denominator": sum(
            int(case["metric_outcomes"]["issuer_year_metric_denominator"])
            for case in cases
        ),
        "published_count": sum(
            int(case["metric_outcomes"]["published_count"])
            for case in cases
        ),
        "typed_gap_count": sum(
            int(case["metric_outcomes"]["typed_gap_count"])
            for case in cases
        ),
        "missing_count": sum(
            int(case["metric_outcomes"]["missing_count"])
            for case in cases
        ),
        "coverage_count": sum(
            int(case["metric_outcomes"]["coverage_count"])
            for case in cases
        ),
    }
    payload = {
        "schema_version": 2,
        "run_id": run_id,
        "expected_case_ids": list(expected_case_ids),
        "case_count": len(cases),
        "cases": sorted(cases, key=lambda item: str(item["case_id"])),
        "idempotent_case_count": sum(
            1 for case in cases if case["idempotency_delta"]["idempotent"]
        ),
        "metric_facts_before": int(before["metric_facts"]),
        "metric_facts_after": int(after["metric_facts"]),
        "retained_integrity": retained,
        "duplicate_totals": duplicates,
        "metric_outcomes": metric_outcomes,
        "mapping_versions": sorted(
            {ACCEPTANCE_MAPPING_VERSION_ID for case in cases}
        ),
        "method_policy_versions": sorted(
            {ACCEPTANCE_METHOD_POLICY_VERSION_ID for case in cases}
        ),
        "publication_requested_cutoffs": {
            str(case["case_id"]): case["pass_1"]["publication_requested_cutoff"]
            for case in cases
        },
        "rate_guard_before": before_guard,
        "rate_guard_after": after_guard,
        "shared_observed_window_delta": shared_observed_window_delta,
        "source_path_proof": source_path_proof,
    }
    return payload


def validate_aggregate_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 2:
        raise ValueError("aggregate report schema identity mismatch")
    expected = list(payload["expected_case_ids"])
    actual = [str(case["case_id"]) for case in payload["cases"]]
    if len(expected) != int(payload["case_count"]) or sorted(expected) != sorted(actual):
        raise ValueError("aggregate report does not contain every locked case exactly once")
    if int(payload["metric_facts_before"]) != 0:
        raise ValueError("FT-04 acceptance must start without metric_facts")
    metric_outcomes = payload["metric_outcomes"]
    if (
        int(metric_outcomes.get("metric_denominator", -1)) != 21
        or int(metric_outcomes.get("published_count", -1))
        + int(metric_outcomes.get("typed_gap_count", -1))
        + int(metric_outcomes.get("missing_count", -1))
        != int(metric_outcomes.get("issuer_year_metric_denominator", -1))
        or int(metric_outcomes.get("coverage_count", -1))
        != int(metric_outcomes.get("published_count", -1))
    ):
        raise ValueError("aggregate metric outcome denominator mismatch")
    if int(payload["metric_facts_after"]) < int(
        metric_outcomes["published_count"]
    ):
        raise ValueError("canonical published outcomes exceed durable metric_facts")
    if int(payload["retained_integrity"]["failed"]) != 0:
        raise ValueError("retained artifact integrity failures are present")
    if any(int(value) for value in payload["duplicate_totals"].values()):
        raise ValueError("duplicate SEC lineage rows are present")
    if int(payload.get("idempotent_case_count", -1)) != int(payload["case_count"]):
        raise ValueError("acceptance second pass is not idempotent for every case")
    if payload["rate_guard_before"]["instance_id"] != payload["rate_guard_after"][
        "instance_id"
    ]:
        raise ValueError("Rate Guard instance changed during acceptance")
    proof = payload["source_path_proof"]
    if (
        not proof.get("configured_route")
        or not proof.get("expected_instance_id")
        or proof.get("fetch_mode") != "rate_guard"
        or proof.get("fallback_enabled") is not False
        or proof.get("fallback_url") is not None
    ):
        raise ValueError("acceptance source path is not the single configured Rate Guard")
    if float(payload["rate_guard_after"]["metrics"]["rate_per_sec"]) > 1.0:
        raise ValueError("acceptance Rate Guard exceeds the 1 request/second policy")
    if payload.get("mapping_versions") != [ACCEPTANCE_MAPPING_VERSION_ID] or payload.get(
        "method_policy_versions"
    ) != [ACCEPTANCE_METHOD_POLICY_VERSION_ID]:
        raise ValueError("acceptance authority versions are not the locked V1 versions")
    if int(metric_outcomes["typed_gap_count"]) or int(
        metric_outcomes["missing_count"]
    ):
        raise ValueError("acceptance canonical metric outcomes remain incomplete")


def render_human_aggregate_summary(payload: dict[str, Any]) -> str:
    delta = payload["shared_observed_window_delta"]
    retained = payload["retained_integrity"]
    duplicates = payload["duplicate_totals"]
    lines = [
        f"acceptance_run_id={payload['run_id']}",
        f"cases={payload['case_count']}/{len(payload['expected_case_ids'])}",
        f"idempotent_cases={payload['idempotent_case_count']}/{payload['case_count']}",
        (
            f"shared_observed_window_requests={delta['requests']} 403={delta['403']} "
            f"429={delta['429']} 503={delta['503']}"
        ),
        (
            f"retained_checked={retained['checked']} "
            f"retained_failed={retained['failed']} retained_bytes={retained['bytes']}"
        ),
        (
            f"duplicates_filings={duplicates['filings']} "
            f"artifacts={duplicates['artifacts']} parse_runs={duplicates['parse_runs']} "
            f"raw_facts={duplicates['raw_facts']} "
            f"current_sec_slots={duplicates['current_sec_slots']}"
        ),
        (
            f"metric_facts_before={payload['metric_facts_before']} "
            f"metric_facts_after={payload['metric_facts_after']}"
        ),
        (
            f"issuer_year_metric_denominator={payload['metric_outcomes']['issuer_year_metric_denominator']} "
            f"published={payload['metric_outcomes']['published_count']} "
            f"typed_gaps={payload['metric_outcomes']['typed_gap_count']} "
            f"missing={payload['metric_outcomes']['missing_count']}"
        ),
        (
            f"mapping_versions={','.join(payload['mapping_versions'])} "
            f"method_policy_versions={','.join(payload['method_policy_versions'])}"
        ),
    ]
    for case in payload["cases"]:
        coverage = case.get("covered_completed_fiscal_years", [])
        expected = case.get("expected_completed_fiscal_years", [])
        lines.append(
            f"case={case['case_id']} ticker={case['ticker']} cik={case['cik']} "
            f"fiscal_years={len(coverage)}/{len(expected)} "
            f"integrity_failures={case['retained_integrity']['failed']} "
            f"idempotent={str(case['idempotency_delta']['idempotent']).lower()}"
        )
    return "\n".join(lines)


def write_stable_json(
    payload: dict[str, Any], *, destination: Path, storage_root: Path
) -> None:
    secure_atomic_write_bytes(
        storage_root=storage_root,
        destination=destination,
        content=(json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
    )


def write_stable_text(
    content: str, *, destination: Path, storage_root: Path
) -> None:
    secure_atomic_write_bytes(
        storage_root=storage_root,
        destination=destination,
        content=(content.rstrip() + "\n").encode(),
    )


def load_stable_json(path: Path, *, storage_root: Path) -> dict[str, Any]:
    return secure_read_json(storage_root=storage_root, source=path)


def _count(db: Session, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def rate_guard_configuration_digest(
    *,
    configured_route: str,
    expected_instance_id: str,
    fetch_mode: str,
    fallback_enabled: bool,
    fallback_url: str | None,
) -> str:
    payload = {
        "configured_route": configured_route.rstrip("/"),
        "expected_instance_id": expected_instance_id,
        "fallback_enabled": fallback_enabled,
        "fallback_url": fallback_url,
        "fetch_mode": fetch_mode,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def persist_rate_guard_snapshot(
    db: Session,
    *,
    run_id: str,
    phase: str,
    configured_route: str,
    expected_instance_id: str,
    observed_instance_id: str,
    fetch_mode: str,
    fallback_enabled: bool,
    fallback_url: str | None,
    metrics: dict[str, Any],
    manifest_digest: str,
    database_name: str,
    storage_root: Path,
) -> dict[str, Any]:
    config_digest = rate_guard_configuration_digest(
        configured_route=configured_route,
        expected_instance_id=expected_instance_id,
        fetch_mode=fetch_mode,
        fallback_enabled=fallback_enabled,
        fallback_url=fallback_url,
    )
    retained = retained_storage_authority(storage_root)
    db.execute(
        text(
            """INSERT INTO sec_acceptance_rate_guard_snapshots
              (run_id,phase,configured_route,expected_instance_id,
               observed_instance_id,fetch_mode,fallback_enabled,fallback_url,
               rate_per_sec,total_request_count,total_403_count,total_429_count,
               total_503_count,cache_hits,cache_misses,config_digest,
               manifest_digest,database_name,runtime_counts,
               retained_file_count,retained_bytes,retained_manifest_digest,
               captured_at,created_at,created_txid)
              VALUES
              (:run,:phase,:route,:expected,:observed,:mode,:fallback,:fallback_url,
               :rate,:requests,:c403,:c429,:c503,:hits,:misses,:config,:manifest,
               :database,'{}'::jsonb,:file_count,:bytes,:storage_digest,
               clock_timestamp(),clock_timestamp(),txid_current())
              ON CONFLICT (run_id,phase) DO NOTHING"""
        ),
        {
            "run": run_id,
            "phase": phase,
            "route": configured_route,
            "expected": expected_instance_id,
            "observed": observed_instance_id,
            "mode": fetch_mode,
            "fallback": fallback_enabled,
            "fallback_url": fallback_url,
            "rate": metrics.get("rate_per_sec"),
            "requests": metrics.get("total_request_count", 0),
            "c403": metrics.get("total_403_count", 0),
            "c429": metrics.get("total_429_count", 0),
            "c503": metrics.get("total_503_count", 0),
            "hits": metrics.get("cache_hits", 0),
            "misses": metrics.get("cache_misses", 0),
            "config": config_digest,
            "manifest": manifest_digest,
            "database": database_name,
            "file_count": retained["file_count"],
            "bytes": retained["bytes"],
            "storage_digest": retained["manifest_digest"],
        },
    )
    db.commit()
    authority = load_rate_guard_snapshot(db, run_id=run_id, phase=phase)
    proof = authority["source_path_proof"]
    if proof != {
        "configured_route": configured_route.rstrip("/"),
        "expected_instance_id": expected_instance_id,
        "fetch_mode": fetch_mode,
        "fallback_enabled": fallback_enabled,
        "fallback_url": fallback_url,
        "config_digest": config_digest,
        "manifest_digest": manifest_digest,
    } or authority["rate_guard"]["instance_id"] != observed_instance_id:
        raise ValueError("durable Rate Guard snapshot identity/configuration mismatch")
    if authority["database"] != database_name or authority["retained_storage"] != retained:
        raise ValueError("durable runtime database/storage identity mismatch")
    current_counts = {
        str(key): int(value)
        for key, value in dict(
            db.execute(text("SELECT sec_acceptance_runtime_counts()" )).scalar_one()
        ).items()
    }
    if current_counts != authority["lineage_counts"]:
        raise ValueError("durable runtime checkpoint exact replay mismatch")
    durable_metrics = authority["rate_guard"]["metrics"]
    for key in (
        "total_request_count",
        "total_403_count",
        "total_429_count",
        "total_503_count",
        "cache_hits",
        "cache_misses",
    ):
        if int(metrics.get(key, 0)) < int(durable_metrics[key]):
            raise ValueError(f"live Rate Guard counter regressed: {key}")
    if float(metrics.get("rate_per_sec", 0)) != float(
        durable_metrics["rate_per_sec"]
    ):
        raise ValueError("durable Rate Guard rate policy mismatch")
    return authority


def retained_storage_authority(storage_root: Path) -> dict[str, Any]:
    """Hash a stable descriptor-relative view of retained financial evidence."""

    root = storage_root.absolute()
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    entry_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK

    def identity(item: os.stat_result) -> tuple[int, ...]:
        return (
            item.st_dev,
            item.st_ino,
            item.st_mode,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )

    def verify_component(
        parent_fd: int, name: str, expected: os.stat_result
    ) -> None:
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("retained storage identity race: component disappeared") from exc
        if identity(current) != identity(expected):
            raise ValueError("retained storage identity race: component changed")

    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise ValueError("retained storage root is not a stable directory") from exc
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    visited = 0

    def walk(directory_fd: int, relative_parts: tuple[str, ...]) -> None:
        nonlocal total_bytes, visited
        directory_before = os.fstat(directory_fd)
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as exc:
            raise ValueError("retained storage identity race: directory changed") from exc
        for name in names:
            visited += 1
            if visited > 20_000:
                raise ValueError("retained storage enumeration exceeded bounded entries")
            try:
                child_fd = os.open(name, entry_flags, dir_fd=directory_fd)
            except OSError as exc:
                raise ValueError(
                    "retained storage identity race: unsafe component"
                ) from exc
            try:
                before = os.fstat(child_fd)
                parts = (*relative_parts, name)
                if stat.S_ISDIR(before.st_mode):
                    if (
                        len(parts) != 1
                        or len(name) != 2
                        or any(char not in "0123456789abcdef" for char in name)
                    ):
                        raise ValueError(
                            "retained storage has invalid content-addressed directory"
                        )
                    walk(child_fd, parts)
                elif stat.S_ISREG(before.st_mode):
                    if (
                        len(parts) != 2
                        or len(parts[1]) != 64
                        or any(
                            char not in "0123456789abcdef" for char in parts[1]
                        )
                        or parts[0] != parts[1][:2]
                    ):
                        raise ValueError(
                            "retained storage has invalid content-addressed object"
                        )
                    digest = hashlib.sha256()
                    observed_size = 0
                    while True:
                        chunk = os.read(child_fd, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        observed_size += len(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > 20_000_000_000:
                            raise ValueError(
                                "retained storage enumeration exceeded bounded bytes"
                            )
                    after = os.fstat(child_fd)
                    if identity(before) != identity(after) or observed_size != before.st_size:
                        raise ValueError(
                            "retained storage identity race: file changed during read"
                        )
                    sha256 = digest.hexdigest()
                    if sha256 != parts[1]:
                        raise ValueError(
                            "retained content-addressed object hash mismatch"
                        )
                    entries.append(
                        {
                            "path": PurePosixPath("financial", *parts).as_posix(),
                            "size": observed_size,
                            "sha256": sha256,
                        }
                    )
                else:
                    raise ValueError("retained storage rejects special files")
                verify_component(directory_fd, name, before)
            finally:
                os.close(child_fd)
        directory_after = os.fstat(directory_fd)
        if identity(directory_before) != identity(directory_after):
            raise ValueError("retained storage identity race: directory changed")

    try:
        root_before = os.fstat(root_fd)
        try:
            financial_fd = os.open("financial", directory_flags, dir_fd=root_fd)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                entries = []
            else:
                raise ValueError(
                    "retained financial storage root is not a stable directory"
                ) from exc
        else:
            try:
                financial_before = os.fstat(financial_fd)
                walk(financial_fd, ())
                verify_component(root_fd, "financial", financial_before)
            finally:
                os.close(financial_fd)
        root_after = os.fstat(root_fd)
        if identity(root_before) != identity(root_after):
            raise ValueError("retained storage identity race: root changed")
        root_path = os.stat(root, follow_symlinks=False)
        if identity(root_before) != identity(root_path):
            raise ValueError("retained storage identity race: root replaced")
    finally:
        os.close(root_fd)
    entries.sort(key=lambda item: item["path"])
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "file_count": len(entries),
        "bytes": sum(int(item["size"]) for item in entries),
        "manifest_digest": hashlib.sha256(canonical).hexdigest(),
    }


def load_rate_guard_snapshot(
    db: Session, *, run_id: str, phase: str
) -> dict[str, Any]:
    row = db.execute(
        text(
            """SELECT * FROM sec_acceptance_rate_guard_snapshots
               WHERE run_id=:run AND phase=:phase"""
        ),
        {"run": run_id, "phase": phase},
    ).mappings().one()
    metrics = {
        "rate_per_sec": float(row.rate_per_sec),
        "total_request_count": int(row.total_request_count),
        "total_403_count": int(row.total_403_count),
        "total_429_count": int(row.total_429_count),
        "total_503_count": int(row.total_503_count),
        "cache_hits": int(row.cache_hits),
        "cache_misses": int(row.cache_misses),
    }
    runtime_counts = {
        str(key): int(value) for key, value in dict(row.runtime_counts).items()
    }
    return {
        "schema_version": 2,
        "run_id": run_id,
        "captured_at": row.captured_at.isoformat(),
        "database": row.database_name,
        "metric_facts": runtime_counts["metric_facts_total"],
        "metric_fact_source_counts": {
            "sec": runtime_counts["metric_facts"],
            "manual": runtime_counts["metric_facts_manual"],
            "other": runtime_counts["metric_facts_other"],
            "user_owned": runtime_counts["metric_facts_user_owned"],
        },
        "lineage_counts": runtime_counts,
        "retained_storage": {
            "file_count": int(row.retained_file_count),
            "bytes": int(row.retained_bytes),
            "manifest_digest": row.retained_manifest_digest.strip(),
        },
        "rate_guard": {
            "url": row.configured_route,
            "expected_instance_id": row.expected_instance_id,
            "instance_id": row.observed_instance_id,
            "metrics": metrics,
        },
        "source_path_proof": {
            "configured_route": row.configured_route,
            "expected_instance_id": row.expected_instance_id,
            "fetch_mode": row.fetch_mode,
            "fallback_enabled": row.fallback_enabled,
            "fallback_url": row.fallback_url,
            "config_digest": row.config_digest.strip(),
            "manifest_digest": row.manifest_digest.strip(),
        },
    }


def audit_runtime_snapshot_rate_guard(
    db: Session,
    *,
    payload: dict[str, Any],
    run_id: str,
    phase: str,
    storage_root: Path | None = None,
    verify_current: bool = False,
) -> dict[str, Any]:
    authority = load_rate_guard_snapshot(db, run_id=run_id, phase=phase)
    if payload != authority:
        raise ValueError("runtime JSON does not match durable runtime authority")
    if verify_current:
        current_counts = {
            str(key): int(value)
            for key, value in dict(
                db.execute(text("SELECT sec_acceptance_runtime_counts()" )).scalar_one()
            ).items()
        }
        if current_counts != authority["lineage_counts"]:
            raise ValueError("database changed after durable runtime checkpoint")
        try:
            current_storage = (
                retained_storage_authority(storage_root)
                if storage_root is not None
                else None
            )
        except ValueError as exc:
            raise ValueError(
                f"retained storage changed after durable runtime checkpoint: {exc}"
            ) from exc
        if current_storage != authority["retained_storage"]:
            raise ValueError("retained storage changed after durable runtime checkpoint")
    return authority


def build_runtime_snapshot(
    db: Session,
    *,
    run_id: str,
    database_name: str,
    storage_root: Path,
    rate_guard_authority: dict[str, Any],
) -> dict[str, Any]:
    if rate_guard_authority.get("run_id") != run_id:
        raise ValueError("durable runtime run identity mismatch")
    if rate_guard_authority.get("database") != database_name:
        raise ValueError("durable runtime database identity mismatch")
    if rate_guard_authority.get("retained_storage") != retained_storage_authority(
        storage_root
    ):
        raise ValueError("durable runtime retained storage identity mismatch")
    return dict(rate_guard_authority)


def _duplicate_excess(db: Session, statement) -> int:
    return sum(int(row[-1]) - 1 for row in db.execute(statement).all())


def _control_plane_counts(db: Session, operation_ids: set[str]) -> dict[str, int]:
    ids = list(operation_ids)
    if not ids:
        raise ValueError("acceptance control plane requires operation identities")
    queries = {
        "ingestion_operations": "SELECT count(*) FROM sec_financial_ingestion_operations WHERE id=ANY(:ids)",
        "operation_results": "SELECT count(*) FROM sec_financial_operation_results WHERE operation_id=ANY(:ids)",
        "lineage_availabilities": "SELECT count(*) FROM sec_financial_lineage_availabilities WHERE operation_id=ANY(:ids)",
        "accession_attempts": "SELECT count(*) FROM sec_financial_accession_attempts WHERE operation_id=ANY(:ids)",
        "operation_snapshot_links": "SELECT count(*) FROM sec_financial_operation_snapshots WHERE operation_id=ANY(:ids)",
        "acquisition_resolutions": "SELECT count(*) FROM sec_financial_acquisition_resolutions WHERE operation_id=ANY(:ids)",
        "resource_anchors": "SELECT count(*) FROM sec_financial_resource_anchors WHERE operation_id=ANY(:ids)",
        "history_continuations": "SELECT count(*) FROM sec_financial_history_continuations WHERE source_operation_id=ANY(:ids)",
        "history_consumption_claims": "SELECT count(*) FROM sec_financial_history_consumption_claims WHERE operation_id=ANY(:ids)",
        "history_continuation_failures": "SELECT count(*) FROM sec_financial_history_continuation_failures WHERE operation_id=ANY(:ids)",
        "acquisition_failures": "SELECT count(*) FROM sec_financial_acquisition_failures WHERE operation_id=ANY(:ids)",
        "attempt_artifact_links": """SELECT count(*) FROM sec_financial_accession_attempt_artifacts link
          JOIN sec_financial_accession_attempts attempt ON attempt.id=link.attempt_id
          WHERE attempt.operation_id=ANY(:ids)""",
    }
    counts = {
        key: int(db.execute(text(sql), {"ids": ids}).scalar_one())
        for key, sql in queries.items()
    }
    if (
        counts["ingestion_operations"] != len(ids)
        or counts["operation_results"] != len(ids)
        or counts["lineage_availabilities"] != len(ids)
    ):
        raise ValueError("acceptance control-plane terminal identity mismatch")
    return counts


def build_case_database_audit(
    db: Session,
    *,
    expected_run_id: str,
    case: dict[str, Any],
    manifest: dict[str, Any],
    pass_one: dict[str, Any],
    pass_two: dict[str, Any],
    storage_root: Path,
) -> dict[str, Any]:
    cik = str(case["cik"])
    identity, stock = _case_database_identity(db, case=case)
    case_id = str(case["case_id"])
    locked_cutoff, expected_years = locked_case_contract(manifest, case)
    pass_one_operation = audit_case_report_operation(
        db,
        report=pass_one,
        acceptance_pass=1,
        expected_run_id=expected_run_id,
        case=case,
        expected_filing_selection_as_of=locked_cutoff,
        expected_completed_fiscal_years=expected_years,
    )
    pass_two_operation = audit_case_report_operation(
        db,
        report=pass_two,
        acceptance_pass=2,
        expected_run_id=expected_run_id,
        case=case,
        expected_filing_selection_as_of=locked_cutoff,
        expected_completed_fiscal_years=expected_years,
    )
    pass_one_delta = load_acceptance_evidence_delta(
        db,
        run_id=expected_run_id,
        case_id=case_id,
        acceptance_pass=1,
    )
    pass_two_delta = load_acceptance_evidence_delta(
        db,
        run_id=expected_run_id,
        case_id=case_id,
        acceptance_pass=2,
    )
    checkpoint_operations = {
        int(row.acceptance_pass): str(row.operation_id)
        for row in db.execute(
            text(
                """SELECT acceptance_pass,operation_id
                   FROM sec_acceptance_evidence_checkpoints
                   WHERE run_id=:run AND case_id=:case AND phase='after'"""
            ),
            {"run": expected_run_id, "case": case_id},
        ).all()
    }
    if checkpoint_operations != {
        1: pass_one["operation_id"],
        2: pass_two["operation_id"],
    }:
        raise ValueError(f"acceptance evidence checkpoint operation mismatch: {case_id}")
    readiness = {
        int(row.acceptance_pass): row
        for row in db.execute(
            text(
                """SELECT acceptance_pass,operation_id,report_sha256,report_ready_at
                   FROM sec_acceptance_report_readiness
                   WHERE run_id=:run AND case_id=:case"""
            ),
            {"run": expected_run_id, "case": case_id},
        ).mappings()
    }
    if set(readiness) != {1, 2}:
        raise ValueError(f"acceptance report readiness authority is incomplete: {case_id}")
    for pass_number, report in ((1, pass_one), (2, pass_two)):
        encoded = (
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        ready = readiness[pass_number]
        if (
            str(ready.operation_id) != str(report["operation_id"])
            or str(ready.report_sha256).strip()
            != hashlib.sha256(encoded).hexdigest()
        ):
            raise ValueError(f"acceptance report readiness digest mismatch: {case_id}")
    if pass_one.get("persistent_delta") != pass_one_delta:
        raise ValueError(f"acceptance pass one evidence delta mismatch: {case_id}")
    if pass_two.get("persistent_delta") != pass_two_delta:
        raise ValueError(f"acceptance pass two evidence delta mismatch: {case_id}")
    if not pass_two_delta["idempotent"]:
        raise ValueError(f"acceptance pass two evidence plane is not zero delta: {case_id}")
    if pass_one_operation["operation_id"] == pass_two_operation["operation_id"]:
        raise ValueError(f"acceptance passes reuse one operation: {case_id}")
    pass_one_operations = {
        item["operation_id"] for item in pass_one["acquisition_operations"]
    }
    pass_two_operations = {
        item["operation_id"] for item in pass_two["acquisition_operations"]
    }
    if pass_one_operations & pass_two_operations:
        raise ValueError(f"acceptance passes reuse acquisition operation identity: {case_id}")
    if (
        pass_one["publication_run_id"] != pass_two["publication_run_id"]
        or pass_one["publication_requested_cutoff"]
        != pass_two["publication_requested_cutoff"]
        or pass_one["publication_source_accessions"]
        != pass_two["publication_source_accessions"]
        or pass_one["publication_run_source_ids"]
        != pass_two["publication_run_source_ids"]
        or pass_one["publication_source_parse_run_ids"]
        != pass_two["publication_source_parse_run_ids"]
        or pass_one["publication_decision_ids"]
        != pass_two["publication_decision_ids"]
    ):
        raise ValueError(f"acceptance pass two is not an exact publication replay: {case_id}")

    filings = list(
        db.scalars(
            select(SecFinancialFiling)
            .where(SecFinancialFiling.issuer_identity_id == identity.id)
            .order_by(SecFinancialFiling.accepted_at, SecFinancialFiling.accession_no)
        ).all()
    )
    filing_ids = [item.id for item in filings]
    artifacts = list(
        db.scalars(
            select(SecFilingArtifact)
            .where(SecFilingArtifact.filing_id.in_(filing_ids or [-1]))
            .order_by(SecFilingArtifact.filing_id, SecFilingArtifact.id)
        ).all()
    )
    parse_runs = list(
        db.scalars(
            select(SecFinancialParseRun)
            .where(SecFinancialParseRun.filing_id.in_(filing_ids or [-1]))
            .order_by(SecFinancialParseRun.filing_id, SecFinancialParseRun.id)
        ).all()
    )
    snapshots = list(
        db.scalars(
            select(SecSubmissionSnapshot)
            .where(SecSubmissionSnapshot.issuer_identity_id == identity.id)
            .order_by(SecSubmissionSnapshot.id)
        ).all()
    )
    filing_by_id = {item.id: item for item in filings}

    retained: list[dict[str, Any]] = []
    for snapshot in snapshots:
        result = audit_retained_file(
            storage_root=storage_root,
            storage_key=snapshot.storage_key,
            expected_size=snapshot.byte_size,
            expected_sha256=snapshot.sha256,
        )
        retained.append(
            {
                "kind": "submission_snapshot",
                "id": snapshot.id,
                "source_url": snapshot.source_url,
                "storage_key": snapshot.storage_key,
                "expected_size": snapshot.byte_size,
                "expected_sha256": snapshot.sha256,
                **result,
            }
        )
    for artifact in artifacts:
        if artifact.state != "retained":
            continue
        if artifact.storage_key is None or artifact.byte_size is None or artifact.sha256 is None:
            raise ValueError(f"retained artifact has incomplete identity: {artifact.id}")
        result = audit_retained_file(
            storage_root=storage_root,
            storage_key=artifact.storage_key,
            expected_size=artifact.byte_size,
            expected_sha256=artifact.sha256,
        )
        retained.append(
            {
                "kind": "filing_artifact",
                "id": artifact.id,
                "accession_no": filing_by_id[artifact.filing_id].accession_no,
                "filename": artifact.filename,
                "source_url": artifact.source_url,
                "storage_key": artifact.storage_key,
                "expected_size": artifact.byte_size,
                "expected_sha256": artifact.sha256,
                **result,
            }
        )

    retained_keys = {str(item["storage_key"]): item for item in retained}
    annual_forms = {"10-K", "10-K/A", "20-F", "20-F/A"}
    rebuilt_selected = pass_one_operation["acquisition"]["selected_filings"]
    covered_years = sorted(
        {
            int(item["report_date"][:4])
            for item in rebuilt_selected
            if item.get("form_type") in annual_forms and item.get("report_date")
        },
        reverse=True,
    )
    parse_statuses: dict[str, int] = {}
    parse_failures: dict[str, int] = {}
    for run in parse_runs:
        parse_statuses[run.status] = parse_statuses.get(run.status, 0) + 1
        if run.error_code:
            parse_failures[run.error_code] = parse_failures.get(run.error_code, 0) + 1

    artifact_duplicate_stmt = (
        select(
            SecFilingArtifact.filing_id,
            SecFilingArtifact.filename,
            SecFilingArtifact.manifest_hash,
            SecFilingArtifact.state,
            func.count(),
        )
        .where(SecFilingArtifact.filing_id.in_(filing_ids or [-1]))
        .group_by(
            SecFilingArtifact.filing_id,
            SecFilingArtifact.filename,
            SecFilingArtifact.manifest_hash,
            SecFilingArtifact.state,
        )
        .having(func.count() > 1)
    )
    parse_duplicate_stmt = (
        select(
            SecFinancialParseRun.filing_id,
            SecFinancialParseRun.parser_version,
            SecFinancialParseRun.input_manifest_hash,
            func.count(),
        )
        .where(SecFinancialParseRun.filing_id.in_(filing_ids or [-1]))
        .group_by(
            SecFinancialParseRun.filing_id,
            SecFinancialParseRun.parser_version,
            SecFinancialParseRun.input_manifest_hash,
        )
        .having(func.count() > 1)
    )
    parse_ids = [item.id for item in parse_runs]
    raw_duplicate_stmt = (
        select(SecRawXbrlFact.parse_run_id, SecRawXbrlFact.ordinal, func.count())
        .where(SecRawXbrlFact.parse_run_id.in_(parse_ids or [-1]))
        .group_by(SecRawXbrlFact.parse_run_id, SecRawXbrlFact.ordinal)
        .having(func.count() > 1)
    )
    filing_duplicate_stmt = (
        select(SecFinancialFiling.accession_no, func.count())
        .where(SecFinancialFiling.issuer_identity_id == identity.id)
        .group_by(SecFinancialFiling.accession_no)
        .having(func.count() > 1)
    )
    raw_fact_count = int(
        db.scalar(
            select(func.count())
            .select_from(SecRawXbrlFact)
            .where(SecRawXbrlFact.parse_run_id.in_(parse_ids or [-1]))
        )
        or 0
    )
    return {
        "case_id": case_id,
        "ticker": stock.ticker,
        "manifest_ticker": str(case["primary_listing"]["ticker"]),
        "company_name": stock.company_name,
        "stock_id": stock.id,
        "issuer_identity_id": identity.id,
        "identity_status": identity.status,
        "cik": cik,
        "filing_selection_as_of": locked_cutoff.isoformat(),
        "expected_completed_fiscal_years": list(expected_years),
        "covered_completed_fiscal_years": covered_years,
        "missing_completed_fiscal_years": sorted(
            set(expected_years) - set(covered_years), reverse=True
        ),
        "selected_forms": sorted({item["form_type"] for item in rebuilt_selected}),
        "selected_accessions": [
            {
                "accession_no": item["accession_no"],
                "form_type": item["form_type"],
                "report_date": item.get("report_date"),
                "accepted_at": item["accepted_at"],
            }
            for item in rebuilt_selected
        ],
        "metric_outcomes": pass_one_operation["publication"]["metric_outcomes"],
        "pass_1": pass_one,
        "pass_2": pass_two,
        "idempotency_delta": pass_two_delta,
        "operation_audits": {
            "pass_1": pass_one_operation,
            "pass_2": pass_two_operation,
        },
        "control_plane": {
            "pass_1": _control_plane_counts(db, pass_one_operations),
            "pass_2": _control_plane_counts(db, pass_two_operations),
        },
        "retained_artifacts": retained,
        "retained_integrity": {
            "checked": len(retained),
            "failed": sum(1 for item in retained if not item["integrity_ok"]),
            "unique_objects": len(retained_keys),
            "bytes": sum(int(item["actual_size"] or 0) for item in retained_keys.values()),
        },
        "lineage": {
            "submission_snapshots": len(snapshots),
            "filings": len(filings),
            "artifacts": len(artifacts),
            "artifact_states": {
                state: sum(1 for item in artifacts if item.state == state)
                for state in sorted({item.state for item in artifacts})
            },
            "parse_runs": len(parse_runs),
            "parse_statuses": dict(sorted(parse_statuses.items())),
            "parse_failures": dict(sorted(parse_failures.items())),
            "raw_facts": raw_fact_count,
        },
        "duplicates": {
            "filings": _duplicate_excess(db, filing_duplicate_stmt),
            "artifacts": _duplicate_excess(db, artifact_duplicate_stmt),
            "parse_runs": _duplicate_excess(db, parse_duplicate_stmt),
            "raw_facts": _duplicate_excess(db, raw_duplicate_stmt),
            "current_sec_slots": int(
                pass_one_operation["publication"]["current_slot_duplicates"]
            ),
        },
    }
