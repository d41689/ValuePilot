from datetime import date

from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.calculated_metrics.piotroski_f_score import (
    PiotroskiFScoreCalculator,
    build_piotroski_f_score_facts,
)


def _fact(metric_key, value, period_end, *, fact_nature="actual", fact_id=1, source_type="parsed", period_type="FY"):
    return {
        "id": fact_id,
        "metric_key": metric_key,
        "value_numeric": value,
        "value_json": {"fact_nature": fact_nature},
        "period_type": period_type,
        "period_end_date": period_end,
        "source_type": source_type,
        "is_current": True,
    }


def _complete_standard_facts():
    y0 = date(2023, 12, 31)
    y1 = date(2024, 12, 31)
    return [
        _fact("returns.roa", 0.08, y0, fact_id=1),
        _fact("returns.roa", 0.10, y1, fact_id=2),
        _fact("is.operating_cash_flow", 150.0, y1, fact_id=3),
        _fact("is.net_income", 100.0, y1, fact_id=4),
        _fact("leverage.long_term_debt_to_assets", 0.30, y0, fact_id=5),
        _fact("leverage.long_term_debt_to_assets", 0.20, y1, fact_id=6),
        _fact("liquidity.current_ratio", 1.5, y0, fact_id=7),
        _fact("liquidity.current_ratio", 2.0, y1, fact_id=8),
        _fact("equity.shares_outstanding", 10.0, y0, fact_id=9),
        _fact("equity.shares_outstanding", 9.0, y1, fact_id=10),
        _fact("is.gross_margin", 0.40, y0, fact_id=11),
        _fact("is.gross_margin", 0.45, y1, fact_id=12),
        _fact("efficiency.asset_turnover", 1.1, y0, fact_id=13),
        _fact("efficiency.asset_turnover", 1.2, y1, fact_id=14),
    ]


def test_build_piotroski_f_score_facts_calculates_complete_standard_total():
    derived = build_piotroski_f_score_facts(_complete_standard_facts())
    by_key = {fact["metric_key"]: fact for fact in derived if fact["period_end_date"] == date(2024, 12, 31)}

    assert by_key["score.piotroski.total"]["value_numeric"] == 9.0
    assert by_key["score.piotroski.total"]["unit"] == "score_total"
    assert by_key["score.piotroski.total"]["value_json"]["status"] == "calculated"
    assert by_key["score.piotroski.total"]["value_json"]["variant"] == "standard"
    assert by_key["score.piotroski.roa_positive"]["value_json"]["method"] == "standard_roa"
    assert by_key["score.piotroski.roa_improving"]["value_json"]["method"] == "standard_roa"


