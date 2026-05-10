from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.edgar.fetcher import fetch_and_store, load_body
from app.edgar.parsers.primary_doc import PrimaryDocSummary, parse_primary_doc
from app.models.institutions import Filing13F, InstitutionManager, NoIndexExpectedDate


INGESTION_FORMS = {"13F-HR", "13F-HR/A", "13F-NT"}


@dataclass(frozen=True)
class PeriodRouting:
    period_of_report: date
    quarter_end_date: date | None
    report_quarter: str | None
    parse_status: str
    parse_warning: str | None = None
    parse_error: str | None = None


def ingest_accession_filing_detail(
    session: Session,
    payload: dict[str, Any],
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    accession = str(payload["accession_no"])
    manager_id = int(payload["manager_id"])
    form_type = str(payload.get("form_type") or "")
    if form_type not in INGESTION_FORMS:
        raise ValueError(f"Unsupported 13F filing form_type: {form_type}")

    manager = session.get(InstitutionManager, manager_id)
    if manager is None:
        raise ValueError(f"Manager not found: {manager_id}")

    filing_url = _filing_url(payload)
    raw_doc = fetch_and_store(
        session,
        source_system="edgar",
        document_type="filing_detail",
        source_url=filing_url,
        cik=str(payload.get("cik") or manager.cik or "").zfill(10),
        accession_no=accession,
        client=client,
    )
    summary = parse_primary_doc(load_body(raw_doc))
    accepted_at = summary.accepted_at
    filing_date = accepted_at.date() if accepted_at else _payload_date(payload)
    routing = route_period(
        summary.period_of_report,
        form_type=form_type,
        accepted_at=accepted_at,
        fallback_period=filing_date,
    )

    filing = _filing_for_accession(session, accession)
    if filing is None:
        filing = Filing13F(
            manager_id=manager_id,
            accession_no=accession,
            accession_number=accession,
            cik=str(payload.get("cik") or manager.cik or "").zfill(10),
            period_of_report=routing.period_of_report,
            filed_at=filing_date,
            filing_date=filing_date,
            form_type=form_type,
            version_rank=1,
            is_latest_for_period=False,
        )
        session.add(filing)

    filing.manager_id = manager_id
    filing.accession_no = accession
    filing.accession_number = accession
    filing.cik = str(payload.get("cik") or manager.cik or "").zfill(10)
    filing.form_type = form_type
    filing.period_of_report = routing.period_of_report
    filing.filed_at = filing_date
    filing.filing_date = filing_date
    filing.accepted_at = accepted_at
    filing.quarter_end_date = routing.quarter_end_date
    filing.report_quarter = routing.report_quarter
    filing.official_filing_deadline = (
        calculate_official_filing_deadline(session, routing.quarter_end_date)
        if routing.quarter_end_date
        else None
    )
    filing.raw_filing_url = filing_url
    filing.raw_primary_doc_id = raw_doc.id
    filing.form_spec_version = summary.form_spec_version
    filing.xml_schema_version = summary.xml_schema_version
    filing.report_type = _normalize_report_type(summary.report_type, form_type)
    filing.coverage_completeness = _coverage_completeness(filing.report_type)
    filing.coverage_type = _coverage_type(filing.report_type, form_type)
    filing.has_confidential_treatment = bool(summary.has_confidential_treatment)
    filing.confidential_treatment_status = "applied" if filing.has_confidential_treatment else "none"
    filing.reported_total_value_thousands = summary.table_value_total
    filing.holdings_count = summary.table_entry_total or 0
    filing.parse_status = routing.parse_status
    filing.parse_warning = routing.parse_warning
    filing.parse_error = routing.parse_error
    filing.other_managers_reporting = summary.other_managers_reporting or None
    filing.other_managers_included = summary.other_managers_included or None

    filing.is_amendment = bool(summary.is_amendment)
    filing.amendment_type_raw = summary.amendment_type
    
    # Optional amends_accession_no extraction logic could go here later.
    # For now, rely on edgar_ingestion or later enrichment.

    session.add(filing)
    session.flush()

    _apply_amendment_policy(session, filing)

    session.add(filing)
    session.commit()
    session.refresh(filing)
    return {
        "status": "succeeded" if routing.parse_status == "pending" else routing.parse_status,
        "filing_id": filing.id,
        "accession_number": filing.accession_number,
        "report_quarter": filing.report_quarter,
        "quarter_end_date": filing.quarter_end_date.isoformat() if filing.quarter_end_date else None,
        "parse_warning": filing.parse_warning,
        "parse_error": filing.parse_error,
        "raw_document_id": filing.raw_primary_doc_id,
    }


def route_period(
    raw_period: str | None,
    *,
    form_type: str,
    accepted_at: datetime | None,
    fallback_period: date,
) -> PeriodRouting:
    if not raw_period:
        return PeriodRouting(
            period_of_report=fallback_period,
            quarter_end_date=None,
            report_quarter=None,
            parse_status="needs_review",
            parse_warning="PERIOD_MISSING",
        )

    parsed = _parse_period_date(raw_period)
    if parsed is None:
        return PeriodRouting(
            period_of_report=fallback_period,
            quarter_end_date=None,
            report_quarter=None,
            parse_status="failed",
            parse_error="PERIOD_INVALID",
        )

    nearest = _nearest_quarter_end(parsed)
    delta = abs((parsed - nearest).days)
    if delta == 0:
        return _routed_success(nearest, accepted_at=accepted_at)

    if delta <= 2:
        if form_type in {"13F-HR", "13F-HR/A"} and _accepted_in_valid_window(accepted_at, nearest):
            routed = _routed_success(nearest, accepted_at=accepted_at)
            return PeriodRouting(
                period_of_report=routed.period_of_report,
                quarter_end_date=routed.quarter_end_date,
                report_quarter=routed.report_quarter,
                parse_status=routed.parse_status,
                parse_warning="PERIOD_WEEKEND_ADJUSTED",
            )
        return PeriodRouting(
            period_of_report=parsed,
            quarter_end_date=None,
            report_quarter=None,
            parse_status="needs_review",
            parse_warning="PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE",
        )

    return PeriodRouting(
        period_of_report=parsed,
        quarter_end_date=None,
        report_quarter=None,
        parse_status="needs_review",
        parse_warning="PERIOD_TOO_FAR_FROM_QUARTER_END",
    )


def calculate_official_filing_deadline(session: Session, quarter_end_date: date) -> date:
    candidate = quarter_end_date + timedelta(days=45)
    while _is_non_operational_edgar_day(session, candidate):
        candidate += timedelta(days=1)
    return candidate


def _filing_for_accession(session: Session, accession: str) -> Filing13F | None:
    return (
        session.query(Filing13F)
        .filter(or_(Filing13F.accession_number == accession, Filing13F.accession_no == accession))
        .one_or_none()
    )


def _filing_url(payload: dict[str, Any]) -> str:
    filename = payload.get("filename")
    if filename:
        filename = str(filename).lstrip("/")
        if filename.startswith("edgar/data/"):
            return f"https://www.sec.gov/Archives/{filename}"
        if filename.startswith("Archives/"):
            return f"https://www.sec.gov/{filename}"
        if filename.startswith("http://") or filename.startswith("https://"):
            return filename
    accession = str(payload["accession_no"])
    accession_raw = accession.replace("-", "")
    cik = str(payload.get("cik") or "").lstrip("0")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_raw}/{accession}.txt"


