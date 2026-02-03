from datetime import date

from app.models.users import User
from app.models.stocks import Stock
from app.models.facts import MetricFact


FAIR_VALUE_KEY = "val.fair_value"


def _make_user(db_session, email: str = "fairvalue@example.com") -> User:
    user = User(email=email)
    db_session.add(user)
    db_session.commit()
    return user


def _make_stock(db_session, ticker: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Inc")
    db_session.add(stock)
    db_session.commit()
    return stock


def test_put_fair_value_creates_new_current_fact(client, db_session):
    user = _make_user(db_session)
    stock = _make_stock(db_session, "FVR")

    old_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=100.0,
        unit="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 2, 1),
        source_type="manual",
        is_current=True,
    )
    db_session.add(old_fact)
    db_session.commit()

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts?user_id={user.id}",
        json={"metric_key": FAIR_VALUE_KEY, "value_numeric": 125.0},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["metric_key"] == FAIR_VALUE_KEY
    assert payload["value_numeric"] == 125.0
    assert payload["is_current"] is True

    facts = (
        db_session.query(MetricFact)
        .filter(MetricFact.user_id == user.id, MetricFact.stock_id == stock.id, MetricFact.metric_key == FAIR_VALUE_KEY)
        .order_by(MetricFact.created_at.asc())
        .all()
    )
    assert len(facts) == 2
    assert facts[0].is_current is False
    assert facts[1].is_current is True


def test_put_fair_value_rejects_unknown_metric_key(client, db_session):
    user = _make_user(db_session, "fairvalue2@example.com")
    stock = _make_stock(db_session, "BAD")

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts?user_id={user.id}",
        json={"metric_key": "val.unknown", "value_numeric": 10.0},
    )
    assert resp.status_code == 400
