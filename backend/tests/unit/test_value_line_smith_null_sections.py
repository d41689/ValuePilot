import json
from pathlib import Path

import pytest

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser


FIXTURE_PDF = Path("tests/fixtures/value_line/smith ao.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/ao_smith_v1.expected.json")


def load_expected_json() -> dict:
    with EXPECTED_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_fixture_pdf() -> list:
    pages = PdfExtractor.extract_pages_with_words(FIXTURE_PDF)
    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_num: words for page_num, _, words in pages}
    parser = ValueLineV1Parser(text, page_words=page_words)
    return parser.parse()


def _first(results, field_key: str):
    return next((res for res in results if res.field_key == field_key), None)


def _assert_series(parsed: list, expected: list):
    assert len(parsed) == len(expected)
    for parsed_value, expected_value in zip(parsed, expected):
        if expected_value is None:
            assert parsed_value is None
        else:
            assert parsed_value == pytest.approx(expected_value)


def test_smith_current_position_block_populated():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "current_position_usd_millions")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_block = expected["financial_snapshot_blocks"]["current_position_usd_millions"]

    assert parsed.get("years") == expected_block["years"]
    for key in (
        "cash_assets",
        "receivables",
        "inventory_lifo",
        "other_current_assets",
        "current_assets_total",
        "accounts_payable",
        "debt_due",
        "other_current_liabilities",
        "current_liabilities_total",
    ):
        _assert_series(parsed.get(key, []), expected_block[key])


def test_smith_annual_rates_of_change_populated():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "annual_rates_of_change")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_block = expected["financial_snapshot_blocks"]["annual_rates_of_change"]

    for metric in ("sales", "cash_flow_per_share", "earnings", "dividends", "book_value"):
        parsed_metric = parsed.get(metric) or {}
        expected_metric = expected_block[metric]
        for horizon in ("past_10y", "past_5y", "est_to_2028_2030"):
            assert parsed_metric.get(horizon) == pytest.approx(expected_metric[horizon])


def test_smith_capital_structure_details_populated():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    expected_block = expected["financial_snapshot_blocks"]["capital_structure"]
    by_key = {res.field_key: res for res in results}

    assert by_key["leases_uncapitalized_annual_rentals"].raw_value_text is not None
    assert by_key["pension_assets"].raw_value_text is not None
    assert by_key["pension_obligations"].raw_value_text is not None
    assert by_key["market_cap"].raw_value_text is not None

    parsed_market_as_of = _first(results, "market_cap_as_of")
    assert parsed_market_as_of is not None
    assert parsed_market_as_of.raw_value_text == expected_block["market_cap_as_of"]

    parsed_pension_as_of = _first(results, "pension_assets_as_of")
    assert parsed_pension_as_of is not None
    assert parsed_pension_as_of.raw_value_text == expected_block["pension_assets_as_of"]

    parsed_shares = _first(results, "common_stock_shares_outstanding")
    assert parsed_shares is not None
    assert parsed_shares.parsed_value_json is not None
    assert parsed_shares.parsed_value_json.get("notes") == expected_block["common_stock_shares_outstanding"]["notes"]

    parsed_market = _first(results, "market_cap")
    assert parsed_market is not None
    assert parsed_market.parsed_value_json is not None
    assert parsed_market.parsed_value_json.get("notes") == expected_block["market_cap"]["notes"]


def test_smith_tables_time_series_populated():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "tables_time_series")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_tables = expected["tables_time_series"]

    parsed_annual = parsed.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030") or {}
    expected_annual = expected_tables["annual_financials_and_ratios_2015_2026_with_projection_2028_2030"]
    assert parsed_annual.get("years") == expected_annual["years"]
    assert parsed_annual.get("projection_year_range") == expected_annual["projection_year_range"]

    parsed_per_share = parsed_annual.get("per_share") or {}
    expected_per_share = expected_annual["per_share"]
    for key in ("sales_per_share_usd", "cash_flow_per_share_usd", "capital_spending_per_share_usd"):
        _assert_series(parsed_per_share.get(key, []), expected_per_share[key])

    parsed_income = parsed_annual.get("income_statement_usd_millions") or {}
    expected_income = expected_annual["income_statement_usd_millions"]
    for key in ("sales", "depreciation", "operating_margin_pct", "net_profit_margin_pct"):
        _assert_series(parsed_income.get(key, []), expected_income[key])

    parsed_balance = parsed_annual.get("balance_sheet_and_returns_usd_millions") or {}
    expected_balance = expected_annual["balance_sheet_and_returns_usd_millions"]
    for key in ("working_capital", "long_term_debt", "return_on_total_capital_pct"):
        _assert_series(parsed_balance.get(key, []), expected_balance[key])
