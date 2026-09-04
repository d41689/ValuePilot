from __future__ import annotations

from datetime import date

import pytest

from app.models.facts import CalculatedRun, Formula, MetricFact
from app.models.stocks import Stock
from app.services.canonical_financials import UnsupportedSystemMethodError
from app.services.formula_engine import FormulaEngine
from app.services.method_applicability import (
    RISK_ATTRIBUTES,
    review_company_classification,
    review_company_risk_attribute,
)
from app.services.screener_service import ScreenerService


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(
        ticker=ticker,
        exchange="NYSE",
        company_name=f"{ticker} Method Consumer",
        is_active=True,
    )
    db_session.add(stock)
    db_session.commit()
    return stock


def _review_profile(
    db_session,
    *,
    reviewer,
    stock: Stock,
    economic_class: str,
    present_risk: str | None = None,
) -> None:
    review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class=economic_class,
        effective_from=date(2020, 1, 1),
        review_reason="Reviewed formula and screener method profile.",
    )
    if economic_class == "ordinary":
        for risk_attribute in sorted(RISK_ATTRIBUTES):
            review_company_risk_attribute(
                db_session,
                reviewer_user_id=reviewer.id,
                stock_id=stock.id,
                risk_attribute=risk_attribute,
                is_present=risk_attribute == present_risk,
                effective_from=date(2020, 1, 1),
                review_reason=f"Reviewed {risk_attribute} for method consumers.",
            )
    db_session.commit()


def _governed_fact(
    db_session,
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    value: float = 100,
) -> MetricFact:
    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value,
        value_json={"fact_nature": "actual"},
        unit="ratio",
        period_type="FY",
        period_end_date=date(2024, 12, 31),
        source_type="manual",
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()
    return fact


def _formula(db_session, *, user_id: int, metric_key: str, suffix: str) -> Formula:
    formula = Formula(
        user_id=user_id,
        name=f"custom.consumer.{suffix}",
        expression=(f"{metric_key} + 1" if metric_key.isidentifier() else "1 + 1"),
        dependencies_json=[metric_key],
    )
    db_session.add(formula)
    db_session.commit()
    return formula


@pytest.mark.parametrize(
    ("label", "metric_key", "economic_class", "present_risk", "reason_code"),
    [
        ("oe_unreviewed", "owners_earnings_per_share", None, None, "classification_unreviewed"),
        ("roic_bank", "returns.total_capital", "bank", None, "roic_unsupported_for_bank"),
        ("trend_reit", "rates.sales.cagr_5y", "reit", None, "per_share_trend_unsupported_for_reit"),
        (
            "valuation_ordinary",
            "system_valuation.dcf",
            "ordinary",
            None,
            "system_valuation_method_pending_ft09",
        ),
        *[
            (
                f"risk_{risk_attribute}",
                "returns.total_capital",
                "ordinary",
                risk_attribute,
                "reviewed_risk_attribute_unsupported",
            )
            for risk_attribute in sorted(RISK_ATTRIBUTES)
        ],
    ],
)
def test_formula_and_screener_fail_closed_before_using_governed_numeric(
    client,
    db_session,
    user_factory,
    auth_headers,
    label: str,
    metric_key: str,
    economic_class: str | None,
    present_risk: str | None,
    reason_code: str,
) -> None:
    user = user_factory(f"consumer-{label}@example.com", role="admin")
    stock = _stock(db_session, f"C{label[:7]}")
    if economic_class is not None:
        _review_profile(
            db_session,
            reviewer=user,
            stock=stock,
            economic_class=economic_class,
            present_risk=present_risk,
        )
    _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key=metric_key,
    )
    formula = _formula(
        db_session,
        user_id=user.id,
        metric_key=metric_key,
        suffix=label,
    )

    with pytest.raises(UnsupportedSystemMethodError) as formula_error:
        FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)
    assert formula_error.value.decision.reason_code == reason_code
    assert db_session.query(CalculatedRun).filter_by(formula_id=formula.id).count() == 0

    # The numeric cannot become a SQL prefilter oracle: it is blocked even when
    # its value would not match the requested predicate.
    rule = {
        "type": "AND",
        "conditions": [{"metric": metric_key, "operator": ">", "value": 999}],
    }
    with pytest.raises(UnsupportedSystemMethodError) as screener_error:
        ScreenerService(db_session).execute_screen(rule, current_user_id=user.id)
    assert screener_error.value.decision.reason_code == reason_code

    response = client.post(
        "/api/v1/screener/run",
        headers=auth_headers(user),
        json=rule,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "unsupported"


@pytest.mark.parametrize(
    "metric_key",
    [
        "owners_earnings_per_share",
        "roic",
    ],
)
def test_formula_and_screener_allow_reviewed_ordinary_method_inputs(
    db_session, user_factory, metric_key: str
) -> None:
    user = user_factory(
        f"approved-{metric_key.replace('.', '-')}@example.com", role="admin"
    )
    stock = _stock(db_session, f"A{len(metric_key)}")
    _review_profile(
        db_session,
        reviewer=user,
        stock=stock,
        economic_class="ordinary",
    )
    _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key=metric_key,
    )
    formula = _formula(
        db_session,
        user_id=user.id,
        metric_key=metric_key,
        suffix=f"approved{len(metric_key)}",
    )

    run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)
    assert run is not None
    assert run.result_value_json["value"] == "101.000000000000"
    matched = ScreenerService(db_session).execute_screen(
        {
            "type": "AND",
            "conditions": [{"metric": metric_key, "operator": ">", "value": 50}],
        },
        current_user_id=user.id,
    )
    assert matched == [stock]


def test_formula_and_screener_ignore_unrelated_blocked_fact(
    db_session, user_factory
) -> None:
    user = user_factory("consumer-unrelated@example.com")
    stock = _stock(db_session, "CLEANDEP")
    _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="system_valuation.dcf",
    )
    _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
    )
    formula = _formula(
        db_session,
        user_id=user.id,
        metric_key="revenue",
        suffix="unrelated",
    )

    assert FormulaEngine(db_session).run_formula(
        formula.id, stock.id, user.id
    ) is not None
    assert ScreenerService(db_session).execute_screen(
        {
            "type": "AND",
            "conditions": [{"metric": "revenue", "operator": ">", "value": 50}],
        },
        current_user_id=user.id,
    ) == [stock]