def _payload_date(payload: dict[str, Any]) -> date:
    sync_date = payload.get("sync_date")
    if sync_date:
        return date.fromisoformat(str(sync_date))
    return datetime.now(timezone.utc).date()


def _parse_period_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _nearest_quarter_end(value: date) -> date:
    candidates: list[date] = []
    for year in (value.year - 1, value.year, value.year + 1):
        candidates.extend(
            [
                date(year, 3, 31),
                date(year, 6, 30),
                date(year, 9, 30),
                date(year, 12, 31),
            ]
        )
    return min(candidates, key=lambda candidate: abs((value - candidate).days))


def _accepted_in_valid_window(accepted_at: datetime | None, quarter_end: date) -> bool:
    if accepted_at is None:
        return False
    accepted_date = accepted_at.date()
    return quarter_end <= accepted_date <= quarter_end + timedelta(days=180)


def _routed_success(quarter_end: date, *, accepted_at: datetime | None) -> PeriodRouting:
    if _accepted_more_than_three_quarters_from_period(accepted_at, quarter_end):
        return PeriodRouting(
            period_of_report=quarter_end,
            quarter_end_date=quarter_end,
            report_quarter=_report_quarter(quarter_end),
            parse_status="needs_review",
            parse_warning="PERIOD_SUSPICIOUSLY_STALE",
        )
    return PeriodRouting(
        period_of_report=quarter_end,
        quarter_end_date=quarter_end,
        report_quarter=_report_quarter(quarter_end),
        parse_status="pending",
    )


