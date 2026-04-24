"""Parse EDGAR submissions JSON for CIK lookup and recent 13F filing metadata.

Endpoint: https://data.sec.gov/submissions/CIK{cik_padded}.json
"""
import json
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class SubmissionsInfo:
    cik: str
    name: str
    sic: Optional[str]
    state_of_inc: Optional[str]


@dataclass
class SubmissionsFiling:
    accession_no: str
    form_type: str
    filed_at: date
    report_date: Optional[date]


def parse_submissions(content: bytes) -> tuple[SubmissionsInfo, list[SubmissionsFiling]]:
    """Parse CIK submissions JSON → entity info + list of 13F filings."""
    data = json.loads(content)

    info = SubmissionsInfo(
        cik=str(data.get("cik", "")).zfill(10),
        name=data.get("name", ""),
        sic=data.get("sic"),
        state_of_inc=data.get("stateOfIncorporation"),
    )

    filings: list[SubmissionsFiling] = []
    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return info, filings

    accessions = recent.get("accessionNumber", [])
    form_types = recent.get("form", [])
    filed_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])

    for i, form_type in enumerate(form_types):
        if form_type not in ("13F-HR", "13F-HR/A"):
            continue
        accession = accessions[i].replace("-", "")  # raw format without dashes
        # Normalize to dashed format
        accession_dashed = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
        filed_str = filed_dates[i] if i < len(filed_dates) else ""
        report_str = report_dates[i] if i < len(report_dates) else ""

        try:
            filed_at = date.fromisoformat(filed_str)
        except (ValueError, TypeError):
            continue

        report_date: Optional[date] = None
        try:
            if report_str:
                report_date = date.fromisoformat(report_str)
        except (ValueError, TypeError):
            pass

        filings.append(
            SubmissionsFiling(
                accession_no=accession_dashed,
                form_type=form_type,
                filed_at=filed_at,
                report_date=report_date,
            )
        )

    return info, filings


def submissions_url(cik_padded: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
