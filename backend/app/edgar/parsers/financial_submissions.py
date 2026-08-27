from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from typing import Any, Iterable
from zoneinfo import ZoneInfo


APPROVED_FINANCIAL_FORMS = frozenset(
    {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "6-K"}
)
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class FinancialIssuerSubmission:
    cik: str
    name: str
    fiscal_year_end: str | None


@dataclass(frozen=True)
class DiscoveredFinancialFiling:
    accession_no: str
    form_type: str
    filed_on: date
    report_date: date | None
    accepted_at: datetime
    primary_document: str
    primary_doc_description: str | None
    submissions_source_url: str
    discovery_payload_sha256: str


@dataclass(frozen=True)
class FinancialSubmissionsResult:
    issuer: FinancialIssuerSubmission
    filings: tuple[DiscoveredFinancialFiling, ...]
    historical_submission_files: tuple[str, ...]


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _parse_acceptance(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    try:
        if len(raw) == 14 and raw.isdigit():
            return datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=ET)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ET)
    except ValueError:
        return None


def _filings_from_arrays(
    arrays: dict[str, Any],
    *,
    source_url: str,
    payload_hash: str,
    approved_forms: Iterable[str],
) -> tuple[DiscoveredFinancialFiling, ...]:
    allowed = set(approved_forms)
    required = {
        key: arrays.get(key) if isinstance(arrays.get(key), list) else []
        for key in (
            "accessionNumber",
            "filingDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
        )
    }
    optional = {
        key: arrays.get(key) if isinstance(arrays.get(key), list) else []
        for key in ("reportDate", "primaryDocDescription")
    }
    count = max((len(values) for values in required.values()), default=0)
    found: list[DiscoveredFinancialFiling] = []
    for index in range(count):
        if any(index >= len(values) for values in required.values()):
            continue
        form_type = str(required["form"][index] or "").strip().upper()
        if form_type not in allowed:
            continue
        accession = str(required["accessionNumber"][index] or "").strip()
        filed_on = _parse_date(required["filingDate"][index])
        accepted_at = _parse_acceptance(required["acceptanceDateTime"][index])
        primary_document = str(required["primaryDocument"][index] or "").strip()
        if not accession or filed_on is None or accepted_at is None or not primary_document:
            continue
        report_value = optional["reportDate"][index] if index < len(optional["reportDate"]) else None
        description = (
            optional["primaryDocDescription"][index]
            if index < len(optional["primaryDocDescription"])
            else None
        )
        found.append(
            DiscoveredFinancialFiling(
                accession_no=accession,
                form_type=form_type,
                filed_on=filed_on,
                report_date=_parse_date(report_value),
                accepted_at=accepted_at,
                primary_document=primary_document,
                primary_doc_description=str(description).strip() if description else None,
                submissions_source_url=source_url,
                discovery_payload_sha256=payload_hash,
            )
        )
    return tuple(found)


def parse_financial_submissions(
    content: bytes,
    *,
    source_url: str,
    approved_forms: Iterable[str] = APPROVED_FINANCIAL_FORMS,
) -> FinancialSubmissionsResult:
    data = json.loads(content)
    payload_hash = hashlib.sha256(content).hexdigest()
    cik = str(data.get("cik") or "").zfill(10)
    recent = data.get("filings", {}).get("recent", {})
    historical = data.get("filings", {}).get("files", [])
    historical_files = tuple(
        str(item.get("name"))
        for item in historical
        if isinstance(item, dict) and str(item.get("name") or "").startswith("CIK")
    )
    return FinancialSubmissionsResult(
        issuer=FinancialIssuerSubmission(
            cik=cik,
            name=str(data.get("name") or ""),
            fiscal_year_end=str(data.get("fiscalYearEnd") or "") or None,
        ),
        filings=_filings_from_arrays(
            recent,
            source_url=source_url,
            payload_hash=payload_hash,
            approved_forms=approved_forms,
        ),
        historical_submission_files=historical_files,
    )


def parse_historical_financial_submissions(
    content: bytes,
    *,
    source_url: str,
    approved_forms: Iterable[str] = APPROVED_FINANCIAL_FORMS,
) -> tuple[DiscoveredFinancialFiling, ...]:
    data = json.loads(content)
    return _filings_from_arrays(
        data,
        source_url=source_url,
        payload_hash=hashlib.sha256(content).hexdigest(),
        approved_forms=approved_forms,
    )
