"""Historical-readiness tests for the Value Line v1 parser.

Covers the fixes from docs/tasks/2026-07-02_value-line-parser-historical-readiness.md:
F1 year sequences incl. 19xx, F2 century pivot, F3 report_date fallback chain,
F4 percent-row coercion consistency, F5 side-row fiscal dates + estimate split,
F8 Value Line structural-marker guard.

All tests drive the parser with raw text mimicking the PDF text layer (same
pattern as test_value_line_smith_parser.py).
"""

from pathlib import Path

import pytest

from app.ingestion.parsers.v1_value_line.evidence import parse_rating_event_notes
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.v1_value_line.semantics import (
    full_year,
    has_value_line_markers,
)

ANNUAL_KEY = "annual_financials_and_ratios_2015_2026_with_projection_2028_2030"

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "value_line"


# --- F2: century pivot -------------------------------------------------------


def test_full_year_pivot():
    assert full_year(97) == 1997
    assert full_year(50) == 1950
    assert full_year(49) == 2049
    assert full_year(24) == 2024
    assert full_year(0) == 2000


def test_iso_from_mdy_handles_pre_2000():
    assert ValueLineV1Parser._iso_from_mdy("3/15/97") == "1997-03-15"
    assert ValueLineV1Parser._iso_from_mdy("6/30/24") == "2024-06-30"


def test_iso_from_month_year_handles_pre_2000():
    assert ValueLineV1Parser._iso_from_month_year("12/98") == "1998-12-31"
    assert ValueLineV1Parser._iso_from_month_year("2/24") == "2024-02-29"


def test_rating_event_notes_handle_pre_2000():
    event = parse_rating_event_notes("Lowered 3/15/97")
    assert event is not None
    assert event["date"] == "1997-03-15"


# --- F1: year sequences ------------------------------------------------------


def test_year_sequence_recognizes_1990s_header():
    text = "SalespershA 1994 1995 1996 1997 1998 1999 2000 2001 BookValue"
    years = ValueLineV1Parser._find_year_sequence(text)
    assert years == [1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001]


def test_year_sequence_ignores_isolated_narrative_years():
    text = (
        "The company was founded in 1987 and expanded through 1992. "
        "It acquired a rival in 1995 before going public. Analysts noted 1998 "
        "was pivotal, as was 2003 and later 2010."
    )
    assert ValueLineV1Parser._find_year_sequence(text) == []


def test_year_sequence_filters_implausible_years():
    text = "1901 1902 1903 1904 1905 1906 1907"
    assert ValueLineV1Parser._find_year_sequence(text) == []


def test_year_sequence_handles_century_crossing_run():
    text = "1997 1998 1999 2000 2001 2002 2003"
    years = ValueLineV1Parser._find_year_sequence(text)
    assert years == [1997, 1998, 1999, 2000, 2001, 2002, 2003]


# --- F8: structural marker guard ---------------------------------------------


VL_MARKED_TEXT = """
SMITH (A.O.) RECENT 68.11 P/E 17.4 VALUE
NYSE-AOS PRICE RATIO LINE
TIMELINESS 3 Lowered1/2/26
SAFETY 2 Raised1/5/24
"""

GENERIC_10K_TEXT = """
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 10-K Annual Report
Registrant: Example Corp (NYSE: XYZ)
For the fiscal year ended December 31, 2025
"""


def test_markers_true_for_value_line_text():
    assert has_value_line_markers(VL_MARKED_TEXT) is True


def test_markers_false_for_generic_filing_text():
    assert has_value_line_markers(GENERIC_10K_TEXT) is False


@pytest.mark.parametrize(
    "pdf_path",
    sorted(FIXTURE_DIR.glob("*.pdf")),
    ids=lambda p: p.name,
)
def test_markers_pass_for_every_fixture_pdf(pdf_path):
    """The guard must never reject a genuine Value Line document."""
    from app.ingestion.pdf_extractor import PdfExtractor

    pages = PdfExtractor.extract_pages(pdf_path)
    assert any(has_value_line_markers(text) for _, text in pages), (
        f"No page of {pdf_path.name} passes has_value_line_markers"
    )


# --- F3: report_date fallback chain ------------------------------------------


MASTHEAD_ONLY_TEXT = """
ACME CORP. RECENT 42.50 P/E 12.1 VALUE
NYSE-ACM PRICE RATIO LINE
TIMELINESS 2 Raised3/10/98
SAFETY 3 Lowered1/9/98
January 9, 1998
BUSINESS: Acme Corp. makes widgets.
"""


def _report_date_results(parser: ValueLineV1Parser) -> list:
    return [res for res in parser.parse() if res.field_key == "report_date"]


