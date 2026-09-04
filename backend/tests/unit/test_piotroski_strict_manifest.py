from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, update

from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.calculated_metrics.piotroski_f_score import (
    PiotroskiFScoreCalculator,
)
from app.services.canonical_financials import (
    PiotroskiMethodAuthorityError,
    guard_piotroski_method_authority,
)
from app.services.screener_service import ScreenerService


PERIOD_0 = date(2023, 12, 31)
PERIOD_1 = date(2024, 12, 31)
STRICT_CALCULATION_VERSION = "piotroski_value_line_v2"
STRICT_MANIFEST_VERSION = "piotroski-strict-manifest-v1"


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(
        ticker=ticker,
        exchange="NYSE",
        company_name=f"{ticker} Strict Manifest",
        is_active=True,
    )
    db_session.add(stock)
    db_session.commit()
    return stock


def _input(
    *,
    user_id: int,
    stock_id: int,
    key: str,
    value: float,
    period_end: date,
    period_type: str = "FY",
) -> MetricFact:
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=key,
        value_numeric=value,
        value_json={"fact_nature": "actual"},
        unit="ratio",
        period_type=period_type,
        period_end_date=period_end,
        source_type="parsed",
        is_current=True,
    )


def _complete_standard_inputs(*, user_id: int, stock_id: int) -> list[MetricFact]:
    rows = [
        ("returns.roa", 0.08, PERIOD_0),
        ("returns.roa", 0.10, PERIOD_1),
        ("is.operating_cash_flow", 150, PERIOD_1),
        ("is.net_income", 100, PERIOD_1),
        ("leverage.long_term_debt_to_assets", 0.30, PERIOD_0),
        ("leverage.long_term_debt_to_assets", 0.20, PERIOD_1),
        ("liquidity.current_ratio", 1.5, PERIOD_0),
        ("liquidity.current_ratio", 2.0, PERIOD_1),
        ("equity.shares_outstanding", 10, PERIOD_0),
        ("equity.shares_outstanding", 9, PERIOD_1),
        ("is.gross_margin", 0.40, PERIOD_0),
        ("is.gross_margin", 0.45, PERIOD_1),
        ("efficiency.asset_turnover", 1.1, PERIOD_0),
        ("efficiency.asset_turnover", 1.2, PERIOD_1),
    ]
    return [
        _input(
            user_id=user_id,
            stock_id=stock_id,
            key=key,
            value=value,
            period_end=period_end,
        )
        for key, value, period_end in rows
    ]


def _generate_complete(db_session, *, user, stock: Stock) -> list[MetricFact]:
    db_session.add_all(
        _complete_standard_inputs(user_id=user.id, stock_id=stock.id)
    )
    db_session.commit()
    return PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=user.id,
        stock_id=stock.id,
    )


def _clone(fact: MetricFact) -> MetricFact:
    return MetricFact(
        user_id=fact.user_id,
        stock_id=fact.stock_id,
        metric_key=fact.metric_key,
        value_numeric=fact.value_numeric,
        value_text=fact.value_text,
        value_json=deepcopy(fact.value_json),
        unit=fact.unit,
        currency=fact.currency,
        period_type=fact.period_type,
        period_end_date=fact.period_end_date,
        source_type=fact.source_type,
        is_current=True,
        created_at=fact.created_at,
    )


def _strict_lineage_item(fact: MetricFact) -> dict:
    return {
        "fact_id": fact.id,
        "user_id": fact.user_id,
        "stock_id": fact.stock_id,
        "metric_key": fact.metric_key,
        "period_type": fact.period_type,
        "period_end_date": fact.period_end_date.isoformat(),
        "value_numeric": format(fact.value_numeric, "f"),
        "source_type": fact.source_type,
        "fact_nature": fact.value_json["fact_nature"],
        "created_at": fact.created_at.isoformat(),
    }


