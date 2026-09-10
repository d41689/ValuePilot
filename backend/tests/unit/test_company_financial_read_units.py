"""Complete metric units, not arbitrary prefixes, bound company reads."""
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.models.stocks import Stock
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.metric_fact_currentness import CurrentnessScopeError
from app.services import source_reconciliation as reconciliation


def _fixture(db_session, user_factory):
    user = user_factory("company-units@example.com")
    stock = Stock(ticker="UNITS", exchange="NYSE", company_name="Read Units")
    db_session.add(stock)
    db_session.flush()
    return user, stock


def _insert(db, user, stock, *, key, count, current=True, offset=0, created_at=None):
    db.execute(text(
        "INSERT INTO metric_facts "
        "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,"
        "unit,currency,period_type,period_end_date,is_current,created_at) "
        "SELECT :user,:stock,:key,g,'{\"manual_role\":\"original_input\"}',"
        "'manual','currency','USD','FY',DATE '1800-01-01' + g + :offset,:current,"
        "coalesce(:created_at,clock_timestamp()) "
        "FROM generate_series(1,:count) AS g"
    ), dict(user=user.id, stock=stock.id, key=key, count=count,
            current=current, offset=offset, created_at=created_at))
    db.flush()


def _read(db, user, stock, snapshot=None):
    return reconciliation.read_bounded_company_facts(
        db, stock_id=stock.id, user_id=user.id,
        evaluation_snapshot=snapshot or database_evaluation_snapshot(db),
    )


def test_company_read_keeps_complete_metrics_above_global_bounds(
    db_session, user_factory,
):
    user, stock = _fixture(db_session, user_factory)
    for key in ("is.revenue", "is.net_income", "is.operating_cash_flow"):
        _insert(db_session, user, stock, key=key, count=200)
        _insert(db_session, user, stock, key=key, count=200, current=False)
    db_session.commit()
    facts, unavailable = _read(db_session, user, stock)
    assert len(facts) == 600
    assert len({fact.id for fact in facts}) == 600
    assert unavailable == []


@pytest.mark.parametrize("count,reason", [
    (251, "reconciliation_bound_exceeded"),
    (1001, "metric_fact_currentness_scope_bound_exceeded"),
])
def test_company_read_redacts_only_complete_oversized_metric(
    db_session, user_factory, count, reason,
):
    user, stock = _fixture(db_session, user_factory)
    _insert(db_session, user, stock, key="is.net_income", count=count)
    _insert(db_session, user, stock, key="is.revenue", count=1)
    db_session.commit()
    facts, unavailable = _read(db_session, user, stock)
    assert [fact.metric_key for fact in facts] == ["is.revenue"]
    assert len(unavailable) == 1
    assert unavailable[0]["metric_key"] == "is.net_income"
    assert unavailable[0]["reason_code"] == reason
    assert unavailable[0]["value_numeric"] is None


def test_company_metric_discovery_never_returns_a_prefix(
    db_session, user_factory,
):
    user, stock = _fixture(db_session, user_factory)
    for index in range(65):
        _insert(db_session, user, stock, key=f"unit.key_{index}", count=16)
    db_session.commit()
    with pytest.raises(CurrentnessScopeError) as captured:
        _read(db_session, user, stock)
    assert captured.value.code == "metric_fact_currentness_scope_bound_exceeded"


def test_existing_small_company_with_more_than_64_keys_remains_readable(
    db_session, user_factory,
):
    user, stock = _fixture(db_session, user_factory)
    for index in range(65):
        _insert(db_session, user, stock, key=f"unit.key_{index}", count=1)
    db_session.commit()
    facts, unavailable = _read(db_session, user, stock)
    assert len(facts) == 65
    assert unavailable == []


def test_company_units_exclude_other_owner_and_post_snapshot_rows(
    db_session, user_factory,
):
    user, stock = _fixture(db_session, user_factory)
    other = user_factory("company-units-private@example.com")
    _insert(db_session, user, stock, key="is.revenue", count=1)
    _insert(db_session, other, stock, key="is.net_income", count=1001)
    db_session.commit()
    snapshot = database_evaluation_snapshot(db_session)
    db_session.commit()
    # Late facts use the same owner and key; they must not consume the bound
    # even if created_at is caller-backdated.
    _insert(db_session, user, stock, key="is.revenue", count=1001, offset=1,
            created_at=snapshot.cutoff - timedelta(days=10))
    db_session.commit()
    facts, unavailable = _read(db_session, user, stock, snapshot)
    assert len(facts) == 1
    assert facts[0].metric_key == "is.revenue"
    assert unavailable == []


@pytest.mark.parametrize("surface", ["facts", "workspace"])
def test_product_company_read_has_no_global_prefix(
    client, db_session, user_factory, auth_headers, surface, monkeypatch,
):
    from app.api.v1.endpoints import stocks as stock_endpoint
    from app.services import research_workspace

    target = research_workspace if surface == "workspace" else stock_endpoint
    original_guard = target.guard_reconciled_source_selection
    guard_calls = []

    def counted_guard(facts, **kwargs):
        guard_calls.append(len(facts))
        return original_guard(facts, **kwargs)

    monkeypatch.setattr(target, "guard_reconciled_source_selection", counted_guard)
    user, stock = _fixture(db_session, user_factory)
    for key in ("is.revenue", "is.net_income", "is.operating_cash_flow"):
        _insert(db_session, user, stock, key=key, count=110)
        _insert(db_session, user, stock, key=key, count=250, current=False)
    db_session.commit()
    headers = auth_headers(user)
    if surface == "workspace":
        created = client.post("/api/v1/research/cases", headers=headers, json={
            "stock_id": stock.id,
            "origin": {"origin_type": "manual", "origin_key": "manual",
                       "source_version": "user-action-v1",
                       "source_ref": {"entry_point": "ticker_search"}},
        })
        assert created.status_code in (200, 201), created.text
        case_id = created.json()["case"]["id"]
        path = f"/api/v1/research/cases/{case_id}/workspace"
    else:
        path = f"/api/v1/stocks/{stock.id}/facts"
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    facts = payload["fundamentals"] if surface == "workspace" else payload
    assert len(facts) == 330
    assert len({fact["id"] for fact in facts}) == 330
    assert all(fact["value_numeric"] is not None for fact in facts)
    assert guard_calls == [110, 110, 110]
    if surface == "workspace":
        reports = payload["source_reconciliation"]
        assert reports["partitioning"] == "complete_metric_history"
        assert len(reports["by_metric"]) == 3
        assert len({item["report"]["knowledge_cutoff"]
                    for item in reports["by_metric"]}) == 1
