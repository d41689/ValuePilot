import calendar
import re
from datetime import date
from typing import Optional


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