def test_build_piotroski_f_score_facts_uses_standard_before_proxy():
    y0 = date(2023, 12, 31)
    y1 = date(2024, 12, 31)
    facts = _complete_standard_facts() + [
        _fact("returns.total_capital", -0.5, y0, fact_id=20),
        _fact("returns.total_capital", -0.4, y1, fact_id=21),
    ]

    derived = build_piotroski_f_score_facts(facts)
    by_key = {fact["metric_key"]: fact for fact in derived if fact["period_end_date"] == y1}

    assert by_key["score.piotroski.roa_positive"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.roa_positive"]["value_json"]["method"] == "standard_roa"
    assert by_key["score.piotroski.roa_improving"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.roa_improving"]["value_json"]["method"] == "standard_roa"


def test_build_piotroski_f_score_facts_uses_return_on_total_capital_for_roa_improving_proxy():
    y0 = date(2023, 12, 31)
    y1 = date(2024, 12, 31)
    facts = [
        _fact("returns.total_capital", 0.10, y0, fact_id=1),
        _fact("returns.total_capital", 0.12, y1, fact_id=2),
    ]

    derived = build_piotroski_f_score_facts(facts)
    by_key = {fact["metric_key"]: fact for fact in derived if fact["period_end_date"] == y1}

    assert by_key["score.piotroski.roa_positive"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.roa_positive"]["value_json"]["method"] == "fallback_return_on_total_capital"
    assert by_key["score.piotroski.roa_improving"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.roa_improving"]["value_json"]["method"] == "fallback_return_on_total_capital"


def test_build_piotroski_f_score_facts_prefers_total_capital_over_net_income_for_roa_positive_proxy():
    y0 = date(2023, 12, 31)
    y1 = date(2024, 12, 31)
    facts = [
        _fact("returns.total_capital", 0.10, y0, fact_id=1),
        _fact("returns.total_capital", 0.12, y1, fact_id=2),
        _fact("is.net_income", -100.0, y1, fact_id=3),
    ]

    derived = build_piotroski_f_score_facts(facts)
    by_key = {fact["metric_key"]: fact for fact in derived if fact["period_end_date"] == y1}

    assert by_key["score.piotroski.roa_positive"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.roa_positive"]["value_json"]["method"] == "fallback_return_on_total_capital"
    assert by_key["score.piotroski.roa_positive"]["value_json"]["formula"] == "returns.total_capital[Y] > 0"
    assert by_key["score.piotroski.roa_improving"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.roa_improving"]["value_json"]["method"] == "fallback_return_on_total_capital"


def test_build_piotroski_f_score_facts_uses_debt_to_capital_for_leverage_proxy():
    y0 = date(2023, 12, 31)
    y1 = date(2024, 12, 31)
    facts = [
        _fact("leverage.long_term_debt_to_capital", 0.40, y0, fact_id=1),
        _fact("leverage.long_term_debt_to_capital", 0.30, y1, fact_id=2),
    ]

    derived = build_piotroski_f_score_facts(facts)
    by_key = {fact["metric_key"]: fact for fact in derived if fact["period_end_date"] == y1}

    assert by_key["score.piotroski.leverage_declining"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.leverage_declining"]["value_json"]["method"] == "fallback_long_term_debt_to_capital"


def test_build_piotroski_f_score_facts_uses_capital_turnover_for_asset_turnover_proxy():
    y0 = date(2023, 12, 31)
    y1 = date(2024, 12, 31)
    facts = [
        _fact("efficiency.capital_turnover", 1.10, y0, fact_id=1),
        _fact("efficiency.capital_turnover", 1.25, y1, fact_id=2),
    ]

    derived = build_piotroski_f_score_facts(facts)
    by_key = {fact["metric_key"]: fact for fact in derived if fact["period_end_date"] == y1}

    assert by_key["score.piotroski.asset_turnover_improving"]["value_numeric"] == 1.0
    assert by_key["score.piotroski.asset_turnover_improving"]["value_json"]["method"] == "fallback_capital_turnover"


def test_build_piotroski_f_score_facts_writes_partial_total_when_missing_components():
    y1 = date(2024, 12, 31)
    facts = [
        _fact("returns.roa", 0.10, y1, fact_id=1),
        _fact("is.operating_cash_flow", 150.0, y1, fact_nature="estimate", fact_id=2),
        _fact("is.net_income", 100.0, y1, fact_id=3),
    ]

    derived = build_piotroski_f_score_facts(facts)
    total = next(fact for fact in derived if fact["metric_key"] == "score.piotroski.total")

    assert total["value_numeric"] is None
    assert total["value_json"]["status"] == "partial"
    assert total["value_json"]["partial_score"] == 3
    assert total["value_json"]["available_indicators"] == 3
    assert total["value_json"]["fact_nature"] == "estimate"
    assert "score.piotroski.no_dilution" in total["value_json"]["missing_indicators"]


def test_build_piotroski_f_score_facts_ignores_non_fy_inputs():
    snapshot_date = date(2024, 1, 21)
    facts = _complete_standard_facts() + [
        _fact("returns.roa", 0.99, snapshot_date, fact_id=90, period_type="AS_OF"),
        _fact("is.operating_cash_flow", 250.0, snapshot_date, fact_id=91, period_type="AS_OF"),
    ]

    derived = build_piotroski_f_score_facts(facts)

    assert all(fact["period_end_date"] != snapshot_date for fact in derived)


def test_build_piotroski_f_score_facts_calculates_insurance_adjusted_variant():
    y0 = date(2023, 12, 31)
    y1 = date(2024, 12, 31)
    facts = _complete_standard_facts() + [
        _fact("ins.underwriting_margin", 0.10, y0, fact_id=30),
        _fact("ins.underwriting_margin", 0.15, y1, fact_id=31),
        _fact("ins.premium_turnover", 0.9, y0, fact_id=32),
        _fact("ins.premium_turnover", 1.1, y1, fact_id=33),
    ]
    facts = [
        fact
        for fact in facts
        if fact["metric_key"] not in {"is.gross_margin", "efficiency.asset_turnover"}
    ]

    derived = build_piotroski_f_score_facts(facts, company_type="insurance")
    by_key = {fact["metric_key"]: fact for fact in derived if fact["period_end_date"] == y1}

    assert by_key["score.piotroski.total"]["value_numeric"] == 9.0
    assert by_key["score.piotroski.total"]["value_json"]["variant"] == "insurance_adjusted"
    assert by_key["score.piotroski.gross_margin_improving"]["value_json"]["method"] == "insurance_underwriting_margin"
    assert by_key["score.piotroski.asset_turnover_improving"]["value_json"]["method"] == "insurance_premium_turnover"


def test_piotroski_calculator_inserts_current_calculated_facts(db_session, user_factory):
    user = user_factory("piotroski-db@example.com")
    stock = Stock(ticker="FICO", exchange="NYSE", company_name="Fair Isaac")
    db_session.add(stock)
    db_session.commit()

    old_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        value_numeric=5.0,
        value_json={"status": "calculated"},
        unit="score_total",
        period_type="FY",
        period_end_date=date(2024, 12, 31),
        source_type="calculated",
        is_current=True,
    )
    db_session.add(old_fact)
    for idx, fact in enumerate(_complete_standard_facts(), start=100):
        db_session.add(
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key=fact["metric_key"],
                value_numeric=fact["value_numeric"],
                value_json=fact["value_json"],
                period_type=fact["period_type"],
                period_end_date=fact["period_end_date"],
                source_type="parsed",
                is_current=True,
                source_ref_id=idx,
            )
        )
    db_session.commit()

    written = PiotroskiFScoreCalculator(db_session).calculate_for_stock(user_id=user.id, stock_id=stock.id)
    db_session.refresh(old_fact)

    current_total = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.user_id == user.id,
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "score.piotroski.total",
            MetricFact.period_end_date == date(2024, 12, 31),
            MetricFact.is_current.is_(True),
        )
        .one()
    )

    assert written
    assert old_fact.is_current is False
    assert current_total.value_numeric == 9.0
    assert current_total.source_type == "calculated"
    assert current_total.value_json["calculation_version"] == "piotroski_value_line_v1"
