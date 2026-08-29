from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.users import User
from app.models.stocks import PoolMembership, Stock, StockPool
from app.models.facts import MetricFact
from app.models.research import ResearchCase, ResearchCaseRevision
from app.core.security import hash_password


FAIR_VALUE_KEY = "val.fair_value"
ET = ZoneInfo("America/New_York")


def _make_user(db_session, email: str = "fairvalue@example.com") -> User:
    user = User(email=email, hashed_password=hash_password("TestPass123!"))
    db_session.add(user)
    db_session.commit()
    return user


def _make_stock(db_session, ticker: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Inc")
    db_session.add(stock)
    db_session.commit()
    return stock


def _make_valuation_revision(
    db_session,
    *,
    user: User,
    stock: Stock,
    value: float,
    as_of_date: date,
) -> ResearchCaseRevision:
    case = (
        db_session.query(ResearchCase)
        .filter_by(user_id=user.id, stock_id=stock.id)
        .one_or_none()
    )
    if case is None:
        case = ResearchCase(user_id=user.id, stock_id=stock.id, state="researching")
        db_session.add(case)
        db_session.flush()
    revision_number = case.head_revision_number + 1
    revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=revision_number,
        case_state="researching",
        valuation_low=value,
        valuation_base=value,
        valuation_high=value,
        valuation_currency="USD",
        valuation_as_of_date=as_of_date,
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        created_by_user_id=user.id,
    )
    db_session.add(revision)
    db_session.flush()
    case.head_revision_number = revision_number
    case.version += 1
    db_session.flush()
    return revision


def test_put_fair_value_preserves_prior_period_and_demotes_only_same_day_slot(
    client, db_session, auth_headers
):
    user = _make_user(db_session)
    stock = _make_stock(db_session, "FVR")
    headers = auth_headers(user)

    today_et = datetime.now(timezone.utc).astimezone(ET).date()
    prior_revision = _make_valuation_revision(
        db_session,
        user=user,
        stock=stock,
        value=100.0,
        as_of_date=date(2026, 2, 1),
    )
    same_day_revision = _make_valuation_revision(
        db_session,
        user=user,
        stock=stock,
        value=110.0,
        as_of_date=today_et,
    )
    prior_period_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=100.0,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 2, 1),
        source_type="manual",
        source_ref_id=prior_revision.id,
        is_current=True,
    )
    same_day_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=110.0,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=today_et,
        source_type="manual",
        source_ref_id=same_day_revision.id,
        is_current=True,
    )
    db_session.add_all([prior_period_fact, same_day_fact])
    db_session.commit()

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=headers,
        json={"metric_key": FAIR_VALUE_KEY, "value_numeric": 125.0},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["metric_key"] == FAIR_VALUE_KEY
    assert payload["value_numeric"] == 125.0
    assert payload["is_current"] is True
    assert payload["research_case_id"] is not None
    assert payload["research_revision_id"] is not None

    facts = (
        db_session.query(MetricFact)
        .filter(MetricFact.user_id == user.id, MetricFact.stock_id == stock.id, MetricFact.metric_key == FAIR_VALUE_KEY)
        .order_by(MetricFact.created_at.asc())
        .all()
    )
    assert len(facts) == 3
    by_value = {fact.value_numeric: fact for fact in facts}
    assert by_value[100.0].is_current is True
    assert by_value[110.0].is_current is False
    assert by_value[125.0].is_current is True
    assert by_value[125.0].source_ref_id == payload["research_revision_id"]
    assert db_session.execute(
        text("SELECT current_manual_fact_has_exact_authority(:fact_id)"),
        {"fact_id": by_value[125.0].id},
    ).scalar_one() is True

    case = db_session.get(ResearchCase, payload["research_case_id"])
    revision = db_session.get(ResearchCaseRevision, payload["research_revision_id"])
    assert case is not None
    assert case.user_id == user.id
    assert case.stock_id == stock.id
    assert case.head_revision_number == 3
    assert revision is not None
    assert revision.case_id == case.id
    assert revision.valuation_low == revision.valuation_base == revision.valuation_high
    assert float(revision.valuation_base) == 125.0
    assert revision.valuation_currency == "USD"


def test_put_dcf_value_is_blocked_until_a_reviewed_valuation_method_exists(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "fairvalue-dcf@example.com")
    stock = _make_stock(db_session, "DCFJ")

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 150.0,
            "valuation_low": 120.0,
            "valuation_high": 180.0,
            "source": "dcf",
            "assumptions": [
                {
                    "source": "dcf",
                    "label": "DCF model inputs",
                    "discount_rate_pct": 10.0,
                    "growth_rate_pct": 6.0,
                }
            ],
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "analysis_method_unavailable",
        "analysis_kind": "valuation",
        "state": "unknown",
        "reason": "company_classification_missing",
        "policy_version": "analysis-method-gate-v1",
    }
    assert (
        db_session.query(ResearchCaseRevision)
        .join(ResearchCase, ResearchCase.id == ResearchCaseRevision.case_id)
        .filter(ResearchCase.user_id == user.id, ResearchCase.stock_id == stock.id)
        .count()
        == 0
    )