def test_new_generation_writes_strict_rebuildable_manifest_on_components_and_total(
    db_session, user_factory
) -> None:
    user = user_factory("piot-strict-generated@example.com")
    stock = _stock(db_session, "PSTRICT")
    written = _generate_complete(db_session, user=user, stock=stock)
    current_period = [fact for fact in written if fact.period_end_date == PERIOD_1]

    assert len(current_period) == 10
    assert all(
        fact.value_json["calculation_version"] == STRICT_CALCULATION_VERSION
        and fact.value_json["manifest_version"] == STRICT_MANIFEST_VERSION
        for fact in current_period
    )
    assert all(
        len({item["fact_id"] for item in fact.value_json["inputs"]})
        == len(fact.value_json["inputs"])
        for fact in current_period
    )
    for fact in current_period:
        for item in fact.value_json["inputs"]:
            assert set(item) == {
                "fact_id",
                "user_id",
                "stock_id",
                "metric_key",
                "period_type",
                "period_end_date",
                "value_numeric",
                "source_type",
                "fact_nature",
                "created_at",
            }
            assert item["period_type"] == "FY"
            assert item["stock_id"] == stock.id
            assert item["user_id"] == user.id
            assert item["created_at"] <= fact.created_at.isoformat()

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=current_period,
        effective_as_of=date.today(),
    )
    assert kept == current_period
    assert blocked == []


@pytest.mark.parametrize(
    "tamper",
    [
        "duplicate",
        "extra",
        "omitted",
        "wrong_period_type",
        "future_input",
        "method_lie",
        "forged_numeric",
    ],
)
def test_strict_manifest_rejects_any_input_or_rebuilt_output_mismatch(
    db_session, user_factory, tamper: str
) -> None:
    user = user_factory(f"piot-strict-{tamper}@example.com")
    stock = _stock(db_session, f"P{tamper[:7]}")
    written = _generate_complete(db_session, user=user, stock=stock)
    source_inputs = db_session.query(MetricFact).filter(
        MetricFact.stock_id == stock.id,
        MetricFact.source_type == "parsed",
    ).all()
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    forged = _clone(total)

    if tamper == "duplicate":
        forged.value_json["inputs"].append(deepcopy(forged.value_json["inputs"][0]))
    elif tamper == "extra":
        extra = _input(
            user_id=user.id,
            stock_id=stock.id,
            key="revenue",
            value=999,
            period_end=PERIOD_1,
        )
        db_session.add(extra)
        db_session.commit()
        forged.value_json["inputs"].append(_strict_lineage_item(extra))
    elif tamper == "omitted":
        forged.value_json["inputs"].pop()
    elif tamper == "wrong_period_type":
        forged.value_json["inputs"][0]["period_type"] = "Q"
    elif tamper == "future_input":
        newest = max(source_inputs, key=lambda item: item.created_at)
        forged.created_at = newest.created_at - timedelta(microseconds=1)
    elif tamper == "method_lie":
        forged.value_json["components"][0]["method"] = (
            "fallback_return_on_total_capital"
        )
    else:
        forged.value_numeric = 8

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[forged],
        effective_as_of=date.today(),
    )
    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )
    assert blocked[0]["value_numeric"] is None
    assert "components" not in blocked[0]
    assert "partial_score" not in blocked[0]


def test_legacy_non_proxy_score_is_quarantined_without_strict_manifest(
    db_session, user_factory
) -> None:
    user = user_factory("piot-legacy-strict@example.com")
    stock = _stock(db_session, "PLEGACY2")
    source = _input(
        user_id=user.id,
        stock_id=stock.id,
        key="returns.roa",
        value=0.12,
        period_end=PERIOD_1,
    )
    db_session.add(source)
    db_session.commit()
    legacy = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.roa_positive",
        value_numeric=1,
        value_json={
            "calculation_version": "piotroski_value_line_v1",
            "method": "standard_roa",
            "inputs": [
                {
                    "fact_id": source.id,
                    "metric_key": source.metric_key,
                    "period_end_date": source.period_end_date.isoformat(),
                    "value_numeric": format(source.value_numeric, "f"),
                    "source_type": source.source_type,
                    "fact_nature": "actual",
                }
            ],
        },
        period_type="FY",
        period_end_date=PERIOD_1,
        source_type="calculated",
        is_current=True,
    )

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[legacy],
        effective_as_of=date.today(),
    )
    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_missing"
    )


def test_guard_batches_input_lookup_for_many_piotroski_facts(
    db_session, user_factory
) -> None:
    user = user_factory("piot-query-bound@example.com")
    stock = _stock(db_session, "PBOUND")
    written = _generate_complete(db_session, user=user, stock=stock)
    facts = [fact for fact in written if fact.period_end_date == PERIOD_1]
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM metric_facts" in statement:
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        kept, blocked = guard_piotroski_method_authority(
            db_session,
            facts=facts,
            effective_as_of=date.today(),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)

    assert kept == facts
    assert blocked == []
    # One bounded sibling expansion plus one batched input lookup.
    assert len(statements) <= 2


