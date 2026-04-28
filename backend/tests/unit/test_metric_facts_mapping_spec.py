import json
from datetime import date
from pathlib import Path

import pytest

from app.services.mapping_spec import MappingSpec


FIXTURE_JSON = Path("tests/fixtures/value_line/axs_v1.parser.json")
LRN_FIXTURE_JSON = Path("tests/fixtures/value_line/lrn_v1.parser.json")
FNV_FIXTURE_JSON = Path("tests/fixtures/value_line/FNV_v1.parser.json")
SPEC_PATH = Path("docs/metric_facts_mapping_spec.yml")


def load_page_json() -> dict:
    with FIXTURE_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_lrn_page_json() -> dict:
    with LRN_FIXTURE_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_fnv_page_json() -> dict:
    with FNV_FIXTURE_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_mapping_spec_generates_core_facts():
    spec = MappingSpec.load(SPEC_PATH)
    page_json = load_page_json()

    facts, _, unmapped = spec.generate_facts(page_json)
    by_key = {(f["metric_key"], f.get("period_type"), f.get("period_end_date")): f for f in facts}

    eps_2024 = by_key.get(("per_share.eps", "FY", date(2024, 12, 31)))
    assert eps_2024 is not None
    assert eps_2024["value_numeric"] == pytest.approx(11.18)

    rate = by_key.get(("rates.premium_income.cagr_10y", "AS_OF", date(2026, 1, 9)))
    assert rate is not None
    assert rate["value_numeric"] == pytest.approx(0.065)

    strength = by_key.get(("quality.financial_strength", "AS_OF", date(2026, 1, 9)))
    assert strength is not None
    assert strength["value_numeric"] is None
    assert strength["value_text"] == "A"

    high_gain = by_key.get(("proj.long_term.high_price_gain", "PROJECTION_RANGE", date(2026, 1, 9)))
    assert high_gain is not None
    assert high_gain["value_numeric"] == pytest.approx(0.7)
    assert high_gain["unit"] == "ratio"

    low_gain = by_key.get(("proj.long_term.low_price_gain", "PROJECTION_RANGE", date(2026, 1, 9)))
    assert low_gain is not None
    assert low_gain["value_numeric"] == pytest.approx(0.25)
    assert low_gain["unit"] == "ratio"

    inst_buy = by_key.get(("ownership.institutional.to_buy", "Q", date(2025, 3, 31)))
    assert inst_buy is not None
    assert inst_buy["value_numeric"] == pytest.approx(232)
    assert inst_buy["unit"] == "count"

    inst_sell = by_key.get(("ownership.institutional.to_sell", "Q", date(2025, 6, 30)))
    assert inst_sell is not None
    assert inst_sell["value_numeric"] == pytest.approx(189)
    assert inst_sell["unit"] == "count"

    inst_holds = by_key.get(("ownership.institutional.holdings", "Q", date(2025, 9, 30)))
    assert inst_holds is not None
    assert inst_holds["value_numeric"] == pytest.approx(74_403_000)
    assert inst_holds["unit"] == "shares"

    assert ("rating.timeliness_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("rating.safety_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("rating.technical_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("analyst.commentary", "AS_OF", date(2026, 1, 9)) not in by_key
    assert ("company.business_description", "AS_OF", date(2026, 1, 9)) not in by_key

    assert any(path.startswith("historical_price_range") for path in unmapped)


def test_mapping_spec_uses_value_line_fiscal_year_end_month_for_fy_facts():
    spec = MappingSpec.load(SPEC_PATH)
    page_json = load_lrn_page_json()

    facts, _, _ = spec.generate_facts(page_json)
    by_key = {(f["metric_key"], f.get("period_type"), f.get("period_end_date")): f for f in facts}

    eps_2025 = by_key.get(("per_share.eps", "FY", date(2025, 6, 30)))
    assert eps_2025 is not None
    assert eps_2025["value_json"]["fact_nature"] == "actual"
    assert ("per_share.eps", "FY", date(2025, 12, 31)) not in by_key

    debt_2024 = by_key.get(("cap.long_term_debt", "FY", date(2024, 6, 30)))
    assert debt_2024 is not None
    assert debt_2024["value_numeric"] == pytest.approx(441_100_000.0)
    assert debt_2024["unit"] == "USD"


def test_mapping_spec_maps_value_line_return_on_total_capital_proxy():
    spec = MappingSpec.load(SPEC_PATH)
    page_json = load_fnv_page_json()

    facts, _, _ = spec.generate_facts(page_json)
    by_key = {(f["metric_key"], f.get("period_type"), f.get("period_end_date")): f for f in facts}

    rotc_2024 = by_key.get(("returns.total_capital", "FY", date(2024, 12, 31)))
    assert rotc_2024 is not None
    assert rotc_2024["value_numeric"] == pytest.approx(0.105)
    assert rotc_2024["unit"] == "ratio"
    assert rotc_2024["value_json"]["fact_nature"] == "actual"


def test_mapping_spec_maps_blank_value_line_long_term_debt_cells_as_zero():
    spec = MappingSpec.load(SPEC_PATH)
    page_json = load_fnv_page_json()

    facts, _, _ = spec.generate_facts(page_json)
    by_key = {(f["metric_key"], f.get("period_type"), f.get("period_end_date")): f for f in facts}

    debt_2024 = by_key.get(("cap.long_term_debt", "FY", date(2024, 12, 31)))
    assert debt_2024 is not None
    assert debt_2024["value_numeric"] == 0.0
    assert debt_2024["unit"] == "USD"
    assert debt_2024["value_json"]["fact_nature"] == "actual"
    assert debt_2024["value_json"]["method"] == "blank_value_line_debt_cell_as_zero"

    debt_2019 = by_key.get(("cap.long_term_debt", "FY", date(2019, 12, 31)))
    assert debt_2019 is not None
    assert debt_2019["value_numeric"] == pytest.approx(80_000_000.0)
    assert "method" not in debt_2019["value_json"]


def test_mapping_spec_maps_current_position_totals_for_current_ratio():
    spec = MappingSpec.load(SPEC_PATH)
    page_json = load_fnv_page_json()

    facts, _, _ = spec.generate_facts(page_json)
    by_key = {(f["metric_key"], f.get("period_type"), f.get("period_end_date")): f for f in facts}

    current_assets_2024 = by_key.get(("bs.current_assets", "FY", date(2024, 12, 31)))
    assert current_assets_2024 is not None
    assert current_assets_2024["value_numeric"] == pytest.approx(1_716_800_000.0)
    assert current_assets_2024["unit"] == "USD"
    assert current_assets_2024["value_json"]["fact_nature"] == "actual"

    current_liabilities_2024 = by_key.get(("bs.current_liabilities", "FY", date(2024, 12, 31)))
    assert current_liabilities_2024 is not None
    assert current_liabilities_2024["value_numeric"] == pytest.approx(67_500_000.0)
    assert current_liabilities_2024["unit"] == "USD"
    assert current_liabilities_2024["value_json"]["fact_nature"] == "actual"

    assert ("bs.current_assets", "FY", date(2025, 12, 31)) not in by_key