def test_report_date_falls_back_to_masthead_date():
    results = _report_date_results(ValueLineV1Parser(MASTHEAD_ONLY_TEXT.strip()))
    assert len(results) == 1
    res = results[0]
    assert res.parsed_value_json["iso_date"] == "1998-01-09"
    assert res.confidence_score < 0.8  # degraded confidence for the fallback


def test_report_date_fallback_requires_markers():
    # A date alone, on a page with no Value Line structure, must not produce
    # a report_date (prevents garbage ingestion of non-VL PDFs).
    results = _report_date_results(
        ValueLineV1Parser(GENERIC_10K_TEXT.strip() + "\nFiled: March 3, 2026")
    )
    assert results == []


def test_report_date_prefers_analyst_line():
    text = MASTHEAD_ONLY_TEXT.strip() + "\nJaneQ.Analyst February 6, 1998"
    results = _report_date_results(ValueLineV1Parser(text))
    assert len(results) == 1
    res = results[0]
    assert res.parsed_value_json["iso_date"] == "1998-02-06"
    assert res.confidence_score == 0.8


# --- F4: percent-row coercion consistency ------------------------------------


INSURANCE_TABLE_TEXT = (
    "AXS CORP. RECENT 55.00 VALUE LINE TIMELINESS 3 SAFETY 2 "
    "2019 2020 2021 2022 2023 2024 "
    "SalesFigures 85.2% 83.1% .9 82.0% 81.5% 80.2% UnderwritingMargin "
    "AnalystY January 2, 2025"
)


def test_percent_row_divides_sub_one_percent_values():
    parser = ValueLineV1Parser(INSURANCE_TABLE_TEXT)
    tables = parser._parse_time_series_tables()
    assert tables is not None
    margin = tables[ANNUAL_KEY]["income_statement_usd_millions"]["underwriting_margin_pct"]
    # 0.9 (meaning 0.9%) must normalize to 0.009 — not stay 0.9 (100x error).
    assert margin[2] == pytest.approx(0.009)
    assert margin[0] == pytest.approx(0.852)


# --- F5: side-row fiscal dates + estimate split -------------------------------


def _side_row_text(*, report_line: str, month_header: str, years_and_values: str) -> str:
    return (
        "TESTCO RECENT 100.00 VALUE LINE TIMELINESS 3 SAFETY 2 "
        f"{years_and_values} NetProfit($mill) "
        f"QUARTERLYSALES($mill.) {month_header} Full Year "
        f"{report_line}"
    )


def test_side_row_uses_fiscal_year_end_month():
    # Fiscal year ends in September (month order Dec/Mar/Jun/Sep).
    text = _side_row_text(
        report_line="AnalystZ January 2, 2026",
        month_header="Dec.31 Mar.31 Jun.30 Sep.30",
        years_and_values="2020 2021 2022 2023 2024 2025 401.0 412.0 423.0 434.0 445.0 456.0",
    )
    results = [
        res
        for res in ValueLineV1Parser(text).parse()
        if res.field_key == "net_profit_usd_millions"
    ]
    assert results, "expected net profit side-row extractions"
    actuals = [r for r in results if not r.parsed_value_json["is_estimate"]]
    assert actuals
    latest_actual = max(actuals, key=lambda r: r.parsed_value_json["year"])
    # Sep FYE + January 2026 report: FY2025 (ended 2025-09-30) is published → actual.
    assert latest_actual.parsed_value_json["year"] == 2025
    assert latest_actual.parsed_value_json["period_end_date"] == "2025-09-30"


def test_side_row_marks_all_unpublished_years_as_estimates():
    # Calendar FYE, report dated January 2, 2026: FY2025 results are NOT yet
    # published, so both 2025 and 2026 columns are estimates; 2024 is the
    # latest actual. (The old logic wrongly treated 2025 as actual.)
    text = _side_row_text(
        report_line="AnalystZ January 2, 2026",
        month_header="Mar.31 Jun.30 Sep.30 Dec.31",
        years_and_values="2021 2022 2023 2024 2025 2026 301.0 312.0 323.0 334.0 345.0 356.0",
    )
    results = [
        res
        for res in ValueLineV1Parser(text).parse()
        if res.field_key == "net_profit_usd_millions"
    ]
    assert results
    by_year = {r.parsed_value_json["year"]: r.parsed_value_json for r in results}
    actual_years = sorted(y for y, p in by_year.items() if not p["is_estimate"])
    estimate_years = sorted(y for y, p in by_year.items() if p["is_estimate"])
    assert actual_years and max(actual_years) == 2024
    assert estimate_years == [2025, 2026]
    assert by_year[2024]["period_end_date"] == "2024-12-31"
