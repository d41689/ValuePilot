"""Integrity and idempotency helpers for the Step D SEC gold-set audit."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, literal_column, select
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
)
from app.models.stocks import Stock


_IDEMPOTENCY_FIELDS = (
    "filings_created",
    "submission_snapshots_created",
    "artifacts_created",
    "parse_runs_created",
    "raw_facts_created",
)


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
    root = storage_root.resolve()
    target = storage_root.joinpath(*relative.parts)
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError("retained storage path must remain inside controlled storage")
    if not target.is_file():
        return {
            "actual_sha256": None,
            "actual_size": None,
            "exists": False,
            "integrity_ok": False,
            "sha256_ok": False,
            "size_ok": False,
        }
    content = target.read_bytes()
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


def validate_case_report_identity(
    payload: dict[str, Any],
    *,
    expected_run_id: str,
    expected_case_id: str,
    expected_pass: int,
) -> bool:
    identity = (
        payload.get("schema_version") == 1
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
    return bool(payload["typed_gaps"] or payload["typed_failures"])


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
    validate_case_report_identity(
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
    before_guard = dict(before["rate_guard"])
    after_guard = dict(after["rate_guard"])
    before_metrics = dict(before_guard["metrics"])
    after_metrics = dict(after_guard["metrics"])
    rate_guard_delta = {
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
        for key in ("filings", "artifacts", "parse_runs", "raw_facts")
    }
    payload = {
        "schema_version": 1,
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
        "rate_guard_before": before_guard,
        "rate_guard_after": after_guard,
        "rate_guard_delta": rate_guard_delta,
        "source_path_proof": source_path_proof,
    }
    return payload


def validate_aggregate_payload(payload: dict[str, Any]) -> None:
    expected = list(payload["expected_case_ids"])
    actual = [str(case["case_id"]) for case in payload["cases"]]
    if len(expected) != int(payload["case_count"]) or sorted(expected) != sorted(actual):
        raise ValueError("aggregate report does not contain every locked case exactly once")
    if int(payload["metric_facts_before"]) != 0 or int(
        payload["metric_facts_after"]
    ) != 0:
        raise ValueError("SEC acceptance must not publish metric_facts")
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
    if proof.get("direct_sec_path") is not False or proof.get("fallback_enabled") is not False:
        raise ValueError("acceptance source path is not the single configured Rate Guard")
    if float(payload["rate_guard_after"]["metrics"]["rate_per_sec"]) > 1.0:
        raise ValueError("acceptance Rate Guard exceeds the 1 request/second policy")


def render_human_aggregate_summary(payload: dict[str, Any]) -> str:
    delta = payload["rate_guard_delta"]
    retained = payload["retained_integrity"]
    duplicates = payload["duplicate_totals"]
    lines = [
        f"acceptance_run_id={payload['run_id']}",
        f"cases={payload['case_count']}/{len(payload['expected_case_ids'])}",
        f"idempotent_cases={payload['idempotent_case_count']}/{payload['case_count']}",
        (
            f"rate_guard_requests={delta['requests']} 403={delta['403']} "
            f"429={delta['429']} 503={delta['503']}"
        ),
        (
            f"retained_checked={retained['checked']} "
            f"retained_failed={retained['failed']} retained_bytes={retained['bytes']}"
        ),
        (
            f"duplicates_filings={duplicates['filings']} "
            f"artifacts={duplicates['artifacts']} parse_runs={duplicates['parse_runs']} "
            f"raw_facts={duplicates['raw_facts']}"
        ),
        (
            f"metric_facts_before={payload['metric_facts_before']} "
            f"metric_facts_after={payload['metric_facts_after']}"
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


def _safe_target(destination: Path, storage_root: Path) -> Path:
    root = storage_root.resolve()
    target = destination.resolve()
    if not target.is_relative_to(root):
        raise ValueError("acceptance output must remain inside isolated storage")
    return target


def write_stable_json(
    payload: dict[str, Any], *, destination: Path, storage_root: Path
) -> None:
    target = _safe_target(destination, storage_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def write_stable_text(
    content: str, *, destination: Path, storage_root: Path
) -> None:
    target = _safe_target(destination, storage_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(target)


def load_stable_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"acceptance JSON must be an object: {path}")
    return payload


def _count(db: Session, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def build_runtime_snapshot(
    db: Session,
    *,
    run_id: str,
    captured_at: datetime,
    database_name: str,
    storage_root: Path,
    rate_guard_url: str,
    rate_guard_instance_id: str,
    rate_guard_metrics: dict[str, Any],
    source_path_proof: dict[str, Any],
) -> dict[str, Any]:
    financial_root = storage_root / "financial"
    files = sorted(
        path
        for path in financial_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    ) if financial_root.is_dir() else []
    return {
        "schema_version": 1,
        "run_id": run_id,
        "captured_at": captured_at.isoformat(),
        "database": database_name,
        "metric_facts": _count(db, MetricFact),
        "lineage_counts": {
            "issuer_identities": _count(db, SecIssuerIdentity),
            "submission_snapshots": _count(db, SecSubmissionSnapshot),
            "filings": _count(db, SecFinancialFiling),
            "artifacts": _count(db, SecFilingArtifact),
            "parse_runs": _count(db, SecFinancialParseRun),
            "raw_facts": _count(db, SecRawXbrlFact),
            "operations": _count(db, SecFinancialIngestionOperation),
            "finalized_operations": _count(db, SecFinancialLineageAvailability),
            "acquisition_failures": _count(db, SecFinancialAcquisitionFailure),
        },
        "retained_storage": {
            "file_count": len(files),
            "bytes": sum(path.stat().st_size for path in files),
        },
        "rate_guard": {
            "url": rate_guard_url.rstrip("/"),
            "instance_id": rate_guard_instance_id,
            "metrics": rate_guard_metrics,
        },
        "source_path_proof": source_path_proof,
    }


def _duplicate_excess(db: Session, statement) -> int:
    return sum(int(row[-1]) - 1 for row in db.execute(statement).all())


def build_case_database_audit(
    db: Session,
    *,
    expected_run_id: str,
    case: dict[str, Any],
    pass_one: dict[str, Any],
    pass_two: dict[str, Any],
    storage_root: Path,
) -> dict[str, Any]:
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
    case_id = str(case["case_id"])
    pass_one_operation = _operation_database_audit(
        db,
        report=pass_one,
        acceptance_pass=1,
        expected_run_id=expected_run_id,
        case_id=case_id,
        identity=identity,
        stock=stock,
    )
    pass_two_operation = _operation_database_audit(
        db,
        report=pass_two,
        acceptance_pass=2,
        expected_run_id=expected_run_id,
        case_id=case_id,
        identity=identity,
        stock=stock,
    )
    if pass_one_operation["operation_id"] == pass_two_operation["operation_id"]:
        raise ValueError(f"acceptance passes reuse one operation: {case_id}")

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
    covered_years = sorted(
        {
            int(item["report_date"][:4])
            for item in pass_one.get("selected_filings", [])
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
    expected_years = [int(value) for value in pass_one["expected_completed_fiscal_years"]]
    return {
        "case_id": case_id,
        "ticker": stock.ticker,
        "manifest_ticker": str(case["primary_listing"]["ticker"]),
        "company_name": stock.company_name,
        "stock_id": stock.id,
        "issuer_identity_id": identity.id,
        "identity_status": identity.status,
        "cik": cik,
        "filing_selection_as_of": pass_one["filing_selection_as_of"],
        "expected_completed_fiscal_years": expected_years,
        "covered_completed_fiscal_years": covered_years,
        "missing_completed_fiscal_years": sorted(
            set(expected_years) - set(covered_years), reverse=True
        ),
        "selected_forms": pass_one.get("selected_forms", []),
        "selected_accessions": [
            {
                "accession_no": item["accession_no"],
                "form_type": item["form_type"],
                "report_date": item.get("report_date"),
                "accepted_at": item["accepted_at"],
            }
            for item in pass_one.get("selected_filings", [])
        ],
        "pass_1": pass_one,
        "pass_2": pass_two,
        "idempotency_delta": build_idempotency_delta(
            pass_two_operation["database_created"]
        ),
        "operation_audits": {
            "pass_1": pass_one_operation,
            "pass_2": pass_two_operation,
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
        },
    }
