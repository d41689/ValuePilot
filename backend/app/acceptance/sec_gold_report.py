"""Stable Step C/Step D SEC gold-set acceptance report contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.models.sec_financials import SecFinancialIngestionOperation

if TYPE_CHECKING:
    from app.services.sec_financial_ingestion import FinancialIngestionReport


@dataclass(frozen=True)
class SecGoldSelectedFiling:
    accession_no: str
    form_type: str
    accepted_at: datetime


@dataclass(frozen=True)
class SecGoldAcceptanceCaseReport:
    schema_version: int
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


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
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
) -> SecGoldAcceptanceCaseReport:
    operation = db.get(
        SecFinancialIngestionOperation, ingestion_report.operation_id
    )
    if operation is None:
        raise ValueError("acceptance report requires its persisted operation")
    gaps = tuple(
        item
        for item in ingestion_report.failures
        if item.startswith("annual_coverage_gap:")
    )
    failures = tuple(
        item for item in ingestion_report.failures if item not in gaps
    )
    metric_facts_published = int(
        db.scalar(select(func.count()).select_from(MetricFact)) or 0
    )
    return SecGoldAcceptanceCaseReport(
        schema_version=1,
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
            )
            for item in ingestion_report.selected_filings
        ),
        typed_gaps=gaps,
        typed_failures=failures,
        filings_discovered=ingestion_report.filings_discovered,
        filings_created=ingestion_report.filings_created,
        artifacts_created=ingestion_report.artifacts_created,
        parse_runs_created=ingestion_report.parse_runs_created,
        raw_facts_created=ingestion_report.raw_facts_created,
        metric_facts_published=metric_facts_published,
    )


def render_human_case_summary(report: SecGoldAcceptanceCaseReport) -> str:
    selected_forms = sorted({item.form_type for item in report.selected_filings})
    lines = [
        f"acceptance_run_id={report.run_id} case={report.case_id} cik={report.cik}",
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
    return "\n".join(lines)


def write_case_report(
    report: SecGoldAcceptanceCaseReport,
    *,
    destination: Path,
    storage_root: Path,
) -> None:
    root = storage_root.resolve()
    target = destination.resolve()
    if not target.is_relative_to(root):
        raise ValueError("acceptance report must remain inside isolated storage")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        case_report_payload(report),
        indent=2,
        sort_keys=True,
    ) + "\n"
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(target)
