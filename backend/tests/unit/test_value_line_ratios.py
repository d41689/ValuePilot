from datetime import date

from app.services.calculated_metrics.value_line_ratios import build_value_line_ratio_facts


def _fact(metric_key, value, period_end, *, fact_nature="actual", period_type="FY", fact_id=1):
    return {
        "id": fact_id,
        "metric_key": metric_key,
        "value_numeric": value,
        "value_json": {"fact_nature": fact_nature},
        "period_type": period_type,
        "period_end_date": period_end,
    }


def test_build_value_line_ratio_facts_calculates_standard_ratios_with_lineage():
    period_end = date(2024, 12, 31)
    facts = [
        _fact("is.net_income", 100.0, period_end, fact_id=1),
        _fact("bs.total_assets", 1000.0, period_end, fact_id=2),
        _fact("bs.current_assets", 300.0, period_end, fact_id=3),
        _fact("bs.current_liabilities", 150.0, period_end, fact_id=4),
        _fact("cap.long_term_debt", 250.0, period_end, fact_id=5),
        _fact("is.sales", 2000.0, period_end, fact_id=6),
        _fact("bs.total_equity", 500.0, period_end, fact_id=7),
    ]

    derived = build_value_line_ratio_facts(facts)
    by_key = {fact["metric_key"]: fact for fact in derived}

    assert by_key["returns.roa"]["value_numeric"] == 0.1
    assert by_key["liquidity.current_ratio"]["value_numeric"] == 2.0
    assert by_key["leverage.long_term_debt_to_assets"]["value_numeric"] == 0.25
    assert by_key["leverage.long_term_debt_to_capital"]["value_numeric"] == 250.0 / 750.0
    assert by_key["efficiency.asset_turnover"]["value_numeric"] == 2.0
    assert by_key["efficiency.capital_turnover"]["value_numeric"] == 2000.0 / 750.0
    assert by_key["efficiency.capital_turnover"]["value_json"]["method"] == "sales_to_total_capital"

    roa_json = by_key["returns.roa"]["value_json"]
    assert roa_json["status"] == "calculated"
    assert roa_json["method"] == "net_income_to_total_assets"
    assert roa_json["fact_nature"] == "actual"
    assert [item["fact_id"] for item in roa_json["inputs"]] == [1, 2]


def test_build_value_line_ratio_facts_marks_estimate_if_any_input_is_estimate():
    period_end = date(2025, 12, 31)
    facts = [
        _fact("is.net_income", 100.0, period_end, fact_nature="estimate", fact_id=1),
        _fact("bs.total_assets", 1000.0, period_end, fact_id=2),
    ]

    derived = build_value_line_ratio_facts(facts)
    roa = next(fact for fact in derived if fact["metric_key"] == "returns.roa")

    assert roa["value_json"]["fact_nature"] == "estimate"


def test_build_value_line_ratio_facts_calculates_insurance_premium_turnover():
    period_end = date(2024, 12, 31)
    facts = [
        _fact("is.net_premiums_earned", 500.0, period_end, fact_id=1),
        _fact("is.pc_premiums_earned", 700.0, period_end, fact_id=2),
        _fact("bs.total_assets", 1000.0, period_end, fact_id=3),
    ]

    derived = build_value_line_ratio_facts(facts)
    by_key = {fact["metric_key"]: fact for fact in derived}

    assert by_key["ins.premium_turnover"]["value_numeric"] == 0.5
    assert by_key["ins.premium_turnover"]["value_json"]["revenue_equivalent_metric"] == "is.net_premiums_earned"
    assert by_key["ins.premium_turnover"]["value_json"]["method"] == "insurance_premiums_to_assets"
