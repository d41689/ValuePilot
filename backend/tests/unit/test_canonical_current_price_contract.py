from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.security import hash_password
from app.models.facts import MetricFact
from app.models.stocks import PoolMembership, Stock, StockPool, StockPrice
from app.models.users import User
from app.services.market_data_service import (
    ET,
    PRICE_FRESHNESS_POLICY_VERSION,
    compute_target_date,
    expected_session_on_or_before,
)


def _user(db_session, suffix: str) -> User:
    row = User(
        email=f"current-price-{suffix}@example.com",
        hashed_password=hash_password("TestPass123!"),
    )
    db_session.add(row)
    db_session.commit()
    return row


def _stock(db_session, ticker: str, *, active: bool = True) -> Stock:
    row = Stock(
        ticker=ticker,
        exchange="NASDAQ",
        market_country="US",
        company_name=f"{ticker} Incorporated",
        is_active=active,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _price(
    db_session,
    stock: Stock,
    *,
    price_date: date,
    source: str = "yfinance",
    currency: str | None = "USD",
    close: float = 100,
) -> StockPrice:
    row = StockPrice(
        stock_id=stock.id,
        price_date=price_date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1,
        source=source,
        currency=currency,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.commit()
    return row


def _authorize_yfinance(monkeypatch) -> None:
    from app.services import market_data_service

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "yfinance")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_SECONDARY", "none")
    monkeypatch.setattr(
        market_data_service.settings,
        "MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER",
        True,
    )


def _create_case(client, headers: dict[str, str], stock_id: int) -> int:
    response = client.post(
        "/api/v1/research/cases",
        headers=headers,
        json={
            "stock_id": stock_id,
            "origin": {
                "origin_type": "manual",
                "origin_key": f"current-price:{stock_id}",
                "source_version": "current-price-test-v1",
                "source_ref": {"test": True},
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["case"]["id"]


def _expected_target() -> date:
    return compute_target_date(datetime.now(timezone.utc).astimezone(ET))


@pytest.mark.parametrize(
    (
        "scenario",
        "expected_status",
        "expected_reason",
        "expected_value",
        "expected_mos",
        "expected_comparison_reason",
    ),
    [
        ("valid", "available", None, 100.0, 0.5, None),
        ("currency_mismatch", "available", None, 100.0, None, "currency_mismatch"),
        ("missing", "unavailable", "price_missing", None, None, "price_missing"),
        (
            "stale",
            "unavailable",
            "price_older_than_expected_session",
            None,
            None,
            "price_older_than_expected_session",
        ),
        (
            "unknown_currency",
            "unavailable",
            "price_currency_unavailable",
            None,
            None,
            "price_currency_unavailable",
        ),
        (
            "unauthorized",
            "unavailable",
            "source_unavailable",
            None,
            None,
            "source_unavailable",
        ),
    ],
)
def test_stock_watchlist_and_research_share_one_current_price_contract(
    client,
    db_session,
    auth_headers,
    monkeypatch,
    scenario: str,
    expected_status: str,
    expected_reason: str | None,
    expected_value: float | None,
    expected_mos: float | None,
    expected_comparison_reason: str | None,
):
    _authorize_yfinance(monkeypatch)
    user = _user(db_session, scenario)
    headers = auth_headers(user)
    stock = _stock(db_session, f"CP{scenario[:4].upper()}")
    pool = StockPool(user_id=user.id, name=f"{scenario} prices")
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
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="val.fair_value",
            value_numeric=200,
            unit="USD",
            currency="USD",
            period_type="AS_OF",
            period_end_date=date.today(),
            source_type="manual",
            is_current=True,
        )
    )
    db_session.commit()
    case_id = _create_case(client, headers, stock.id)

    target = _expected_target()
    if scenario != "missing":
        observed_date = target
        if scenario == "stale":
            previous = expected_session_on_or_before(
                stock.listing_exchange or stock.exchange,
                target - timedelta(days=1),
            )
            assert previous.session_date is not None
            observed_date = previous.session_date
        _price(
            db_session,
            stock,
            price_date=observed_date,
            source="unapproved-feed" if scenario == "unauthorized" else "yfinance",
            currency=(
                None
                if scenario == "unknown_currency"
                else "CAD"
                if scenario == "currency_mismatch"
                else "USD"
            ),
        )

    summary_response = client.get(
        f"/api/v1/stocks/by_ticker/{stock.ticker}", headers=headers
    )
    watchlist_response = client.get(
        f"/api/v1/stock_pools/{pool.id}/members", headers=headers
    )
    workspace_response = client.get(
        f"/api/v1/research/cases/{case_id}/workspace", headers=headers
    )
    assert summary_response.status_code == 200, summary_response.text
    assert watchlist_response.status_code == 200, watchlist_response.text
    assert workspace_response.status_code == 200, workspace_response.text

    summary = summary_response.json()
    watchlist = watchlist_response.json()[0]
    workspace = workspace_response.json()
    canonical = summary["current_price"]
    assert watchlist["current_price"] == canonical
    assert workspace["current_price"] == canonical
    assert canonical["status"] == expected_status
    assert canonical["value"] == expected_value
    assert canonical["reason_code"] == expected_reason
    assert canonical["freshness_policy_version"] == PRICE_FRESHNESS_POLICY_VERSION
    assert canonical["as_of_mode"] == "latest_completed_session"
    assert watchlist["mos"] == expected_mos
    assert watchlist["price_comparison_reason"] == expected_comparison_reason
    assert watchlist["discount_to_reference"] is None


def test_report_price_is_a_dated_reference_not_a_current_price(
    client, db_session, auth_headers, monkeypatch
):
    _authorize_yfinance(monkeypatch)
    user = _user(db_session, "report-reference")
    stock = _stock(db_session, "CPREF")
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="mkt.price",
            value_numeric=54.52,
            unit="USD",
            currency="USD",
            period_type="AS_OF",
            period_end_date=date(2026, 1, 9),
            source_type="parsed",
            is_current=True,
        )
    )
    _price(db_session, stock, price_date=_expected_target(), close=100)

    response = client.get(
        f"/api/v1/stocks/by_ticker/{stock.ticker}", headers=auth_headers(user)
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "price" not in payload
    assert "latest_price" not in payload
    assert payload["current_price"]["value"] == 100
    assert payload["report_price_reference"]["value"] == 54.52
    assert payload["report_price_reference"]["as_of_date"] == "2026-01-09"
    assert payload["report_price_reference"]["currency"] == "USD"
    assert payload["report_price_reference"]["label"] == "report_reference"


def test_inactive_stock_current_price_fails_closed(db_session):
    from app.services.market_data_service import read_current_eod_price

    stock = _stock(db_session, "CPOLD", active=False)
    _price(db_session, stock, price_date=_expected_target())

    result = read_current_eod_price(
        db_session,
        stock=stock,
        source_priority=("yfinance",),
    )

    assert result.status == "unavailable"
    assert result.current_value is None
    assert result.reason_code == "stock_inactive"


def test_authorized_source_wins_same_session_over_unauthorized_source(
    db_session, monkeypatch
):
    from app.services.market_data_service import read_current_eod_price

    _authorize_yfinance(monkeypatch)
    stock = _stock(db_session, "CPAUTH")
    target = _expected_target()
    selected = _price(
        db_session, stock, price_date=target, source="yfinance", close=100
    )
    _price(
        db_session, stock, price_date=target, source="twelvedata", close=999
    )

    result = read_current_eod_price(db_session, stock=stock)

    assert result.status == "available"
    assert result.price_id == selected.id
    assert result.current_value == 100


def test_non_currency_valuation_unit_blocks_comparison(
    client, db_session, auth_headers, monkeypatch
):
    _authorize_yfinance(monkeypatch)
    user = _user(db_session, "invalid-valuation-currency")
    stock = _stock(db_session, "CPUNIT")
    pool = StockPool(user_id=user.id, name="invalid valuation currency")
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
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="val.fair_value",
            value_numeric=200,
            unit="currency_per_share",
            currency=None,
            period_type="AS_OF",
            period_end_date=date.today(),
            source_type="manual",
            is_current=True,
        )
    )
    db_session.commit()
    _price(db_session, stock, price_date=_expected_target())

    response = client.get(
        f"/api/v1/stock_pools/{pool.id}/members", headers=auth_headers(user)
    )

    assert response.status_code == 200, response.text
    row = response.json()[0]
    assert row["fair_value_currency"] is None
    assert row["mos"] is None
    assert row["price_comparison_reason"] == "currency_mismatch"
