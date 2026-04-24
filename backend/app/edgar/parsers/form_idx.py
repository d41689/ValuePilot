"""Parse EDGAR quarterly full-index form.idx files.

EDGAR form.idx format (fixed-width, header + separator + data):
  Form Type   Company Name  ...  CIK         Date Filed  File Name
  ---...
  13F-HR      BERKSHIRE HATHAWAY INC  ...     1067983     2025-02-14  edgar/data/...

The header and data lines may have slightly different column alignment, so we
use regex to extract the well-known structured fields (date, CIK, filename)
rather than relying on header-based fixed offsets.
"""
import io
import re
from dataclasses import dataclass
from datetime import date


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

# Data line: form_type  company_name  cik  YYYY-MM-DD  edgar/data/...
# We anchor on the well-known structured fields: date and edgar/data path.
_DATA_RE = re.compile(
    r"^(\S[^\n]*?)\s{2,}(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(edgar/data/\S+)"
)


def parse_form_idx(content: bytes, form_types: frozenset[str] = _FORM_TYPES) -> list[FormIdxRecord]:
    """Parse raw form.idx bytes and return matching records."""
    text = content.decode("latin-1")
    records: list[FormIdxRecord] = []
    in_data = False

    for line in io.StringIO(text):
        line = line.rstrip()

        if line.lstrip().startswith("---"):
            in_data = True
            continue

        if not in_data or not line.strip():
            continue

        m = _DATA_RE.match(line)
        if not m:
            continue

        prefix = m.group(1)           # "form_type   company_name"
        cik_raw = m.group(2)
        date_str = m.group(3)
        filename = m.group(4)

        # Split prefix into form_type + company_name: form_type is the first
        # whitespace-free token, company_name is the rest.
        parts = prefix.split(None, 1)  # split on any whitespace, max 1 split
        if len(parts) < 1:
            continue
        form_type = parts[0]
        company_name = parts[1].strip() if len(parts) > 1 else ""

        if form_type not in form_types:
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
