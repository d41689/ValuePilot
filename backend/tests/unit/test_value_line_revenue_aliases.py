from copy import deepcopy
from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest

from app.services.mapping_spec import MappingSpec


SPEC = Path("docs/metric_facts_mapping_spec.yml")


def annual_page(field="revenues"):
    return {
        "annual_financials": {
            "meta": {
                "currency": "USD",
                "fiscal_year_end_month": 6,
                "actual_years": [2024],
                "estimate_years": [2025],
            },
            "per_unit_metrics": {field: {"2024": 38.59, "2025": 42.5}},
            "income_statement_usd_millions": {field: {"2024": 7088, "2025": 7600}},
        }
    }


@pytest.mark.parametrize("field", ["sales", "revenues"])
def test_annual_revenue_labels_keep_canonical_keys_periods_units_and_lineage(field):
    spec = MappingSpec.load(SPEC)
    facts, used, unmapped = spec.generate_facts(annual_page(field))
    by_slot = {(f["metric_key"], f["period_end_date"]): f for f in facts}
    assert len(facts) == len(by_slot) == 4
    for year, nature, revenue, per_share in [
        (2024, "actual", 7_088_000_000, 38.59),
        (2025, "estimate", 7_600_000_000, 42.5),
    ]:
        for key, expected in [("is.sales", revenue), ("per_share.sales", per_share)]:
            fact = by_slot[(key, date(year, 6, 30))]
            assert fact["value_numeric"] == Decimal(str(expected))
            assert fact["unit"] == "USD"
            assert fact["currency"] == "USD"
            assert fact["period_type"] == "FY"
            assert fact["value_json"]["fact_nature"] == nature
            assert fact["value_json"]["fiscal_year"] == year
            assert fact["value_json"]["source_mapping_version"] == spec.source_mapping_version
            assert fact["source_extraction_keys"] == ("tables_time_series",)
    assert any(f".{field}.2024" in path for path in used)
    assert not any(f".{field}." in path for path in unmapped)


def test_identical_aliases_collapse_deterministically_even_when_mappings_reordered():
    spec = MappingSpec.load(SPEC)
    page = annual_page()
    for section in ("per_unit_metrics", "income_statement_usd_millions"):
        page["annual_financials"][section]["sales"] = deepcopy(
            page["annual_financials"][section]["revenues"]
        )
    facts, _, _ = spec.generate_facts(page)
    spec.mappings = list(reversed(spec.mappings))
    reordered, _, _ = spec.generate_facts(page)
    by_slot = lambda rows: {(f["metric_key"], f["period_end_date"]): f for f in rows}
    assert len(facts) == len(reordered) == 4
    assert by_slot(facts) == by_slot(reordered)
    assert {f["value_json"]["mapping_id"] for f in facts} == {
        "is.sales.fy", "per_share.sales.fy"
    }


@pytest.mark.parametrize("section", ["per_unit_metrics", "income_statement_usd_millions"])
def test_conflicting_annual_aliases_fail_closed(section):
    page = annual_page()
    page["annual_financials"][section]["sales"] = {"2024": 999}
    with pytest.raises(ValueError, match="Conflicting Value Line semantic aliases"):
        MappingSpec.load(SPEC).generate_facts(page)


def test_distinct_alias_periods_do_not_conflict_or_expand_history():
    page = annual_page()
    page["annual_financials"]["per_unit_metrics"]["sales"] = {"2023": 34}
    facts, _, _ = MappingSpec.load(SPEC).generate_facts(page)
    assert len(facts) == 5
    assert {f["period_end_date"].year for f in facts} == {2023, 2024, 2025}


@pytest.mark.parametrize("invalid", ["not-a-number", float("nan"), float("inf"), "1e40"])
@pytest.mark.parametrize("field", ["sales", "revenues"])
def test_invalid_alias_value_cannot_be_silently_discarded_or_published(field, invalid):
    page = annual_page()
    page["annual_financials"]["per_unit_metrics"]["sales"] = {"2024": 38.59}
    page["annual_financials"]["per_unit_metrics"][field]["2024"] = invalid
    with pytest.raises(ValueError, match="Conflicting Value Line semantic aliases"):
        MappingSpec.load(SPEC).generate_facts(page)


@pytest.mark.parametrize("invalid,code", [
    ("not-a-number", "invalid_numeric"),
    (float("nan"), "nonfinite_numeric"),
    (float("inf"), "nonfinite_numeric"),
    ("1e40", "numeric_out_of_range"),
])
def test_invalid_standalone_revenue_keeps_raw_error_and_null_numeric(invalid, code):
    page = annual_page()
    page["annual_financials"]["income_statement_usd_millions"]["revenues"] = {"2024": invalid}
    facts, _, _ = MappingSpec.load(SPEC).generate_facts(page)
    fact = next(f for f in facts if f["metric_key"] == "is.sales")
    assert fact["value_numeric"] is None
    assert fact["value_json"]["raw_value"] == str(invalid)
    assert fact["value_json"]["normalization_error"] == code
    assert fact["source_extraction_keys"] == ("tables_time_series",)


def test_fractional_millions_are_exact_for_both_aliases():
    page = annual_page()
    page["annual_financials"]["income_statement_usd_millions"] = {
        "revenues": {"2024": 4204.1}, "sales": {"2024": 4204.1}
    }
    facts, _, _ = MappingSpec.load(SPEC).generate_facts(page)
    sales = [f for f in facts if f["metric_key"] == "is.sales"]
    assert len(sales) == 1
    assert isinstance(sales[0]["value_numeric"], Decimal)
    assert sales[0]["value_numeric"] == Decimal("4204100000")


def test_missing_alias_value_does_not_conflict_with_reported_value():
    page = annual_page()
    page["annual_financials"]["per_unit_metrics"]["sales"] = {"2024": None}
    facts, _, _ = MappingSpec.load(SPEC).generate_facts(page)
    assert len(facts) == 4


def test_registered_revenue_mapping_digest_matches_entire_resolved_policy():
    migration_path = Path("alembic/versions/20260912110000-value-line-revenue-aliases.py")
    module_spec = importlib.util.spec_from_file_location("revenue_alias_migration", migration_path)
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)
    resolved = MappingSpec.load(SPEC)
    assert migration.POLICY_ID == resolved.source_mapping_version
    assert migration.POLICY_SHA256 == resolved.mapping_policy_sha256
    assert migration.down_revision == "20260912100000"
    assert migration.POLICY_ID != migration.PREVIOUS_POLICY_ID