def test_component_only_request_requires_and_uses_complete_current_siblings(
    db_session, user_factory
) -> None:
    user = user_factory("piot-component-only@example.com")
    stock = _stock(db_session, "PCOMPONLY")
    written = _generate_complete(db_session, user=user, stock=stock)
    component = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[component],
        effective_as_of=date.today(),
    )

    assert kept == [component]
    assert blocked == []


def test_component_only_screener_requires_complete_current_sibling_period(
    db_session, user_factory
) -> None:
    user = user_factory("piot-component-screener@example.com")
    stock = _stock(db_session, "PCOMPSCR")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    rule = {
        "type": "AND",
        "conditions": [
            {
                "metric": "score.piotroski.roa_positive",
                "operator": ">=",
                "value": 0,
            }
        ],
    }

    assert {
        item.id
        for item in ScreenerService(db_session).execute_screen(
            rule, current_user_id=user.id
        )
    } == {stock.id}

    db_session.execute(
        update(MetricFact)
        .where(MetricFact.id == total.id)
        .values(is_current=False)
    )
    db_session.commit()
    with pytest.raises(PiotroskiMethodAuthorityError) as error:
        ScreenerService(db_session).execute_screen(
            rule, current_user_id=user.id
        )
    assert error.value.code == "piotroski_method_authority_manifest_invalid"


def test_component_only_request_is_quarantined_when_current_total_is_demoted(
    db_session, user_factory
) -> None:
    user = user_factory("piot-component-missing-total@example.com")
    stock = _stock(db_session, "PNOTOTAL")
    written = _generate_complete(db_session, user=user, stock=stock)
    component = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    db_session.execute(
        update(MetricFact)
        .where(MetricFact.id == total.id)
        .values(is_current=False)
    )
    db_session.commit()

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[component],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )
    assert blocked[0]["value_numeric"] is None


def test_total_only_request_is_quarantined_when_a_current_component_is_missing(
    db_session, user_factory
) -> None:
    user = user_factory("piot-total-missing-component@example.com")
    stock = _stock(db_session, "PNOCOMP")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    component = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )
    db_session.execute(
        update(MetricFact)
        .where(MetricFact.id == component.id)
        .values(is_current=False)
    )
    db_session.commit()

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[total],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )


def test_total_only_request_is_quarantined_for_duplicate_current_sibling_key(
    db_session, user_factory
) -> None:
    user = user_factory("piot-duplicate-sibling@example.com")
    stock = _stock(db_session, "PDUPSIB")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    component = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )
    db_session.add(_clone(component))
    db_session.commit()

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[total],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )


def test_total_only_request_is_quarantined_for_invalid_current_sibling(
    db_session, user_factory
) -> None:
    user = user_factory("piot-invalid-sibling@example.com")
    stock = _stock(db_session, "PBADSIB")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    component = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )
    forged = _clone(component)
    forged.value_numeric = Decimal("0")
    db_session.execute(
        update(MetricFact)
        .where(MetricFact.id == component.id)
        .values(is_current=False)
    )
    db_session.add(forged)
    db_session.commit()

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[total],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )


def test_blocked_proxy_period_writes_only_unavailable_total(
    db_session, user_factory
) -> None:
    user = user_factory("piot-period-atomic@example.com")
    stock = _stock(db_session, "PATOMIC")
    db_session.add_all(
        [
            _input(
                user_id=user.id,
                stock_id=stock.id,
                key="returns.total_capital",
                value=0.12,
                period_end=PERIOD_1,
            ),
            _input(
                user_id=user.id,
                stock_id=stock.id,
                key="is.operating_cash_flow",
                value=150,
                period_end=PERIOD_1,
            ),
        ]
    )
    db_session.commit()

    written = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=user.id,
        stock_id=stock.id,
    )
    assert [fact.metric_key for fact in written] == ["score.piotroski.total"]
    assert written[0].value_numeric is None
    assert written[0].value_json["status"] == "unavailable"
    assert "partial_score" not in written[0].value_json
    assert "components" not in written[0].value_json


