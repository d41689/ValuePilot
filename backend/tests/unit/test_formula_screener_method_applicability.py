from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.models.facts import CalculatedRun, Formula, MetricFact
from app.models.sec_publication import SecEconomicClassificationReview
from app.models.stocks import Stock
from app.services.canonical_financials import (
    CanonicalUnavailableError,
    UnsupportedSystemMethodError,
)
from app.services.formula_engine import FormulaEngine
from app.services.method_applicability import (
    RISK_ATTRIBUTES,
    review_company_classification,
    review_company_risk_attribute,
)
from app.services.screener_service import (
    MAX_SCREENER_SQL_BIND_BUDGET,
    SCREENER_ALLOWED_PAIR_BIND_COUNT,
    SCREENER_CONDITION_BIND_OVERHEAD,
    ScreenerService,
    _ScreenerSourceAuthority,
)


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


def test_screener_binds_predicate_to_fact_ids_verified_before_replacement(
    db_session, user_factory
) -> None:
    user = user_factory("screener-fact-race@example.com", role="admin")
    stock = _stock(db_session, "SCRRACE")
    _review_profile(
        db_session,
        reviewer=user,
        stock=stock,
        economic_class="ordinary",
    )
    original = _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="owners_earnings_per_share",
        value=10,
    )
    service = ScreenerService(db_session)
    original_guard = service._guard_screen_sources

    def replace_after_guard(*args, **kwargs):
        authority = original_guard(*args, **kwargs)
        with Session(bind=db_session.get_bind(), autoflush=False) as concurrent:
            concurrent.execute(
                update(MetricFact)
                .where(MetricFact.id == original.id)
                .values(is_current=False)
            )
            concurrent.add(
                MetricFact(
                    user_id=user.id,
                    stock_id=stock.id,
                    metric_key="owners_earnings_per_share",
                    value_numeric=100,
                    value_json={"fact_nature": "actual"},
                    unit="ratio",
                    period_type="FY",
                    period_end_date=date(2024, 12, 31),
                    source_type="manual",
                    is_current=True,
                )
            )
            concurrent.commit()
        return authority

    service._guard_screen_sources = replace_after_guard

    matched = service.execute_screen(
        {
            "type": "AND",
            "conditions": [
                {
                    "metric": "owners_earnings_per_share",
                    "operator": ">",
                    "value": 50,
                }
            ],
        },
        current_user_id=user.id,
    )

    assert matched == []


def test_screener_binds_predicate_to_numeric_verified_before_same_id_update(
    db_session, user_factory
) -> None:
    user = user_factory("screener-numeric-race@example.com", role="admin")
    stock = _stock(db_session, "SCRNUM")
    _review_profile(
        db_session,
        reviewer=user,
        stock=stock,
        economic_class="ordinary",
    )
    fact = _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="returns.total_capital",
        value=10,
    )
    service = ScreenerService(db_session)
    original_guard = service._guard_screen_sources

    def mutate_after_guard(*args, **kwargs):
        authority = original_guard(*args, **kwargs)
        with Session(bind=db_session.get_bind(), autoflush=False) as concurrent:
            concurrent.execute(
                update(MetricFact)
                .where(MetricFact.id == fact.id)
                .values(value_numeric=100)
            )
            concurrent.commit()
        return authority

    service._guard_screen_sources = mutate_after_guard

    matched = service.execute_screen(
        {
            "type": "AND",
            "conditions": [
                {
                    "metric": "returns.total_capital",
                    "operator": ">",
                    "value": 50,
                }
            ],
        },
        current_user_id=user.id,
    )

    assert matched == []


def test_screener_uses_one_cutoff_when_review_commits_after_initial_guard(
    db_session, user_factory
) -> None:
    user = user_factory("screener-review-race@example.com", role="admin")
    stock = _stock(db_session, "SCRREVIEW")
    _review_profile(
        db_session,
        reviewer=user,
        stock=stock,
        economic_class="ordinary",
    )
    classification = db_session.query(SecEconomicClassificationReview).filter_by(
        stock_id=stock.id
    ).one()
    _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="returns.total_capital",
        value=100,
    )
    service = ScreenerService(db_session)
    original_guard = service._guard_screen_sources
    observed: dict[str, object] = {}

    def invalidate_after_guard(*args, **kwargs):
        authority = original_guard(*args, **kwargs)
        observed["evaluated_at"] = authority.evaluated_at
        with Session(bind=db_session.get_bind(), autoflush=False) as concurrent:
            review = review_company_classification(
                concurrent,
                reviewer_user_id=user.id,
                stock_id=stock.id,
                economic_class="bank",
                effective_from=date(2020, 1, 1),
                supersedes_review_id=classification.id,
                review_reason="Reclassified before screener predicate execution.",
            )
            concurrent.commit()
            observed["review_known_at"] = review.known_at
        return authority

    service._guard_screen_sources = invalidate_after_guard

    matched = service.execute_screen(
        {
            "type": "AND",
            "conditions": [
                {
                    "metric": "returns.total_capital",
                    "operator": ">",
                    "value": 50,
                }
            ],
        },
        current_user_id=user.id,
    )

    assert matched == [stock]
    assert observed["review_known_at"] > observed["evaluated_at"]


