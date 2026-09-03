"""Stable FT-04 SEC gold-set acceptance report contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.models.sec_financials import (
    SecFinancialAccessionAttempt,
    SecFinancialFiling,
    SecFinancialIngestionOperation,
    SecFinancialLineageAvailability,
    SecSubmissionSnapshot,
)
from app.models.sec_publication import (
    SecMetricPublication,
    SecMetricPublicationAvailability,
    SecMetricPublicationRun,
)
from app.acceptance.sec_gold_publication import (
    AcceptancePublicationExecution,
    build_metric_outcome_matrix,
    load_metric_gap_evidence,
    validate_migration_owned_acceptance_authorities,
)
from app.acceptance.sec_gold_storage import secure_atomic_write_bytes

if TYPE_CHECKING:
    from app.services.sec_financial_ingestion import FinancialIngestionReport


@dataclass(frozen=True)
class SecGoldSelectedFiling:
    accession_no: str
    form_type: str
    accepted_at: datetime
    report_date: date | None = None


@dataclass(frozen=True)
class SecGoldAcceptanceCaseReport:
    schema_version: int
    acceptance_pass: int
    run_id: str
    case_id: str
    stock_id: int
    cik: str
    filing_selection_as_of: datetime
    operation_id: str
    operation_attempted_at: datetime
    evidence_finalized_at: datetime
    evidence_available_at: datetime
    expected_completed_fiscal_years: tuple[int, ...]
    selected_filings: tuple[SecGoldSelectedFiling, ...]
    typed_gaps: tuple[str, ...]
    typed_failures: tuple[str, ...]
    filings_discovered: int
    filings_created: int
    artifacts_created: int
    parse_runs_created: int
    raw_facts_created: int
    metric_facts_published: int
    submission_snapshots_created: int = 0
    next_history_cursor: str | None = None
    acquisition_operations: tuple[dict[str, Any], ...] = ()
    publication_run_id: str | None = None
    publication_replayed: bool = False
    publication_requested_cutoff: datetime | None = None
    publication_attempted_at: datetime | None = None
    publication_finalized_at: datetime | None = None
    publication_available_at: datetime | None = None
    publication_decision_ids: tuple[int, ...] = ()
    publication_run_source_ids: tuple[int, ...] = ()
    publication_source_parse_run_ids: tuple[int, ...] = ()
    publication_source_accessions: tuple[str, ...] = ()
    mapping_version_id: str | None = None
    method_policy_version_id: str | None = None
    amendment_policy_id: str | None = None
    metric_outcomes: dict[str, Any] = field(default_factory=dict)
    lineage_counts: dict[str, int] = field(default_factory=dict)
    persistent_delta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        timestamps = (
            self.filing_selection_as_of,
            self.operation_attempted_at,
            self.evidence_finalized_at,
            self.evidence_available_at,
        )
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("acceptance report timestamps must be timezone-aware")
        if self.evidence_finalized_at < self.operation_attempted_at:
            raise ValueError("finalization cannot precede operation attempt")
        if self.evidence_available_at < self.operation_attempted_at:
            raise ValueError("availability cannot precede operation attempt")
        if self.evidence_available_at < self.evidence_finalized_at:
            raise ValueError("availability cannot precede finalization")
        if self.metric_facts_published < 0:
            raise ValueError("metric_facts publication count cannot be negative")
        if self.acceptance_pass not in {1, 2}:
            raise ValueError("acceptance pass must be 1 or 2")
        publication_timestamps = (
            self.publication_requested_cutoff,
            self.publication_attempted_at,
            self.publication_finalized_at,
            self.publication_available_at,
        )
        if any(value is not None and value.tzinfo is None for value in publication_timestamps):
            raise ValueError("publication timestamps must be timezone-aware")
        if self.publication_run_id is not None and any(
            value is None for value in publication_timestamps
        ):
            raise ValueError("publication identity requires every PIT timestamp")


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def case_report_payload(report: SecGoldAcceptanceCaseReport) -> dict[str, Any]:
    payload = _json_value(asdict(report))
    payload["selected_forms"] = sorted(
        {item.form_type for item in report.selected_filings}
    )
    return payload


def build_case_report(
    db: Session,
    *,
    run_id: str,
    case_id: str,
    filing_selection_as_of: datetime,
    expected_completed_fiscal_years: tuple[int, ...],
    ingestion_report: "FinancialIngestionReport",
    evidence_available_at: datetime,
    acceptance_pass: int = 1,
    ingestion_reports: tuple["FinancialIngestionReport", ...] | None = None,
    publication: AcceptancePublicationExecution | None = None,
    persistent_delta: dict[str, Any] | None = None,
) -> SecGoldAcceptanceCaseReport:
    reports = ingestion_reports or (ingestion_report,)
    operation = db.get(SecFinancialIngestionOperation, ingestion_report.operation_id)
    if operation is None:
        raise ValueError("acceptance report requires its persisted operation")
    all_failures = tuple(
        failure for report in reports for failure in report.failures
    )
    gaps = tuple(
        item for item in all_failures if item.startswith("annual_coverage_gap:")
    )
    failures = tuple(item for item in all_failures if item not in gaps)
    operation_ids = tuple(item.operation_id for item in reports)
    acquisition_operations: list[dict[str, Any]] = []
    if publication is not None or ingestion_reports is not None:
        for item in reports:
            persisted = db.get(SecFinancialIngestionOperation, item.operation_id)
            if persisted is None:
                raise ValueError("acceptance report requires every persisted operation")
            availability = db.execute(
                select(SecFinancialLineageAvailability).where(
                    SecFinancialLineageAvailability.operation_id == item.operation_id
                )
            ).scalar_one_or_none()
            if availability is None:
                raise ValueError("acceptance report requires finalized acquisition lineage")
            acquisition_operations.append(
                {
                    "operation_id": item.operation_id,
                    "attempted_at": persisted.attempted_at,
                    "finalized_at": availability.available_at,
                    "available_at": availability.available_at,
                    "accessions": [
                        str(accession)
                        for accession in db.scalars(
                            select(SecFinancialAccessionAttempt.accession_no)
                            .outerjoin(
                                SecFinancialFiling,
                                SecFinancialFiling.id
                                == SecFinancialAccessionAttempt.filing_id,
                            )
                            .where(
                                SecFinancialAccessionAttempt.operation_id
                                == item.operation_id
                            )
                            .order_by(
                                SecFinancialFiling.accepted_at.desc().nulls_last(),
                                SecFinancialAccessionAttempt.accession_no.desc(),
                            )
                        )
                    ],
                    "filings_discovered": item.filings_discovered,
                    "filings_created": item.filings_created,
                    "submission_snapshots_created": int(
                        db.scalar(
                            select(func.count())
                            .select_from(SecSubmissionSnapshot)
                            .where(
                                SecSubmissionSnapshot.operation_id
                                == item.operation_id
                            )
                        )
                        or 0
                    ),
                    "artifacts_created": item.artifacts_created,
                    "parse_runs_created": item.parse_runs_created,
                    "raw_facts_created": item.raw_facts_created,
                }
            )
    metric_facts_published = int(
        db.scalar(
            select(func.count()).select_from(MetricFact).where(
                MetricFact.stock_id == ingestion_report.stock_id,
                MetricFact.source_type == "sec",
            )
            if publication is not None
            else select(func.count()).select_from(MetricFact)
        )
        or 0
    )
    submission_snapshots_created = sum(
        int(
            db.scalar(
                select(func.count()).select_from(SecSubmissionSnapshot).where(
                    SecSubmissionSnapshot.operation_id == operation_id
                )
            )
            or 0
        )
        for operation_id in operation_ids
    )
    publication_fields: dict[str, Any] = {}
    metric_outcomes: dict[str, Any] = {}
    lineage_counts: dict[str, int] = {}
    if publication is not None:
        metric_keys = validate_migration_owned_acceptance_authorities(db)
        run = db.execute(
            select(
                SecMetricPublicationRun.created_at,
                SecMetricPublicationRun.published_count,
                SecMetricPublicationRun.unresolved_count,
                SecMetricPublicationRun.rejected_count,
            ).where(SecMetricPublicationRun.id == publication.receipt.run_id)
        ).one_or_none()
        availability = db.get(
            SecMetricPublicationAvailability, publication.receipt.run_id
        )
        if run is None or availability is None:
            raise ValueError("acceptance publication is not finalized DB authority")
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
                ).where(
                    SecMetricPublication.publication_run_id
                    == publication.receipt.run_id
                ).order_by(SecMetricPublication.decision_ordinal)
            ).mappings()
        )
        metric_outcomes = build_metric_outcome_matrix(
            expected_fiscal_years=expected_completed_fiscal_years,
            metric_keys=metric_keys,
            decisions=decisions,
            gap_evidence=load_metric_gap_evidence(
                db,
                publication_run_id=publication.receipt.run_id,
                expected_fiscal_years=expected_completed_fiscal_years,
                metric_keys=metric_keys,
            ),
        )
        run_sources = list(
            db.execute(
                text(
                    """SELECT id,parse_run_id FROM sec_metric_publication_run_sources
                       WHERE publication_run_id=:run ORDER BY source_ordinal"""
                ),
                {"run": publication.receipt.run_id},
            ).mappings()
        )
        publication_fields = {
            "publication_run_id": publication.receipt.run_id,
            "publication_replayed": publication.receipt.replayed,
            "publication_requested_cutoff": publication.requested_cutoff,
            "publication_attempted_at": run.created_at,
            "publication_finalized_at": availability.available_at,
            "publication_available_at": availability.available_at,
            "publication_decision_ids": tuple(int(item["id"]) for item in decisions),
            "publication_run_source_ids": tuple(
                int(item["id"]) for item in run_sources
            ),
            "publication_source_parse_run_ids": tuple(
                int(item["parse_run_id"]) for item in run_sources
            ),
            "publication_source_accessions": tuple(
                source.accession_no for source in publication.sources
            ),
            "mapping_version_id": publication.mapping_version_id,
            "method_policy_version_id": publication.method_policy_version_id,
            "amendment_policy_id": publication.amendment_policy_id,
        }
        publication_input_count = int(
            db.execute(
                text(
                    """SELECT count(*) FROM sec_metric_publication_inputs i
                       JOIN sec_metric_publications p ON p.id=i.publication_id
                       WHERE p.publication_run_id=:run"""
                ),
                {"run": publication.receipt.run_id},
            ).scalar_one()
        )
        unresolved_input_count = int(
            db.execute(
                text(
                    """SELECT count(*) FROM sec_metric_publication_unresolved_inputs i
                       JOIN sec_metric_publications p ON p.id=i.publication_id
                       WHERE p.publication_run_id=:run"""
                ),
                {"run": publication.receipt.run_id},
            ).scalar_one()
        )
        parse_ids = [source.parse_run_id for source in publication.sources]
        lineage_counts = {
            "raw_facts": int(
                db.execute(
                    text("SELECT count(*) FROM sec_raw_xbrl_facts WHERE parse_run_id=ANY(:ids)"),
                    {"ids": parse_ids},
                ).scalar_one()
            ),
            "statement_report_references": int(
                db.execute(
                    text("SELECT count(*) FROM sec_statement_report_references WHERE parse_run_id=ANY(:ids)"),
                    {"ids": parse_ids},
                ).scalar_one()
            ),
            "statement_occurrences": int(
                db.execute(
                    text("SELECT count(*) FROM sec_statement_occurrence_evidence WHERE parse_run_id=ANY(:ids)"),
                    {"ids": parse_ids},
                ).scalar_one()
            ),
            "statement_authorities": int(
                db.execute(
                    text("SELECT count(*) FROM sec_statement_fact_authorities WHERE parse_run_id=ANY(:ids)"),
                    {"ids": parse_ids},
                ).scalar_one()
            ),
            "numeric_normalizations": int(
                db.execute(
                    text(
                        """SELECT count(*) FROM sec_raw_numeric_normalizations n
                           JOIN sec_raw_xbrl_facts raw ON raw.id=n.raw_fact_id
                           WHERE raw.parse_run_id=ANY(:ids)
                             AND n.mapping_version_id=:mapping"""
                    ),
                    {"ids": parse_ids, "mapping": publication.mapping_version_id},
                ).scalar_one()
            ),
            "publication_runs": 1,
            "publication_sources": len(publication.sources),
            "publication_decisions": len(decisions),
            "publication_inputs": publication_input_count,
            "publication_unresolved_inputs": unresolved_input_count,
            "published_decisions": int(run.published_count),
            "unresolved_decisions": int(run.unresolved_count),
            "publication_audits": int(run.rejected_count),
            "publication_availabilities": 1,
            "metric_facts": metric_facts_published,
        }
    return SecGoldAcceptanceCaseReport(
        schema_version=2 if publication is not None else 1,
        acceptance_pass=acceptance_pass,
        run_id=run_id,
        case_id=case_id,
        stock_id=ingestion_report.stock_id,
        cik=ingestion_report.cik,
        filing_selection_as_of=filing_selection_as_of,
        operation_id=ingestion_report.operation_id,
        operation_attempted_at=operation.attempted_at,
        evidence_finalized_at=evidence_available_at,
        evidence_available_at=evidence_available_at,
        expected_completed_fiscal_years=expected_completed_fiscal_years,
        selected_filings=tuple(
            SecGoldSelectedFiling(
                accession_no=item.accession_no,
                form_type=item.form_type,
                accepted_at=item.accepted_at,
                report_date=item.report_date,
            )
            for item in {
                selected.accession_no: selected
                for report in reports
                for selected in report.selected_filings
            }.values()
        ),
        typed_gaps=gaps,
        typed_failures=failures,
        filings_discovered=sum(item.filings_discovered for item in reports),
        filings_created=sum(item.filings_created for item in reports),
        artifacts_created=sum(item.artifacts_created for item in reports),
        parse_runs_created=sum(item.parse_runs_created for item in reports),
        raw_facts_created=sum(item.raw_facts_created for item in reports),
        metric_facts_published=metric_facts_published,
        submission_snapshots_created=submission_snapshots_created,
        next_history_cursor=reports[-1].next_history_cursor,
        acquisition_operations=tuple(acquisition_operations),
        metric_outcomes=metric_outcomes,
        lineage_counts=lineage_counts,
        persistent_delta=persistent_delta or {},
        **publication_fields,
    )


def render_human_case_summary(report: SecGoldAcceptanceCaseReport) -> str:
    selected_forms = sorted({item.form_type for item in report.selected_filings})
    lines = [
        f"acceptance_run_id={report.run_id} case={report.case_id} cik={report.cik}",
        f"acceptance_pass={report.acceptance_pass}",
        f"next_history_cursor={report.next_history_cursor or 'exhausted'}",
        f"filing_selection_as_of={report.filing_selection_as_of.isoformat()}",
        f"operation_attempted_at={report.operation_attempted_at.isoformat()}",
        f"evidence_finalized_at={report.evidence_finalized_at.isoformat()}",
        f"evidence_available_at={report.evidence_available_at.isoformat()}",
        "expected_completed_fiscal_years="
        + ",".join(str(year) for year in report.expected_completed_fiscal_years),
        "selected_forms=" + (",".join(selected_forms) if selected_forms else "none"),
        (
            f"selected_filings={len(report.selected_filings)} "
            f"artifacts_created={report.artifacts_created} "
            f"parse_runs_created={report.parse_runs_created} "
            f"raw_facts_created={report.raw_facts_created} "
            f"metric_facts_published={report.metric_facts_published}"
        ),
    ]
    lines.extend(f"typed_gap={item}" for item in report.typed_gaps)
    lines.extend(f"typed_failure={item}" for item in report.typed_failures)
    if report.publication_run_id is not None:
        outcomes = report.metric_outcomes
        lines.extend(
            [
                f"publication_run_id={report.publication_run_id} replayed={str(report.publication_replayed).lower()}",
                f"publication_requested_cutoff={report.publication_requested_cutoff.isoformat()}",
                f"publication_attempted_at={report.publication_attempted_at.isoformat()}",
                f"publication_finalized_at={report.publication_finalized_at.isoformat()}",
                f"publication_available_at={report.publication_available_at.isoformat()}",
                f"mapping_version={report.mapping_version_id} method_policy_version={report.method_policy_version_id} amendment_policy={report.amendment_policy_id}",
                (
                    f"issuer_year_metric_outcomes={outcomes['issuer_year_metric_denominator']} "
                    f"published={outcomes['published_count']} "
                    f"typed_gaps={outcomes['typed_gap_count']} "
                    f"missing={outcomes['missing_count']}"
                ),
                "pass_persistent_delta="
                + json.dumps(report.persistent_delta, sort_keys=True),
            ]
        )
    return "\n".join(lines)


def write_case_report(
    report: SecGoldAcceptanceCaseReport,
    *,
    destination: Path,
    storage_root: Path,
) -> None:
    encoded = json.dumps(
        case_report_payload(report),
        indent=2,
        sort_keys=True,
    ) + "\n"
    secure_atomic_write_bytes(
        storage_root=storage_root,
        destination=destination,
        content=encoded.encode(),
    )
