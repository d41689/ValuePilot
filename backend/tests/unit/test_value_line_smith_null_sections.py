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
    expected_block = expected["current_position"]
    expected_periods = expected_block["periods"]
    expected_years = [
        period["period_end_date"] if "/" in period["label"] else period["label"]
        for period in expected_periods
    ]

    assert parsed.get("years") == expected_years
    expected_series = {
        "cash_assets": [period["assets"]["cash_assets"] for period in expected_periods],
        "receivables": [period["assets"]["receivables"] for period in expected_periods],
        "inventory_lifo": [period["assets"]["inventory_lifo"] for period in expected_periods],
        "other_current_assets": [period["assets"]["other_current_assets"] for period in expected_periods],
        "current_assets_total": [period["assets"]["total_current_assets"] for period in expected_periods],
        "accounts_payable": [period["liabilities"]["accounts_payable"] for period in expected_periods],
        "debt_due": [period["liabilities"]["debt_due"] for period in expected_periods],
        "other_current_liabilities": [
            period["liabilities"]["other_current_liabilities"] for period in expected_periods
        ],
        "current_liabilities_total": [
            period["liabilities"]["total_current_liabilities"] for period in expected_periods
        ],
    }
    for key, series in expected_series.items():
        _assert_series(parsed.get(key, []), series)


def test_smith_annual_rates_of_change_populated():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "annual_rates_of_change")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_metrics = {
        metric["metric_key"]: metric for metric in expected["annual_rates"]["metrics"]
    }
    key_map = {
        "sales": "sales",
        "cash_flow_per_share": "cash_flow",
        "earnings": "earnings",
        "dividends": "dividends",
        "book_value": "book_value",
    }

    def to_ratio(value: float | None) -> float | None:
        return None if value is None else value / 100.0

    for metric, expected_key in key_map.items():
        parsed_metric = parsed.get(metric) or {}
        expected_metric = expected_metrics[expected_key]
        for horizon_key, expected_value in (
            ("past_10y", expected_metric["past_10y_cagr_pct"]),
            ("past_5y", expected_metric["past_5y_cagr_pct"]),
            ("est_to_2028_2030", expected_metric["estimated_cagr_pct"]["value"]),
        ):
            expected_ratio = to_ratio(expected_value)
            if expected_ratio is None:
                assert parsed_metric.get(horizon_key) is None
            else:
                assert parsed_metric.get(horizon_key) == pytest.approx(expected_ratio)


def test_smith_capital_structure_details_populated():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    expected_block = expected["capital_structure"]
    by_key = {res.field_key: res for res in results}

    assert by_key["leases_uncapitalized_annual_rentals"].raw_value_text is not None
    assert by_key["pension_assets"].raw_value_text is not None
    assert by_key["pension_obligations"].raw_value_text is not None
    assert by_key["market_cap"].raw_value_text is not None

    parsed_market_as_of = _first(results, "market_cap_as_of")
    if parsed_market_as_of is not None:
        assert parsed_market_as_of.raw_value_text == expected_block["common_stock"]["as_of"]

    parsed_pension_as_of = _first(results, "pension_assets_as_of")
    assert parsed_pension_as_of is not None
    assert parsed_pension_as_of.raw_value_text == expected_block["pension_assets"]["as_of"]

    parsed_shares = _first(results, "common_stock_shares_outstanding")
    assert parsed_shares is not None
    assert parsed_shares.parsed_value_json is not None
    parsed_meta = parsed_shares.parsed_value_json
    assert parsed_meta.get("as_of") == expected_block["common_stock"]["as_of"]
    assert parsed_meta.get("class_a_shares") == expected_block["common_stock"]["class_a_shares"]["display"]
    assert parsed_meta.get("class_a_voting_power_multiple") == expected_block["common_stock"]["class_a_voting_power"][
        "multiple"
    ]
    assert parsed_meta.get("class_a_voting_power_notes") == expected_block["common_stock"]["class_a_voting_power"][
        "notes"
    ]

    parsed_market = _first(results, "market_cap")
    assert parsed_market is not None
    assert parsed_market.parsed_value_json is not None
    assert parsed_market.parsed_value_json.get("notes") == expected_block["market_cap"]["market_cap_category"]


def test_smith_tables_time_series_populated():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "tables_time_series")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_annual = expected["annual_financials"]

    parsed_annual = parsed.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030") or {}
    years = expected_annual["meta"]["historical_years"]
    assert parsed_annual.get("years") == years
    assert parsed_annual.get("projection_year_range") == expected_annual["meta"]["projection_year_range"]

    parsed_per_share = parsed_annual.get("per_share") or {}
    expected_per_share = expected_annual["per_unit_metrics"]
    per_share_map = {
        "sales_per_share_usd": "sales",
        "cash_flow_per_share_usd": "cash_flow",
        "capital_spending_per_share_usd": "capital_spending",
    }
    for parsed_key, expected_key in per_share_map.items():
        expected_series = [expected_per_share[expected_key][str(year)] for year in years]
        _assert_series(parsed_per_share.get(parsed_key, []), expected_series)

    parsed_income = parsed_annual.get("income_statement_usd_millions") or {}
    expected_income = expected_annual["income_statement_usd_millions"]
    for key in ("sales", "depreciation", "operating_margin_pct", "net_profit"):
        expected_series = [expected_income[key][str(year)] for year in years]
        _assert_series(parsed_income.get(key, []), expected_series)

    parsed_valuation = parsed_annual.get("valuation") or {}
    expected_valuation = expected_annual["valuation_metrics"]
    for key in ("avg_annual_pe_ratio", "relative_pe_ratio", "avg_annual_dividend_yield_pct"):
        expected_series = [expected_valuation[key].get(str(year)) for year in years]
        _assert_series(parsed_valuation.get(key, []), expected_series)