def test_screener_allows_reviewed_multistock_multicondition_sources_only(
    db_session, user_factory
) -> None:
    user = user_factory("screener-multistock@example.com", role="admin")
    stocks = [_stock(db_session, ticker) for ticker in ("SCRMA", "SCRMB")]
    for stock in stocks:
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
            metric_key="owners_earnings_per_share",
            value=100,
        )
        _governed_fact(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            metric_key="revenue",
            value=100,
        )
    _governed_fact(
        db_session,
        user_id=user.id,
        stock_id=stocks[0].id,
        metric_key="system_valuation.dcf",
        value=1_000,
    )

    matched = ScreenerService(db_session).execute_screen(
        {
            "type": "AND",
            "conditions": [
                {
                    "metric": "owners_earnings_per_share",
                    "operator": ">",
                    "value": 50,
                },
                {"metric": "revenue", "operator": ">", "value": 50},
            ],
        },
        current_user_id=user.id,
    )

    assert {item.id for item in matched} == {stock.id for stock in stocks}


def _synthetic_screen_authority(pair_count: int) -> _ScreenerSourceAuthority:
    return _ScreenerSourceAuthority(
        evaluated_at=datetime.now(timezone.utc),
        allowed_by_stock_metric={
            (1, "revenue"): tuple(
                (fact_id, Decimal("100"))
                for fact_id in range(1, pair_count + 1)
            )
        },
    )


def test_screener_rejects_repeated_condition_bind_expansion_before_sql(
    db_session,
) -> None:
    service = ScreenerService(db_session)
    authority = _synthetic_screen_authority(10_000)
    service._guard_screen_sources = lambda *_args, **_kwargs: authority
    statements: list[str] = []

    def before_cursor_execute(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", before_cursor_execute)
    try:
        with pytest.raises(CanonicalUnavailableError) as error:
            service.execute_screen(
                {
                    "type": "AND",
                    "conditions": [
                        {"metric": "revenue", "operator": ">", "value": 50}
                        for _ in range(7)
                    ],
                },
                current_user_id=1,
            )
    finally:
        event.remove(
            db_session.get_bind(), "before_cursor_execute", before_cursor_execute
        )

    assert error.value.code == "screener_source_guard_bound_exceeded"
    assert statements == []


def test_screener_allows_exact_conservative_bind_budget_boundary(
    db_session,
) -> None:
    service = ScreenerService(db_session)
    condition_count = 3
    pair_count = (
        MAX_SCREENER_SQL_BIND_BUDGET // condition_count
        - SCREENER_CONDITION_BIND_OVERHEAD
    ) // SCREENER_ALLOWED_PAIR_BIND_COUNT
    assert condition_count * (
        pair_count * SCREENER_ALLOWED_PAIR_BIND_COUNT
        + SCREENER_CONDITION_BIND_OVERHEAD
    ) == MAX_SCREENER_SQL_BIND_BUDGET
    authority = _synthetic_screen_authority(pair_count)
    service._guard_screen_sources = lambda *_args, **_kwargs: authority

    matched = service.execute_screen(
        {
            "type": "AND",
            "conditions": [
                {"metric": "revenue", "operator": ">", "value": 50}
                for _ in range(condition_count)
            ],
        },
        current_user_id=1,
    )

    assert matched == []


def test_screener_empty_authority_remains_fail_closed(db_session) -> None:
    service = ScreenerService(db_session)
    authority = _synthetic_screen_authority(0)
    service._guard_screen_sources = lambda *_args, **_kwargs: authority

    assert service.execute_screen(
        {
            "type": "AND",
            "conditions": [
                {"metric": "revenue", "operator": ">", "value": 50}
            ],
        },
        current_user_id=1,
    ) == []