def _report_quarter(quarter_end: date) -> str:
    quarter_by_month = {3: 1, 6: 2, 9: 3, 12: 4}
    return f"{quarter_end.year}-Q{quarter_by_month[quarter_end.month]}"


def _accepted_more_than_three_quarters_from_period(accepted_at: datetime | None, quarter_end: date) -> bool:
    if accepted_at is None:
        return False
    return abs(_quarter_index(accepted_at.date()) - _quarter_index(quarter_end)) > 3


def _quarter_index(value: date) -> int:
    return value.year * 4 + ((value.month - 1) // 3)


def _is_non_operational_edgar_day(session: Session, value: date) -> bool:
    if value.weekday() >= 5:
        return True
    return NoIndexExpectedDate.active_for_date(session, value)


def _normalize_report_type(raw: str | None, form_type: str) -> str:
    text = (raw or "").strip().lower().replace("-", " ")
    if form_type == "13F-NT" or "notice" in text:
        return "notice_report"
    if "combination" in text:
        return "combination_report"
    if "holding" in text:
        return "holdings_report"
    return "holdings_report"


def _coverage_completeness(report_type: str | None) -> str:
    if report_type == "holdings_report":
        return "complete"
    if report_type == "combination_report":
        return "partial"
    return "unknown"


def _coverage_type(report_type: str | None, form_type: str) -> str:
    if form_type == "13F-NT" or report_type == "notice_report":
        return "notice_reported_elsewhere"
    if report_type == "combination_report":
        return "combination_partial"
    return "normal"


def _normalize_amendment_type(raw: str | None) -> str:
    if not raw:
        return "unknown"
    upper = raw.strip().upper()
    if upper == "RESTATEMENT":
        return "RESTATEMENT"
    if upper == "NEW HOLDINGS":
        return "NEW_HOLDINGS"
    if upper == "ADDITIONS, CORRECTIONS OR DELETIONS" or "ADDITIONS" in upper:
        return "ADDITIONS_CORRECTIONS_DELETIONS"
    return "unknown"


def _apply_amendment_policy(session: Session, filing: Filing13F) -> None:
    if filing.is_amendment:
        filing.amendment_type = _normalize_amendment_type(filing.amendment_type_raw)
        filing.is_active_for_manager_period = False
        if filing.amendment_type == "RESTATEMENT":
            filing.amendment_status = "pending_parse"
        else:
            filing.amendment_status = "amendments_pending"
        return

    # Original filing logic
    filing.is_amendment = False
    filing.amendment_type = None
    
    if not filing.quarter_end_date:
        filing.is_active_for_manager_period = False
        return

    originals = (
        session.query(Filing13F)
        .filter(Filing13F.manager_id == filing.manager_id)
        .filter(Filing13F.quarter_end_date == filing.quarter_end_date)
        .filter(Filing13F.is_amendment.is_(False))
        .all()
    )
    
    if not originals:
        filing.is_active_for_manager_period = True
        return

    sorted_originals = sorted(
        originals,
        key=lambda x: (x.accepted_at or datetime.min.replace(tzinfo=timezone.utc), x.accession_no),
        reverse=True,
    )

    latest = sorted_originals[0]
    tie = False
    if len(sorted_originals) > 1:
        second_latest = sorted_originals[1]
        t1 = latest.accepted_at or datetime.min.replace(tzinfo=timezone.utc)
        t2 = second_latest.accepted_at or datetime.min.replace(tzinfo=timezone.utc)
        if t1 == t2:
            tie = True

    for orig in originals:
        if tie:
            orig.is_active_for_manager_period = False
            orig.amendment_status = "amendments_pending"
            orig.amendment_sort_warning = True
        else:
            if orig.id == latest.id:
                orig.is_active_for_manager_period = True
                orig.amendment_sort_warning = False
                if orig.amendment_status == "amendments_pending" and orig.amendment_sort_warning:
                    orig.amendment_status = "no_amendments_seen"
            else:
                orig.is_active_for_manager_period = False
                orig.amendment_sort_warning = False
        session.add(orig)
