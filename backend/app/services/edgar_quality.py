"""Data quality checks for 13F holdings data.

Runs after ingestion to surface anomalies. All checks return structured
results so they can be surfaced in CLI output or logged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.thirteenf_quality_codes import VALUE_UNIT_SANITY

_CUSIP_RE = re.compile(r"^[A-Z0-9]{9}$")
_RECONCILE_THRESHOLD = 0.001  # 0.1%

# Module-local readability alias for the canonical constant in
# ``thirteenf_quality_codes`` (MVP4-09). The canonical name is the source
# of truth; this alias is kept because ``edgar_quality`` references the
# constant in three places and the short suffixed name reads naturally
# next to ``report.add(...)``.
VALUE_UNIT_SANITY_RULE_CODE = VALUE_UNIT_SANITY


@dataclass
class QualityIssue:
    check: str
    severity: str          # "error" | "warning" | "info"
    accession_no: str | None
    detail: str
    value: Any = None


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)

    def add(self, check: str, severity: str, detail: str,
            accession_no: str | None = None, value: Any = None) -> None:
        self.issues.append(QualityIssue(check, severity, accession_no, detail, value))

    @property
    def errors(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self) -> str:
        e = len(self.errors)
        w = len(self.warnings)
        info = len(self.issues) - e - w
        return f"{e} errors, {w} warnings, {info} info"


def run_quality_checks(db: Session, quarter: str | None = None) -> QualityReport:
    """Run all quality checks. If quarter given (e.g. '2025-Q1'), scope to that quarter."""
    report = QualityReport()

    _check_reconciliation(db, report, quarter)
    _check_cusip_format(db, report, quarter)
    _check_negative_values(db, report, quarter)
    _check_duplicate_fingerprints(db, report, quarter)
    _check_period_alignment(db, report, quarter)
    _check_parse_failures(db, report, quarter)
    _check_value_unit_sanity(db, report, quarter)

    return report


def persist_quality_report(
    db: Session,
    *,
    quarter: str | None,
    report: QualityReport,
    source_job_id: int | None = None,
    unavailable_reasons: list[str] | None = None,
) -> Any:
    """Persist a durable 13F quality report for admin readiness and audit."""
    from app.models.institutions import QualityReport13F

    error_count = len(report.errors)
    warning_count = len(report.warnings)
    info_count = len(report.issues) - error_count - warning_count
    status = "failed" if error_count else "warning" if warning_count else "passed"
    record = QualityReport13F(
        quarter=quarter,
        status=status,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        unavailable_reasons=unavailable_reasons or [],
        issues_json=[
            {
                "check": issue.check,
                "severity": issue.severity,
                "accession_no": issue.accession_no,
                "detail": issue.detail,
                "value": issue.value,
            }
            for issue in report.issues
        ],
        summary=report.summary(),
        source_job_id=source_job_id,
        checked_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    _persist_quality_findings(db, record, report)
    return record


def _persist_quality_findings(db: Session, record: Any, report: QualityReport) -> None:
    """Persist per-issue findings as durable validation records.

    The aggregate quality report remains the run-level summary. Finding rows are
    the audit asset used by MVP3 workflows to compare before/after validation.
    """
    from app.models.institutions import QualityFinding13F

    for issue in report.issues:
        value = issue.value if isinstance(issue.value, dict) else {}
        entity_type = value.get("entity_type") or ("filing" if issue.accession_no else None)
        entity_id = value.get("entity_id")
        manager_id = value.get("manager_id")
        accession_number = issue.accession_no or value.get("accession_number")

        existing = (
            db.query(QualityFinding13F)
            .filter(QualityFinding13F.status == "open")
            .filter(QualityFinding13F.rule_code == issue.check)
            .filter(QualityFinding13F.quarter.is_(None) if record.quarter is None else QualityFinding13F.quarter == record.quarter)
            .filter(
                QualityFinding13F.accession_number.is_(None)
                if accession_number is None
                else QualityFinding13F.accession_number == accession_number
            )
            .filter(QualityFinding13F.entity_type.is_(None) if entity_type is None else QualityFinding13F.entity_type == entity_type)
            .filter(QualityFinding13F.entity_id.is_(None) if entity_id is None else QualityFinding13F.entity_id == entity_id)
            .filter(QualityFinding13F.manager_id.is_(None) if manager_id is None else QualityFinding13F.manager_id == manager_id)
            .one_or_none()
        )
        if existing is None:
            db.add(
                QualityFinding13F(
                    validation_run_id=record.id,
                    rule_code=issue.check,
                    severity=issue.severity,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    quarter=record.quarter,
                    manager_id=manager_id,
                    accession_number=accession_number,
                    detail=issue.detail,
                    value_json=issue.value if isinstance(issue.value, dict) else {"value": issue.value},
                    status="open",
                    first_seen_at=record.checked_at,
                    last_seen_at=record.checked_at,
                )
            )
            continue

        existing.validation_run_id = record.id
        existing.severity = issue.severity
        existing.detail = issue.detail
        existing.value_json = issue.value if isinstance(issue.value, dict) else {"value": issue.value}
        existing.last_seen_at = record.checked_at
        db.add(existing)


def _quarter_filter(quarter: str | None) -> tuple[str, dict]:
    """Return a SQL fragment + params to filter by quarter, or empty string."""
    if not quarter:
        return "", {}
    import calendar as _cal
    parts = quarter.upper().split("-Q")
    if len(parts) != 2:
        raise ValueError(f"Expected YYYY-Qn, got {quarter!r}")
    year, qtr = int(parts[0]), int(parts[1])
    start_month = (qtr - 1) * 3 + 1
    end_month = qtr * 3
    last_day = _cal.monthrange(year, end_month)[1]
    return (
        "AND f.period_of_report BETWEEN :q_start AND :q_end",
        {
            "q_start": f"{year}-{start_month:02d}-01",
            "q_end": f"{year}-{end_month:02d}-{last_day:02d}",
        },
    )


def _check_reconciliation(db: Session, report: QualityReport, quarter: str | None) -> None:
    """Computed vs reported total value must match within 0.1%."""
    qf, qp = _quarter_filter(quarter)
    rows = db.execute(text(f"""
        SELECT f.accession_no,
               f.reported_total_value_thousands,
               f.computed_total_value_thousands
        FROM filings_13f f
        WHERE f.reported_total_value_thousands IS NOT NULL
          AND f.computed_total_value_thousands IS NOT NULL
          AND ABS(f.computed_total_value_thousands - f.reported_total_value_thousands)
              / GREATEST(f.reported_total_value_thousands, 1) > :threshold
        {qf}
    """), {"threshold": _RECONCILE_THRESHOLD, **qp}).fetchall()

    for row in rows:
        diff_pct = abs(row.computed_total_value_thousands - row.reported_total_value_thousands) \
                   / max(row.reported_total_value_thousands, 1) * 100
        report.add(
            "reconciliation",
            "warning",
            f"reported={row.reported_total_value_thousands:,} computed={row.computed_total_value_thousands:,} diff={diff_pct:.2f}%",
            accession_no=row.accession_no,
            value=diff_pct,
        )

    # A filing with holdings but no value total is invisible to the comparison
    # above — and to `compute_portfolio_weight`, which divides by
    # `computed_total_value_thousands or reported_total_value_thousands` and
    # returns None when both are NULL. An entire automated database once looked
    # like this, and this function reported "All filings within tolerance"
    # because it had compared exactly zero filings. Never again: a vacuous pass
    # must not be spelled like a clean one.
    missing = db.execute(text(f"""
        SELECT f.accession_no
        FROM filings_13f f
        WHERE COALESCE(f.computed_total_value_thousands,
                       f.reported_total_value_thousands) IS NULL
          AND EXISTS (
              SELECT 1 FROM holdings_13f h
              JOIN parse_runs pr ON pr.id = h.parse_run_id AND pr.is_current
              WHERE pr.accession_number = f.accession_no
          )
        {qf}
    """), qp).fetchall()

    for row in missing:
        report.add(
            "reconciliation",
            "warning",
            "filing has holdings but no value total — every portfolio weight is "
            "NULL, so Oracle's Lens distinctiveness scores 0 and conviction's "
            "position-importance is capped",
            accession_no=row.accession_no,
        )

    if not rows and not missing:
        report.add("reconciliation", "info",
                   f"All filings within {_RECONCILE_THRESHOLD*100:.1f}% tolerance")


def _check_cusip_format(db: Session, report: QualityReport, quarter: str | None) -> None:
    """CUSIP must be exactly 9 alphanumeric uppercase chars."""
    qf, qp = _quarter_filter(quarter)
    rows = db.execute(text(f"""
        SELECT DISTINCT h.cusip, COUNT(*) as cnt
        FROM holdings_13f h
        JOIN filings_13f f ON h.filing_id = f.id
        WHERE h.cusip !~ '^[A-Z0-9]{{9}}$'
        {qf}
        GROUP BY h.cusip
        ORDER BY cnt DESC
        LIMIT 20
    """), qp).fetchall()

    for row in rows:
        report.add(
            "cusip_format",
            "error",
            f"Invalid CUSIP {row.cusip!r} appears in {row.cnt} holdings",
            value={"cusip": row.cusip, "count": row.cnt},
        )

    if not rows:
        report.add("cusip_format", "info", "All CUSIPs pass format check")


def _check_negative_values(db: Session, report: QualityReport, quarter: str | None) -> None:
    """shares and value_thousands must be non-negative."""
    qf, qp = _quarter_filter(quarter)
    rows = db.execute(text(f"""
        SELECT h.id, f.accession_no, h.cusip, h.shares, h.value_thousands
        FROM holdings_13f h
        JOIN filings_13f f ON h.filing_id = f.id
        WHERE h.shares < 0 OR h.value_thousands < 0
        {qf}
        LIMIT 20
    """), qp).fetchall()

    for row in rows:
        report.add(
            "negative_values",
            "error",
            f"cusip={row.cusip} shares={row.shares} value={row.value_thousands}",
            accession_no=row.accession_no,
        )

    if not rows:
        report.add("negative_values", "info", "No negative shares or values found")


def _check_duplicate_fingerprints(db: Session, report: QualityReport, quarter: str | None) -> None:
    """Each (filing_id, row_fingerprint) must be unique — catches bugs in upsert logic."""
    qf, qp = _quarter_filter(quarter)
    rows = db.execute(text(f"""
        SELECT f.accession_no, h.row_fingerprint, COUNT(*) as cnt
        FROM holdings_13f h
        JOIN filings_13f f ON h.filing_id = f.id
        {("WHERE 1=1 " + qf) if qf else ""}
        GROUP BY f.accession_no, h.row_fingerprint
        HAVING COUNT(*) > 1
        LIMIT 10
    """), qp).fetchall()

    for row in rows:
        report.add(
            "duplicate_fingerprint",
            "error",
            f"fingerprint {row.row_fingerprint[:12]}… duplicated {row.cnt}× in {row.accession_no}",
            accession_no=row.accession_no,
        )

    if not rows:
        report.add("duplicate_fingerprint", "info", "No duplicate fingerprints found")


def _check_period_alignment(db: Session, report: QualityReport, quarter: str | None) -> None:
    """A 13F filed in quarter X reports the period ending in quarter X-1.

    13F-HR is filed within ~45 days of a quarter-end — i.e. in the *following*
    calendar quarter — so ``period_of_report`` should fall in the quarter
    *before* the filing quarter. (The old check compared against the filing
    quarter, which mis-fired on essentially every 13F.) Deviations split by
    direction:

    - *Earlier than X-1* — a late filing, or an amendment of an old period.
      The ingested data is correct and the lag is the filer's, so this is
      ``info``, not a ``warning`` that would block readiness.
    - *Later than X-1* — the period is in the filing quarter itself or in the
      future. A 13F cannot report a quarter that has not ended, so this is a
      genuine data anomaly and stays a ``warning``.
    """
    if not quarter:
        report.add("period_alignment", "info", "Skipped (no quarter specified)")
        return

    import calendar as _cal
    from datetime import date as _date

    parts = quarter.upper().split("-Q")
    year, qtr = int(parts[0]), int(parts[1])
    start_month = (qtr - 1) * 3 + 1
    end_month = qtr * 3
    last_day = _cal.monthrange(year, end_month)[1]

    # The quarter immediately before the filing quarter — the expected
    # period_of_report window for a 13F filed in this quarter.
    prev_year, prev_qtr = (year - 1, 4) if qtr == 1 else (year, qtr - 1)
    prev_start_month = (prev_qtr - 1) * 3 + 1
    prev_end_month = prev_qtr * 3
    prev_last_day = _cal.monthrange(prev_year, prev_end_month)[1]
    prev_end_date = _date(prev_year, prev_end_month, prev_last_day)

    rows = db.execute(text("""
        SELECT accession_no, period_of_report, filed_at
        FROM filings_13f
        WHERE period_of_report NOT BETWEEN :prev_start AND :prev_end
          AND filed_at BETWEEN :f_start AND :f_end
    """), {
        "prev_start": f"{prev_year}-{prev_start_month:02d}-01",
        "prev_end": f"{prev_year}-{prev_end_month:02d}-{prev_last_day:02d}",
        "f_start": f"{year}-{start_month:02d}-01",
        "f_end": f"{year}-{end_month:02d}-{last_day:02d}",
    }).fetchall()

    for row in rows:
        period = row.period_of_report
        if isinstance(period, str):
            period = _date.fromisoformat(period)
        if period > prev_end_date:
            # Period is in the filing quarter or the future — anomalous.
            report.add(
                "period_alignment",
                "warning",
                f"Filed in {quarter} but period_of_report={row.period_of_report} "
                f"is not before the filing quarter "
                f"(expected the {prev_year}-Q{prev_qtr} quarter-end)",
                accession_no=row.accession_no,
            )
        else:
            # Period older than X-1 — a late filing or an old-period amendment.
            report.add(
                "period_alignment",
                "info",
                f"Filed in {quarter} but period_of_report={row.period_of_report} "
                f"predates the expected {prev_year}-Q{prev_qtr} quarter-end "
                f"(late filing)",
                accession_no=row.accession_no,
            )

    if not rows:
        report.add("period_alignment", "info",
                   f"All filings in {quarter} report the expected {prev_year}-Q{prev_qtr} period")


def _check_parse_failures(db: Session, report: QualityReport, quarter: str | None) -> None:
    """Any raw_source_documents with parse_status='failed' need attention."""
    qf, qp = _quarter_filter(quarter)
    rows = db.execute(text(f"""
        SELECT r.accession_no, r.document_type, r.error_message
        FROM raw_source_documents r
        JOIN filings_13f f ON (f.raw_primary_doc_id = r.id OR f.raw_infotable_doc_id = r.id)
        WHERE r.parse_status = 'failed'
        {qf}
        LIMIT 20
    """), qp).fetchall()

    for row in rows:
        report.add(
            "parse_failure",
            "error",
            f"{row.document_type}: {(row.error_message or '')[:120]}",
            accession_no=row.accession_no,
        )

    if not rows:
        report.add("parse_failure", "info", "No parse failures found")


def _check_value_unit_sanity(db: Session, report: QualityReport, quarter: str | None) -> None:
    """Flag filing-level value jumps that often indicate 1000x value-unit errors."""
    qf, qp = _quarter_filter(quarter)
    rows = db.execute(text(f"""
        WITH ordered AS (
            SELECT
                f.id,
                f.manager_id,
                f.accession_no,
                f.period_of_report,
                f.reported_total_value_thousands,
                LAG(f.reported_total_value_thousands) OVER (
                    PARTITION BY f.manager_id
                    ORDER BY f.period_of_report
                ) AS previous_value
            FROM filings_13f f
            WHERE f.reported_total_value_thousands IS NOT NULL
              AND f.reported_total_value_thousands > 0
              AND f.manager_id IS NOT NULL
        )
        SELECT
            id,
            manager_id,
            accession_no,
            reported_total_value_thousands,
            previous_value,
            GREATEST(
                reported_total_value_thousands::numeric / GREATEST(previous_value, 1),
                previous_value::numeric / GREATEST(reported_total_value_thousands, 1)
            ) AS jump_ratio
        FROM ordered f
        WHERE previous_value IS NOT NULL
          AND previous_value > 0
          AND GREATEST(
              reported_total_value_thousands::numeric / GREATEST(previous_value, 1),
              previous_value::numeric / GREATEST(reported_total_value_thousands, 1)
          ) >= 1000
        {qf}
        ORDER BY jump_ratio DESC, accession_no ASC
        LIMIT 20
    """), qp).fetchall()

    for row in rows:
        ratio = float(row.jump_ratio)
        report.add(
            VALUE_UNIT_SANITY_RULE_CODE,
            "warning",
            (
                "Suspicious reported value jump "
                f"{ratio:.1f}x: previous={row.previous_value:,} current={row.reported_total_value_thousands:,}"
            ),
            accession_no=row.accession_no,
            value={
                "entity_type": "filing",
                "entity_id": row.id,
                "manager_id": row.manager_id,
                "previous_value_thousands": row.previous_value,
                "current_value_thousands": row.reported_total_value_thousands,
                "ratio": ratio,
            },
        )

    if not rows:
        report.add(VALUE_UNIT_SANITY_RULE_CODE, "info", "No suspicious 1000x reported value jumps found")
