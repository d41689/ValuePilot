import calendar
import re
from datetime import date, timedelta
from typing import Optional

# SEC 10-Q filing deadline for large accelerated filers is 40 days; use 45 as a safe threshold.
_QUARTERLY_REPORTING_LAG = timedelta(days=45)

# Two-digit years: >= pivot → 19xx, < pivot → 20xx. Fixed (not clock-relative)
# so historical parses stay reproducible. Value Line data realistically spans
# 1950–2049.
_CENTURY_PIVOT = 50

# Structural markers that only appear together on genuine Value Line pages.
# Used to guard against parsing arbitrary financial PDFs (e.g. a 10-K that
# happens to contain a ticker) as Value Line reports.
_VALUE_LINE_MARKERS = (
    re.compile(r"\bTIMELINESS\b", re.IGNORECASE),
    re.compile(r"\bSAFETY\b", re.IGNORECASE),
    re.compile(r"\bTECHNICAL\b", re.IGNORECASE),
    re.compile(r"VALUE\s*LINE", re.IGNORECASE),
    # RECENT price header, incl. glued text-layer variants ("RECENT109.10",
    # "RECEN1T062.19").
    re.compile(r"\bRECEN(?:\dT|T)\s*(?:PRICE\s*)?\d", re.IGNORECASE),
    # A >=6-year table-header run (annual financials table).
    re.compile(r"(?:(?:19|20)\d{2}\D{0,3}){6,}"),
)


def full_year(two_digit_year: int) -> int:
    """Expand a two-digit year using the fixed century pivot."""
    return (1900 if two_digit_year >= _CENTURY_PIVOT else 2000) + two_digit_year


def has_value_line_markers(text: Optional[str], *, minimum: int = 2) -> bool:
    """True when ``text`` shows at least ``minimum`` structural VL markers."""
    if not text:
        return False
    hits = sum(1 for pattern in _VALUE_LINE_MARKERS if pattern.search(text))
    return hits >= minimum


MONTH_LOOKUP = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

MONTH_NAME_LOOKUP = {
    "january": "Jan",
    "february": "Feb",
    "march": "Mar",
    "april": "Apr",
    "may": "May",
    "june": "Jun",
    "july": "Jul",
    "august": "Aug",
    "september": "Sep",
    "october": "Oct",
    "november": "Nov",
    "december": "Dec",
}


def parse_report_date_iso(text: str) -> Optional[str]:
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s*(\d{1,2})\s*,\s*(\d{4})",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    month = MONTH_NAME_LOOKUP[match.group(1).lower()]
    return f"{int(match.group(3)):04d}-{MONTH_LOOKUP[month]:02d}-{int(match.group(2)):02d}"


def normalize_month_token(token: str) -> Optional[str]:
    if not token:
        return None
    short = token.strip()[:3].title()
    return short if short in MONTH_LOOKUP else None


def extract_month_order(segment: str) -> list[str]:
    months: list[str] = []
    for match in re.findall(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*(?:\d{1,2}|Per)",
        segment or "",
        re.IGNORECASE,
    ):
        month = normalize_month_token(match)
        if month and month not in months:
            months.append(month)
        if len(months) == 4:
            break
    return months


def detect_quarter_month_order(text: str) -> Optional[list[str]]:
    start = re.search(r"\b(QUARTERLYSALES|QUARTERLYREVENUES|NETPREMIUMSEARNED)\b", text or "", re.IGNORECASE)
    if not start:
        return None
    segment = (text or "")[start.end() : start.end() + 400]
    months = extract_month_order(segment)
    return months if len(months) == 4 else None


def fiscal_year_end_month_from_order(month_order: Optional[list[str]]) -> Optional[int]:
    if not month_order:
        return None
    month = normalize_month_token(month_order[-1])
    return MONTH_LOOKUP.get(month) if month else None


def estimate_start_year(report_date_iso: Optional[str], fiscal_year_end_month: Optional[int]) -> Optional[int]:
    if not report_date_iso:
        return None
    report_date = date.fromisoformat(report_date_iso)
    if fiscal_year_end_month is None:
        return report_date.year - 1
    if fiscal_year_end_month == 12:
        return report_date.year - 1 if report_date.month <= 3 else report_date.year
    if report_date.month < fiscal_year_end_month:
        return report_date.year
    return report_date.year + 1


def is_estimated_year(
    year: Optional[int],
    report_date_iso: Optional[str],
    fiscal_year_end_month: Optional[int],
) -> bool:
    if year is None or report_date_iso is None:
        return False
    start_year = estimate_start_year(report_date_iso, fiscal_year_end_month)
    if start_year is None:
        return False
    return int(year) >= start_year


def split_actual_and_estimate_years(
    years: list[int],
    report_date_iso: Optional[str],
    fiscal_year_end_month: Optional[int],
) -> tuple[list[int], list[int]]:
    actual_years: list[int] = []
    estimate_years: list[int] = []
    for year in years:
        if is_estimated_year(year, report_date_iso, fiscal_year_end_month):
            estimate_years.append(year)
        else:
            actual_years.append(year)
    return actual_years, estimate_years


def quarter_fact_nature(
    period_end: Optional[str],
    report_date_iso: Optional[str],
) -> str:
    """Return 'actual' if the quarter's results would have been published by the report date.

    A quarter is considered published if its period-end date plus the typical SEC reporting
    lag (45 days for large accelerated filers) falls on or before the report date.
    """
    if not period_end or not report_date_iso:
        return "estimate"
    try:
        q_end = date.fromisoformat(period_end)
        r_date = date.fromisoformat(report_date_iso)
        return "actual" if q_end + _QUARTERLY_REPORTING_LAG <= r_date else "estimate"
    except ValueError:
        return "estimate"


def quarter_end_date_for_fiscal_year(
    year: Optional[int],
    quarter: Optional[int],
    month_order: Optional[list[str]],
) -> Optional[str]:
    if not year or not quarter:
        return None
    if not month_order or len(month_order) != 4:
        month = quarter * 3
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-{last_day:02d}"
    month_name = normalize_month_token(month_order[quarter - 1])
    fye_month = fiscal_year_end_month_from_order(month_order)
    if not month_name or fye_month is None:
        return None
    month = MONTH_LOOKUP[month_name]
    calendar_year = year if month <= fye_month else year - 1
    last_day = calendar.monthrange(calendar_year, month)[1]
    return f"{calendar_year:04d}-{month:02d}-{last_day:02d}"