def test_recalculation_demotes_all_prior_current_piotroski_period_facts(
    db_session, user_factory
) -> None:
    user = user_factory("piot-period-demotion@example.com")
    stock = _stock(db_session, "PDEMOTE")
    first = _generate_complete(db_session, user=user, stock=stock)
    second = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=user.id,
        stock_id=stock.id,
    )

    db_session.expire_all()
    assert all(db_session.get(MetricFact, fact.id).is_current is False for fact in first)
    assert all(db_session.get(MetricFact, fact.id).is_current is True for fact in second)
    for period_end in {fact.period_end_date for fact in second}:
        assert db_session.query(MetricFact).filter(
            MetricFact.stock_id == stock.id,
            MetricFact.user_id == user.id,
            MetricFact.metric_key.like("score.piotroski.%"),
            MetricFact.period_end_date == period_end,
            MetricFact.is_current.is_(True),
        ).count() == len([fact for fact in second if fact.period_end_date == period_end])


def test_blocked_total_quarantines_every_component_in_same_fact_batch(
    db_session, user_factory
) -> None:
    user = user_factory("piot-batch-atomic@example.com")
    stock = _stock(db_session, "PBATCH")
    written = _generate_complete(db_session, user=user, stock=stock)
    component = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    forged_total = _clone(total)
    forged_total.value_numeric = 8

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[component, forged_total],
        effective_as_of=date.today(),
    )
    assert kept == []
    assert {state["metric_key"] for state in blocked} == {
        "score.piotroski.roa_positive",
        "score.piotroski.total",
    }
    assert all(state["value_numeric"] is None for state in blocked)


def test_period_quarantine_never_crosses_tenant_boundary(
    db_session, user_factory
) -> None:
    first_user = user_factory("piot-period-tenant-a@example.com")
    second_user = user_factory("piot-period-tenant-b@example.com")
    stock = _stock(db_session, "PTENANT")
    first = _generate_complete(db_session, user=first_user, stock=stock)
    second = _generate_complete(db_session, user=second_user, stock=stock)
    forged_first_total = _clone(
        next(
            fact
            for fact in first
            if fact.metric_key == "score.piotroski.total"
            and fact.period_end_date == PERIOD_1
        )
    )
    forged_first_total.value_numeric = 8
    valid_second_component = next(
        fact
        for fact in second
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[forged_first_total, valid_second_component],
        effective_as_of=date.today(),
    )
    assert kept == [valid_second_component]
    assert [state["metric_key"] for state in blocked] == [
        "score.piotroski.total"
    ]


def test_missing_siblings_quarantine_only_the_matching_tenant_period(
    db_session, user_factory
) -> None:
    first_user = user_factory("piot-sibling-tenant-a@example.com")
    second_user = user_factory("piot-sibling-tenant-b@example.com")
    stock = _stock(db_session, "PSIBTEN")
    first = _generate_complete(db_session, user=first_user, stock=stock)
    second = _generate_complete(db_session, user=second_user, stock=stock)
    first_component = next(
        fact
        for fact in first
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )
    first_total = next(
        fact
        for fact in first
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    second_component = next(
        fact
        for fact in second
        if fact.metric_key == "score.piotroski.roa_positive"
        and fact.period_end_date == PERIOD_1
    )
    db_session.execute(
        update(MetricFact)
        .where(MetricFact.id == first_total.id)
        .values(is_current=False)
    )
    db_session.commit()

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[first_component, second_component],
        effective_as_of=date.today(),
    )

    assert kept == [second_component]
    assert len(blocked) == 1
    assert blocked[0]["metric_key"] == first_component.metric_key
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )


def _captured_metric_fact_queries(db_session):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM metric_facts" in statement:
            statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    return statements, capture