def test_put_fair_value_reopens_monitoring_case_for_explicit_review(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "fairvalue-review@example.com")
    stock = _make_stock(db_session, "REVW")
    pool = StockPool(user_id=user.id, name="Review candidates")
    db_session.add(pool)
    db_session.flush()
    db_session.add(
        PoolMembership(
            user_id=user.id,
            pool_id=pool.id,
            stock_id=stock.id,
            inclusion_type="manual",
        )
    )
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="watch",
        next_review_on=date(2026, 10, 1),
        head_revision_number=1,
    )
    db_session.add(case)
    db_session.flush()
    db_session.add(
        ResearchCaseRevision(
            case_id=case.id,
            revision_number=1,
            thesis="Original monitoring thesis",
            risks_json=[{"label": "Competition"}],
            evidence_json=[{"source_type": "user_note", "label": "Note", "claim": "Evidence"}],
            case_state="monitoring",
            valuation_low=90,
            valuation_base=100,
            valuation_high=110,
            valuation_currency="USD",
            valuation_as_of_date=date(2026, 7, 17),
            decision="watch",
            next_review_on=date(2026, 10, 1),
            snapshot_stock_id=stock.id,
            stock_ticker=stock.ticker,
            stock_company_name=stock.company_name,
            stock_exchange=stock.exchange,
            created_by_user_id=user.id,
        )
    )
    db_session.commit()

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 140.0,
            "valuation_low": 120.0,
            "valuation_high": 160.0,
            "source": "watchlist",
            "pool_id": pool.id,
        },
    )

    assert response.status_code == 200, response.text
    db_session.refresh(case)
    assert case.state == "researching"
    assert case.decision is None
    assert case.next_review_on is None
    latest = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert latest is not None
    assert latest.case_state == "researching"
    assert latest.decision is None


def test_put_fair_value_rejects_unknown_metric_key(client, db_session, auth_headers):
    user = _make_user(db_session, "fairvalue2@example.com")
    stock = _make_stock(db_session, "BAD")
    headers = auth_headers(user)

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=headers,
        json={"metric_key": "val.unknown", "value_numeric": 10.0},
    )
    assert resp.status_code == 400


def test_database_rejects_fair_value_without_exact_revision_authority(db_session):
    user = _make_user(db_session, "fairvalue-forgery@example.com")
    stock = _make_stock(db_session, "FVFG")
    forged = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=123.45,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 8, 28),
        source_type="manual",
        is_current=True,
    )
    db_session.add(forged)
    db_session.flush()
    with pytest.raises(DBAPIError, match="authorized user valuation"):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_database_rejects_isolated_current_fair_value_demotion(db_session):
    user = _make_user(db_session, "fairvalue-demotion@example.com")
    stock = _make_stock(db_session, "FVDEM")
    older_revision = _make_valuation_revision(
        db_session,
        user=user,
        stock=stock,
        value=100.0,
        as_of_date=date(2026, 1, 1),
    )
    latest_revision = _make_valuation_revision(
        db_session,
        user=user,
        stock=stock,
        value=200.0,
        as_of_date=date(2026, 2, 1),
    )
    older = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=100.0,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 1, 1),
        source_type="manual",
        source_ref_id=older_revision.id,
        is_current=True,
    )
    latest = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=200.0,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 2, 1),
        source_type="manual",
        source_ref_id=latest_revision.id,
        is_current=True,
    )
    db_session.add_all([older, latest])
    db_session.commit()

    db_session.execute(
        text("UPDATE metric_facts SET is_current = false WHERE id = :fact_id"),
        {"fact_id": latest.id},
    )
    with pytest.raises(
        DBAPIError,
        match="manual current fact demotion|authorized user valuation",
    ):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()

    assert db_session.get(MetricFact, latest.id).is_current is True


def test_manual_fact_history_rejects_value_mutation_and_normal_delete(db_session):
    user = _make_user(db_session, "manual-history@example.com")
    stock = _make_stock(db_session, "MVHI")
    revision = _make_valuation_revision(
        db_session,
        user=user,
        stock=stock,
        value=125.0,
        as_of_date=date(2026, 8, 28),
    )
    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=125.0,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 8, 28),
        source_type="manual",
        source_ref_id=revision.id,
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()
    fact_id = fact.id

    fact.value_numeric = 999.0
    with pytest.raises(
        DBAPIError, match="manual metric fact lineage and value are immutable"
    ):
        db_session.flush()
    db_session.rollback()

    retained = db_session.get(MetricFact, fact_id)
    assert retained is not None
    assert retained.value_numeric == 125.0
    db_session.delete(retained)
    with pytest.raises(DBAPIError, match="manual metric facts are retained lineage"):
        db_session.flush()
