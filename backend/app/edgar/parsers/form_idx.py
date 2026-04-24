"""Parse EDGAR quarterly full-index form.idx files.

Format (fixed-width, header line + separator + data):
  Company Name                            Form Type   CIK         Date Filed  Filename
  ---------------------------------------- ---------- ----------- ---------- ---------
  BERKSHIRE HATHAWAY INC                  13F-HR      1067983     2024-02-14  edgar/data/...

Column offsets are read dynamically from the header line to be tolerant of
minor format variations across years.
"""
import io
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class FormIdxRecord:
    company_name: str
    form_type: str
    cik: str            # zero-padded 10-digit string
    filed_at: date
    filename: str       # e.g. edgar/data/1067983/0001067983-24-000006.txt

    @property
    def accession_no(self) -> str:
        """Extract dashed accession number from filename."""
        stem = self.filename.rsplit("/", 1)[-1].removesuffix(".txt")
        return stem

    @property
    def cik_padded(self) -> str:
        return self.cik.zfill(10)


_FORM_TYPES = frozenset({"13F-HR", "13F-HR/A"})

_HEADER_KEYS = ("Company Name", "Form Type", "CIK", "Date Filed", "Filename")


def parse_form_idx(content: bytes, form_types: frozenset[str] = _FORM_TYPES) -> list[FormIdxRecord]:
    """Parse raw form.idx bytes and return matching records."""
    text = content.decode("latin-1")
    records: list[FormIdxRecord] = []

    col: dict[str, int] = {}
    in_data = False

    for line in io.StringIO(text):
        line = line.rstrip("\n")

        # Detect column layout from header line
        if not col and all(k in line for k in _HEADER_KEYS):
            col["company"] = line.index("Company Name")
            col["form_type"] = line.index("Form Type")
            col["cik"] = line.index("CIK")
            col["date"] = line.index("Date Filed")
            col["filename"] = line.index("Filename")
            continue

        if line.lstrip().startswith("---"):
            in_data = True
            continue

        if not in_data or not line.strip() or not col:
            continue

        company_name = line[col["company"]:col["form_type"]].strip()
        form_type = line[col["form_type"]:col["cik"]].strip()
        cik_raw = line[col["cik"]:col["date"]].strip()
        date_str = line[col["date"]:col["filename"]].strip()
        filename = line[col["filename"]:].strip()

        if form_type not in form_types:
            continue
        if not cik_raw or not date_str:
            continue

        try:
            filed_at = date.fromisoformat(date_str)
        except ValueError:
            continue

        records.append(
            FormIdxRecord(
                company_name=company_name,
                form_type=form_type,
                cik=cik_raw.zfill(10),
                filed_at=filed_at,
                filename=filename,
            )
        )

    return records


def quarter_to_year_qtr(quarter: str) -> tuple[int, int]:
    """Parse '2025-Q1' → (2025, 1)."""
    parts = quarter.upper().split("-Q")
    if len(parts) != 2:
        raise ValueError(f"Expected YYYY-Qn format, got: {quarter!r}")
    return int(parts[0]), int(parts[1])


def form_idx_url(year: int, qtr: int) -> str:
    return f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{qtr}/form.idx"