def test_request_fact_bound_blocks_before_any_authority_query(
    db_session, user_factory
) -> None:
    user = user_factory("piot-request-bound@example.com")
    stock = _stock(db_session, "PREQBOUND")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    requested = [_clone(total) for _ in range(501)]
    statements, listener = _captured_metric_fact_queries(db_session)
    try:
        kept, blocked = guard_piotroski_method_authority(
            db_session,
            facts=requested,
            effective_as_of=date.today(),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    assert kept == []
    assert len(blocked) == len(requested)
    assert {state["reason_code"] for state in blocked} == {
        "piotroski_method_authority_bound_exceeded"
    }
    assert statements == []


def test_period_group_bound_blocks_before_any_authority_query(
    db_session, user_factory
) -> None:
    user = user_factory("piot-period-bound@example.com")
    stock = _stock(db_session, "PPERBOUND")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    requested = []
    for ordinal in range(51):
        clone = _clone(total)
        clone.period_end_date = PERIOD_1 + timedelta(days=ordinal)
        requested.append(clone)
    statements, listener = _captured_metric_fact_queries(db_session)
    try:
        kept, blocked = guard_piotroski_method_authority(
            db_session,
            facts=requested,
            effective_as_of=date.today(),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    assert kept == []
    assert len(blocked) == len(requested)
    assert {state["reason_code"] for state in blocked} == {
        "piotroski_method_authority_bound_exceeded"
    }
    assert statements == []


def test_per_manifest_input_bound_blocks_before_any_authority_query(
    db_session, user_factory
) -> None:
    user = user_factory("piot-manifest-bound@example.com")
    stock = _stock(db_session, "PMANBOUND")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = _clone(
        next(
            fact
            for fact in written
            if fact.metric_key == "score.piotroski.total"
            and fact.period_end_date == PERIOD_1
        )
    )
    seed = deepcopy(total.value_json["inputs"][0])
    while len(total.value_json["inputs"]) <= 32:
        item = deepcopy(seed)
        item["fact_id"] = 1_000_000 + len(total.value_json["inputs"])
        total.value_json["inputs"].append(item)
    statements, listener = _captured_metric_fact_queries(db_session)
    try:
        kept, blocked = guard_piotroski_method_authority(
            db_session,
            facts=[total],
            effective_as_of=date.today(),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_bound_exceeded"
    )
    assert statements == []


def test_aggregate_unique_input_bound_blocks_before_any_authority_query(
    db_session, user_factory
) -> None:
    user = user_factory("piot-input-id-bound@example.com")
    stock = _stock(db_session, "PIDBOUND")
    written = _generate_complete(db_session, user=user, stock=stock)
    persisted = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    requested = []
    for ordinal in range(40):
        clone = _clone(persisted)
        seed = deepcopy(clone.value_json["inputs"][0])
        clone.value_json["inputs"] = []
        for input_ordinal in range(30):
            item = deepcopy(seed)
            item["fact_id"] = 2_000_000 + ordinal * 100 + input_ordinal
            clone.value_json["inputs"].append(item)
        requested.append(clone)
    statements, listener = _captured_metric_fact_queries(db_session)
    try:
        kept, blocked = guard_piotroski_method_authority(
            db_session,
            facts=requested,
            effective_as_of=date.today(),
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", listener)

    assert kept == []
    assert len(blocked) == len(requested)
    assert {state["reason_code"] for state in blocked} == {
        "piotroski_method_authority_bound_exceeded"
    }
    assert statements == []


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_output_is_typed_unavailable_instead_of_raising(
    db_session, user_factory, value: str
) -> None:
    user = user_factory(f"piot-nonfinite-{value.lower()}@example.com")
    stock = _stock(db_session, f"PNF{value[:3]}")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = _clone(
        next(
            fact
            for fact in written
            if fact.metric_key == "score.piotroski.total"
            and fact.period_end_date == PERIOD_1
        )
    )
    total.value_numeric = Decimal(value)

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[total],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )
    assert blocked[0]["value_numeric"] is None


def test_postgres_nan_source_is_typed_unavailable_instead_of_raising(
    db_session, user_factory
) -> None:
    user = user_factory("piot-source-nan@example.com")
    stock = _stock(db_session, "PSRCNAN")
    written = _generate_complete(db_session, user=user, stock=stock)
    total = _clone(
        next(
            fact
            for fact in written
            if fact.metric_key == "score.piotroski.total"
            and fact.period_end_date == PERIOD_1
        )
    )
    original_source = next(
        fact
        for fact in db_session.query(MetricFact).filter(
            MetricFact.stock_id == stock.id,
            MetricFact.source_type == "parsed",
            MetricFact.metric_key == "returns.roa",
            MetricFact.period_end_date == PERIOD_1,
        )
    )
    source = _input(
        user_id=user.id,
        stock_id=stock.id,
        key="returns.roa",
        value=Decimal("NaN"),
        period_end=PERIOD_1,
    )
    db_session.add(source)
    db_session.commit()
    lineage_index = next(
        index
        for index, item in enumerate(total.value_json["inputs"])
        if item["fact_id"] == original_source.id
    )
    total.value_json["inputs"][lineage_index] = _strict_lineage_item(source)

    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=[total],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )
    assert blocked[0]["value_numeric"] is None
