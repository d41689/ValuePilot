import json
from pathlib import Path

import pytest

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.normalization.scaler import Scaler


FIXTURE_PDF = Path("tests/fixtures/value_line/axs.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/axs_v1.expected.json")


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


def _normalize_value(result, value_type: str) -> float | None:
    if not result or not result.raw_value_text:
        return None
    normalized, _ = Scaler.normalize(result.raw_value_text, value_type)
    return normalized


def test_axs_recent_price_extracted_from_header_words():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "recent_price")
    assert result is not None
    normalized = _normalize_value(result, "currency")
    expected_norm = expected["header"]["recent_price"]
    assert normalized == pytest.approx(expected_norm)


def test_axs_capital_structure_fields_extracted():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    as_of = _first(results, "capital_structure_as_of")
    assert as_of is not None
    assert as_of.raw_value_text == expected["capital_structure"]["as_of"]

    preferred_stock = _first(results, "preferred_stock")
    assert preferred_stock is not None
    preferred_stock_norm = _normalize_value(preferred_stock, "currency")
    expected_stock_norm = expected["capital_structure"]["preferred_stock"]["normalized"]
    assert preferred_stock_norm == pytest.approx(expected_stock_norm)

    preferred_div = _first(results, "preferred_dividend")
    assert preferred_div is not None
    preferred_div_norm = _normalize_value(preferred_div, "currency")
    expected_div_norm = expected["capital_structure"]["preferred_dividend"]["normalized"]
    assert preferred_div_norm == pytest.approx(expected_div_norm)

    shares = _first(results, "common_stock_shares_outstanding")
    assert shares is not None
    assert int(shares.raw_value_text) == expected["capital_structure"]["common_stock"]["shares_outstanding"][
        "normalized"
    ]


def test_axs_financial_position_block_extracted():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "financial_position_usd_millions")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_fp = expected["financial_position"]

    assert parsed.get("years") == expected_fp["years"]
    assert parsed.get("assets", {}).get("bonds") == expected_fp["assets"]["bonds"]
    assert parsed.get("assets", {}).get("total_assets") == expected_fp["assets"]["total_assets"]
    assert parsed.get("liabilities", {}).get("unearned_premiums") == expected_fp["liabilities"]["unearned_premiums"]
    assert parsed.get("liabilities", {}).get("total_liabilities") == expected_fp["liabilities"]["total_liabilities"]


def test_axs_price_semantics_total_return_extracted():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "price_semantics_and_returns")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_total = expected["total_return"]

    assert parsed.get("value_line_total_return_as_of") == expected_total["as_of_date"]
    parsed_returns = parsed.get("total_return", {})
    expected_returns = {
        (row["name"], row["window_years"]): row["value_pct"] / 100.0
        for row in expected_total["series"]
    }

    for horizon, window in (("1y", 1), ("3y", 3), ("5y", 5)):
        assert parsed_returns.get("stock", {}).get(horizon) == pytest.approx(
            expected_returns[("this_stock", window)]
        )
        assert parsed_returns.get("index", {}).get(horizon) == pytest.approx(
            expected_returns[("vl_arithmetic_index", window)]
        )


def test_axs_tables_time_series_extracted():
    results = parse_fixture_pdf()
    expected = load_expected_json()

    result = _first(results, "tables_time_series")
    assert result is not None
    parsed = result.parsed_value_json or {}
    expected_prices = expected["historical_price_range"]

    parsed_prices = parsed.get("price_history_high_low", {})
    expected_highs = [row["high"] for row in expected_prices]
    expected_lows = [row["low"] for row in expected_prices]
    assert parsed_prices.get("high") == expected_highs
    assert parsed_prices.get("low") == expected_lows

    parsed_annual = parsed.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030", {})
    expected_annual = expected["annual_financials"]
    years = expected_annual["meta"]["historical_years"]
    assert parsed_annual.get("years") == years
    assert parsed_annual.get("projection_year_range") == expected_annual["meta"]["projection_year_range"]
    parsed_eps = parsed_annual.get("per_share", {}).get("earnings_per_share_usd") or []
    expected_eps_map = expected_annual["per_share_metrics"]["earnings_per_share_usd"]
    expected_eps = [expected_eps_map[str(year)] for year in years]
    assert len(parsed_eps) == len(expected_eps)
    if parsed_eps and expected_eps:
        assert parsed_eps[0] == pytest.approx(expected_eps[0])
        assert parsed_eps[-1] == pytest.approx(expected_eps[-1])
