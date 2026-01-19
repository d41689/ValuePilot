import json
from pathlib import Path

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.v1_value_line.page_json import build_value_line_page_json


FIXTURE_PDF = Path("tests/fixtures/value_line/axs.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/axs_v1.expected.json")


def load_expected_json() -> dict:
    with EXPECTED_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_page_json() -> dict:
    pages = PdfExtractor.extract_pages_with_words(FIXTURE_PDF)
    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_num: words for page_num, _, words in pages}
    parser = ValueLineV1Parser(text, page_words=page_words)
    return build_value_line_page_json(parser, page_number=1)


def test_axs_report_date_and_rating_events_are_time_aware():
    expected = load_expected_json()
    actual = build_page_json()

    assert actual["meta"]["report_date"] == expected["meta"]["report_date"]

    for key in ("timeliness", "safety", "technical"):
        assert actual["ratings"][key]["event"]["date"] == expected["ratings"][key]["event"]["date"]


def test_axs_institutional_decisions_have_period_end_dates():
    expected = load_expected_json()
    actual = build_page_json()

    expected_rows = expected["institutional_decisions"]["by_quarter"]
    actual_rows = actual["institutional_decisions"]["by_quarter"]
    assert len(actual_rows) == len(expected_rows)
    for exp, got in zip(expected_rows, actual_rows):
        assert got["period_end_date"] == exp["period_end_date"]


def test_axs_capital_structure_as_of_fields():
    expected = load_expected_json()
    actual = build_page_json()

    assert actual["capital_structure"]["as_of"] == expected["capital_structure"]["as_of"]
    assert (
        actual["capital_structure"]["common_stock_shares_outstanding"]["as_of"]
        == expected["capital_structure"]["common_stock_shares_outstanding"]["as_of"]
    )
    assert (
        actual["capital_structure"]["market_cap"]["as_of"]
        == expected["capital_structure"]["market_cap"]["as_of"]
    )


def test_axs_quarterly_time_series_include_period_end_dates():
    expected = load_expected_json()
    actual = build_page_json()

    exp_year = expected["net_premiums_earned"]["by_year"][0]
    got_year = actual["net_premiums_earned"]["by_year"][0]
    assert got_year["quarters"]["Q1"]["period_end"] == exp_year["quarters"]["Q1"]["period_end"]

    exp_eps_year = expected["earnings_per_share"]["by_year"][0]
    got_eps_year = actual["earnings_per_share"]["by_year"][0]
    assert got_eps_year["quarters"]["Q4"]["period_end"] == exp_eps_year["quarters"]["Q4"]["period_end"]

    exp_div_year = expected["quarterly_dividends_paid"]["by_year"][0]
    got_div_year = actual["quarterly_dividends_paid"]["by_year"][0]
    assert got_div_year["quarters"]["Q2"]["period_end"] == exp_div_year["quarters"]["Q2"]["period_end"]


def test_axs_annual_financials_years_and_total_return_shape():
    expected = load_expected_json()
    actual = build_page_json()

    assert (
        actual["annual_financials"]["meta"]["historical_years"]
        == expected["annual_financials"]["meta"]["historical_years"]
    )
    assert actual["annual_financials"]["meta"]["projection_year_range"] == expected["annual_financials"]["meta"][
        "projection_year_range"
    ]

    assert "price_semantics_and_returns" not in actual
    assert actual["total_return"]["as_of_date"] == expected["total_return"]["as_of_date"]
    assert actual["total_return"]["series"] == expected["total_return"]["series"]
