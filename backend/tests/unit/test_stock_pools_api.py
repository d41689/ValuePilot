from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.users import User
from app.models.stocks import Stock, StockPool, PoolMembership, StockPrice
from app.models.facts import MetricFact
from app.core.security import hash_password


ET = ZoneInfo("America/New_York")
FAIR_VALUE_KEY = "val.fair_value"
TARGET_KEY = "target.price_18m.mid"


def _make_user(db_session, email: str = "watchlist@example.com") -> User:
    user = User(email=email, hashed_password=hash_password("TestPass123!"))
    db_session.add(user)
    db_session.commit()
    return user


def _make_stock(db_session, ticker: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Inc")
    db_session.add(stock)
    db_session.commit()
    return stock


def test_stock_pools_crud_and_membership(client, db_session, auth_headers):
    user = _make_user(db_session)
    stock = _make_stock(db_session, "AAPL")
    headers = auth_headers(user)

    resp = client.get("/api/v1/stock_pools", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post(
        "/api/v1/stock_pools",
        headers=headers,
        json={"name": "Default"},
    )
    assert resp.status_code == 200
    pool = resp.json()
    assert pool["name"] == "Default"

    resp = client.get("/api/v1/stock_pools", headers=headers)
    assert resp.status_code == 200
    pools = resp.json()
    assert len(pools) == 1

    resp = client.post(
        f"/api/v1/stock_pools/{pool['id']}/members",
        headers=headers,
        json={"stock_id": stock.id},
    )
    assert resp.status_code == 200
    membership = resp.json()
    assert membership["stock"]["ticker"] == "AAPL"

    resp = client.post(
        f"/api/v1/stock_pools/{pool['id']}/members",
        headers=headers,
        json={"stock_id": stock.id},
    )
    assert resp.status_code == 409

    resp = client.delete(
        f"/api/v1/stock_pools/{pool['id']}",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_pool_members_include_price_and_fair_value(client, db_session, monkeypatch, auth_headers):
    from app.api.v1.endpoints import stock_pools as stock_pools_endpoint

    user = _make_user(db_session, "watchlist2@example.com")
    headers = auth_headers(user)
    pool = StockPool(user_id=user.id, name="Value", description=None)
    db_session.add(pool)
    db_session.commit()

    stock_a = _make_stock(db_session, "AOS")
    stock_b = _make_stock(db_session, "MSFT")

    db_session.add(
        PoolMembership(
            user_id=user.id,
            pool_id=pool.id,
            stock_id=stock_a.id,
            inclusion_type="manual",
            rule_id=None,
        )
    )
    db_session.add(
        PoolMembership(
            user_id=user.id,
            pool_id=pool.id,
            stock_id=stock_b.id,
            inclusion_type="manual",
            rule_id=None,
        )
    )

    target_date = date(2026, 2, 3)
    prev_date = date(2026, 2, 2)
    monkeypatch.setattr(
        stock_pools_endpoint,
        "compute_target_date",
        lambda now_et, **kwargs: target_date,
    )

    db_session.add_all(
        [
            StockPrice(
                stock_id=stock_a.id,
                price_date=target_date,
                open=99.0,
                high=101.0,
                low=98.0,
                close=100.0,
                volume=1_000,
                source="seed",
                created_at=datetime(2026, 2, 3, 21, 0, tzinfo=timezone.utc),
            ),
            StockPrice(
                stock_id=stock_a.id,
                price_date=prev_date,
                open=97.0,
                high=99.0,
                low=96.0,
                close=98.0,
                volume=1_000,
                source="seed",
                created_at=datetime(2026, 2, 2, 21, 0, tzinfo=timezone.utc),
            ),
            StockPrice(
                stock_id=stock_b.id,
                price_date=target_date,
                open=49.0,
                high=51.0,
                low=48.0,
                close=50.0,
                volume=1_000,
                source="seed",
                created_at=datetime(2026, 2, 3, 21, 0, tzinfo=timezone.utc),
            ),
            StockPrice(
                stock_id=stock_b.id,
                price_date=prev_date,
                open=54.0,
                high=56.0,
                low=53.0,
                close=55.0,
                volume=1_000,
                source="seed",
                created_at=datetime(2026, 2, 2, 21, 0, tzinfo=timezone.utc),
            ),
        ]
    )

    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock_a.id,
            metric_key=FAIR_VALUE_KEY,
            value_numeric=200.0,
            unit="USD",
            period_type="AS_OF",
            period_end_date=target_date,
            source_type="manual",
            is_current=True,
        )
    )
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock_a.id,
            metric_key=TARGET_KEY,
            value_numeric=180.0,
            unit="USD",
            period_type="TARGET_HORIZON",
            period_end_date=target_date,
            source_type="parsed",
            is_current=True,
        )
    )
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock_b.id,
            metric_key=TARGET_KEY,
            value_numeric=80.0,
            unit="USD",
            period_type="TARGET_HORIZON",
            period_end_date=target_date,
            source_type="parsed",
            is_current=True,
        )
    )
    db_session.commit()

    resp = client.get(f"/api/v1/stock_pools/{pool.id}/members", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2

    row_a = next(row for row in rows if row["ticker"] == "AOS")
    assert row_a["price"] == pytest.approx(100.0)
    assert row_a["delta_today"] == pytest.approx(2.0)
    assert row_a["fair_value"] == pytest.approx(200.0)
    assert row_a["fair_value_source"] == "manual"
    assert row_a["mos"] == pytest.approx(0.5)

    row_b = next(row for row in rows if row["ticker"] == "MSFT")
    assert row_b["price"] == pytest.approx(50.0)
    assert row_b["delta_today"] == pytest.approx(-5.0)
    assert row_b["fair_value"] == pytest.approx(80.0)
    assert row_b["fair_value_source"] == TARGET_KEY
    assert row_b["mos"] == pytest.approx(0.375)
