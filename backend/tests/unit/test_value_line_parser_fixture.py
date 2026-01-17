import json
from pathlib import Path

import pytest

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.normalization.scaler import Scaler


FIXTURE_PDF = Path("tests/fixtures/value_line/smith ao.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/ao_smith_v1.expected.json")


def load_expected_json() -> dict:
    with EXPECTED_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_fixture_pdf() -> dict[str, ValueLineV1Parser]:
    pages = PdfExtractor.extract_pages_with_words(FIXTURE_PDF)
    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_num: words for page_num, _, words in pages}
    parser = ValueLineV1Parser(text, page_words=page_words)
    return {res.field_key: res for res in parser.parse()}


def _dig(d: dict, path: list[str]):
    current = d
    for key in path:
        current = current[key]
    return current


def _normalize_value(result, value_type: str) -> float | None:
    if not result or not result.raw_value_text:
        return None
    normalized, _ = Scaler.normalize(result.raw_value_text, value_type)
    return normalized


def test_value_line_pdf_matches_expected_fixture():
    expected = load_expected_json()
    actual = parse_fixture_pdf()

    missing = []
    mismatched = []

    numeric_expectations = [
        ("recent_price", ["header_ratings", "recent_price", "normalized"], "number"),
        ("pe_ratio", ["header_ratings", "pe_ratio", "normalized"], "ratio"),
        ("pe_ratio_trailing", ["header_ratings", "pe_ratio_trailing", "normalized"], "ratio"),
        ("pe_ratio_median", ["header_ratings", "pe_ratio_median", "normalized"], "ratio"),
        ("relative_pe_ratio", ["header_ratings", "relative_pe_ratio", "normalized"], "ratio"),
        ("dividend_yield", ["header_ratings", "dividend_yield", "normalized"], "percent"),
        ("target_18m_low", ["target_price_ranges", "target_18m", "low", "normalized"], "number"),
        ("target_18m_high", ["target_price_ranges", "target_18m", "high", "normalized"], "number"),
        ("target_18m_mid", ["target_price_ranges", "target_18m", "midpoint", "normalized"], "number"),
        ("target_18m_upside_pct", ["target_price_ranges", "target_18m", "pct_to_mid", "normalized"], "percent"),
        (
            "long_term_projection_high_price",
            ["target_price_ranges", "long_term_projection", "high", "price_gain", "normalized_price"],
            "number",
        ),
        (
            "long_term_projection_high_price_gain_pct",
            [
                "target_price_ranges",
                "long_term_projection",
                "high",
                "price_gain",
                "price_gain_pct_normalized",
            ],
            "percent",
        ),
        (
            "long_term_projection_high_total_return_pct",
            ["target_price_ranges", "long_term_projection", "high", "annual_total_return", "normalized"],
            "percent",
        ),
        (
            "long_term_projection_low_price",
            ["target_price_ranges", "long_term_projection", "low", "price_gain", "normalized_price"],
            "number",
        ),
        (
            "long_term_projection_low_price_gain_pct",
            [
                "target_price_ranges",
                "long_term_projection",
                "low",
                "price_gain",
                "price_gain_pct_normalized",
            ],
            "percent",
        ),
        (
            "long_term_projection_low_total_return_pct",
            ["target_price_ranges", "long_term_projection", "low", "annual_total_return", "normalized"],
            "percent",
        ),
        ("total_debt", ["financial_snapshot_blocks", "capital_structure", "total_debt", "normalized"], "number"),
        (
            "debt_due_in_5_years",
            ["financial_snapshot_blocks", "capital_structure", "debt_due_in_5_years", "normalized"],
            "number",
        ),
        ("lt_debt", ["financial_snapshot_blocks", "capital_structure", "lt_debt", "normalized"], "number"),
        ("lt_interest", ["financial_snapshot_blocks", "capital_structure", "lt_interest", "normalized"], "number"),
        (
            "debt_percent_of_capital",
            ["financial_snapshot_blocks", "capital_structure", "debt_percent_of_capital", "normalized"],
            "percent",
        ),
        (
            "leases_uncapitalized_annual_rentals",
            ["financial_snapshot_blocks", "capital_structure", "leases_uncapitalized_annual_rentals", "normalized"],
            "number",
        ),
        ("pension_assets", ["financial_snapshot_blocks", "capital_structure", "pension_assets", "normalized"], "number"),
        ("pension_obligations", ["financial_snapshot_blocks", "capital_structure", "pension_obligations", "normalized"], "number"),
        (
            "common_stock_shares_outstanding",
            [
                "financial_snapshot_blocks",
                "capital_structure",
                "common_stock_shares_outstanding",
                "normalized",
            ],
            "number",
        ),
        (
            "market_cap",
            ["financial_snapshot_blocks", "capital_structure", "market_cap", "normalized"],
            "number",
        ),
    ]

    for field_key, path, value_type in numeric_expectations:
        result = actual.get(field_key)
        if not result:
            missing.append(f"{field_key} (expected at {'.'.join(path)})")
            continue

        expected_value = _dig(expected, path)
        actual_value = _normalize_value(result, value_type)

        if actual_value is None:
            mismatched.append(f"{field_key} (could not normalize '{result.raw_value_text}')")
            continue

        if actual_value != pytest.approx(expected_value):
            mismatched.append(
                f"{field_key} normalized {actual_value} != expected {expected_value} (path={'.'.join(path)})"
            )

    # Non-numeric expectations
    for field_key, path in (
        ("analyst_name", ["header_ratings", "analyst_name"]),
        ("report_date", ["header_ratings", "report_date"]),
    ):
        result = actual.get(field_key)
        if not result:
            missing.append(field_key)
            continue
        expected_value = _dig(expected, path)
        if result.raw_value_text != expected_value:
            mismatched.append(
                f"{field_key} raw '{result.raw_value_text}' != expected '{expected_value}'"
            )

    for field_key, path in (
        ("timeliness", ["header_ratings", "timeliness", "value"]),
        ("technical", ["header_ratings", "technical", "value"]),
    ):
        result = actual.get(field_key)
        if not result or not result.parsed_value_json:
            missing.append(field_key)
            continue
        expected_value = _dig(expected, path)
        actual_value = result.parsed_value_json.get("value")
        if actual_value != expected_value:
            mismatched.append(
                f"{field_key} value {actual_value} != expected {expected_value}"
            )

    # Target year range
    yr_result = actual.get("long_term_projection_year_range")
    if yr_result:
        expected_year_range = _dig(expected, ["target_price_ranges", "long_term_projection", "year_range"])
        if yr_result.raw_value_text != expected_year_range:
            mismatched.append(
                f"long_term_projection_year_range '{yr_result.raw_value_text}' != expected '{expected_year_range}'"
            )
    else:
        missing.append("long_term_projection_year_range")

    # Tables + structured blocks
    current_position = actual.get("current_position_usd_millions")
    expected_current_position = expected["financial_snapshot_blocks"]["current_position_usd_millions"]
    if not current_position or not current_position.parsed_value_json:
        missing.append("current_position_usd_millions")
    else:
        parsed_cp = current_position.parsed_value_json
        if parsed_cp.get("years") != expected_current_position["years"]:
            mismatched.append("current_position_usd_millions.years mismatch")
        for series in ("cash_assets", "receivables", "inventory_lifo"):
            if parsed_cp.get(series) != expected_current_position.get(series):
                mismatched.append(f"current_position_usd_millions.{series} mismatch")

    annual_rates = actual.get("annual_rates_of_change")
    expected_annual_rates = expected["financial_snapshot_blocks"]["annual_rates_of_change"]
    if not annual_rates or not annual_rates.parsed_value_json:
        missing.append("annual_rates_of_change")
    else:
        parsed_ar = annual_rates.parsed_value_json
        for metric in ("sales", "cash_flow_per_share", "earnings", "dividends", "book_value"):
            expected_metric = expected_annual_rates.get(metric)
            parsed_metric = parsed_ar.get(metric)
            if expected_metric and parsed_metric:
                for attr, expected_val in expected_metric.items():
                    parsed_val = parsed_metric.get(attr)
                    if parsed_val is None:
                        mismatched.append(
                            f"annual_rates_of_change.{metric}.{attr} missing parsed value"
                        )
                        continue
                    if parsed_val != pytest.approx(expected_val):
                        mismatched.append(
                            f"annual_rates_of_change.{metric}.{attr} {parsed_val} != expected {expected_val}"
                        )
            else:
                mismatched.append(f"annual_rates_of_change.{metric} missing parsed data")

    for field_key, expected_list_key in (
        ("quarterly_sales_usd_millions", "quarterly_sales_usd_millions"),
        ("earnings_per_share", "earnings_per_share"),
        ("quarterly_dividends_paid_per_share", "quarterly_dividends_paid_per_share"),
    ):
        result = actual.get(field_key)
        expected_list = expected["tables_time_series"][expected_list_key]
        if not result or not result.parsed_value_json:
            missing.append(field_key)
            continue
        parsed_list = result.parsed_value_json
        if len(parsed_list) != len(expected_list):
            mismatched.append(
                f"{field_key} length {len(parsed_list)} != expected {len(expected_list)}"
            )
        if parsed_list and expected_list:
            if parsed_list[0]["calendar_year"] != expected_list[0]["calendar_year"]:
                mismatched.append(
                    f"{field_key}[0].calendar_year {parsed_list[0]['calendar_year']} != expected {expected_list[0]['calendar_year']}"
                )
            expected_last_full = expected_list[-1].get("full_year")
            parsed_last_full = parsed_list[-1].get("full_year")
            if expected_last_full is not None:
                if parsed_last_full != pytest.approx(expected_last_full):
                    mismatched.append(
                        f"{field_key} last entry full_year {parsed_last_full} != expected {expected_last_full}"
                    )

    inst_result = actual.get("institutional_decisions")
    expected_inst = expected["institutional_decisions"]["quarterly"]
    if not inst_result or not inst_result.parsed_value_json:
        missing.append("institutional_decisions")
    else:
        parsed_inst = inst_result.parsed_value_json.get("quarterly")
        if parsed_inst != expected_inst:
            mismatched.append("institutional_decisions quarterly data mismatch")

    business_description = actual.get("business_description")
    expected_description = expected["narrative"]["business_description"]
    if not business_description or not business_description.raw_value_text:
        missing.append("business_description")
    else:
        def normalize_text(value: str) -> str:
            return "".join(ch for ch in value.lower() if ch.isalnum())

        if normalize_text(expected_description[:40]) not in normalize_text(business_description.raw_value_text):
            mismatched.append("business_description text does not contain expected snippet")

    if missing or mismatched:
        pytest.fail(
            "Value Line fixture parsing mismatch:\n"
            f" Missing fields: {missing!r}\n"
            f" Mismatched fields: {mismatched!r}"
        )
