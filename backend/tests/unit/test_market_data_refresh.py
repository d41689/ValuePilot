from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.users import User
from app.models.institutions import Filing13F, Holding13F, InstitutionManager
from app.models.stocks import Stock, StockPrice


ET = ZoneInfo("America/New_York")


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = []

    def fetch_daily_bar(self, *, ticker: str, exchange: str, target_date: date):
        self.calls.append((ticker, exchange, target_date))
        return {
            "open": 100.0,
            "high": 110.0,
            "low": 95.0,
            "close": 105.0,
            "volume": 1_000_000,
            "adj_close": None,
        }


def _make_user_stock(db_session):
    user = User(email="marketdata@example.com")
    db_session.add(user)
    db_session.commit()

    stock = Stock(ticker="AAPL", exchange="NDQ", company_name="Apple")
    db_session.add(stock)
    db_session.commit()
    return user, stock


def _make_manager(db_session, *, name: str = "13F Fund", superinvestor: bool = True):
    manager = InstitutionManager(
        cik=f"9{name.lower().replace(' ', '')[:8]}",
        legal_name=name,
        display_name=name,
        name_normalized=name.lower(),
        match_status="confirmed",
        is_superinvestor=superinvestor,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _make_filing_holding(db_session, manager, stock, *, period: date, accession: str):
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        period_of_report=period,
        filed_at=period,
        form_type="13F-HR",
        is_latest_for_period=True,
        reported_total_value_thousands=100_000,
        computed_total_value_thousands=100_000,
    )
    db_session.add(filing)
    db_session.flush()
    holding = Holding13F(
        filing_id=filing.id,
        row_fingerprint=f"{accession}-{stock.ticker}",
        cusip=f"{stock.id:09d}"[-9:],
        issuer_name=stock.company_name,
        title_of_class="COM",
        value_thousands=10_000,
        shares=1000,
        share_type="SH",
        stock_id=stock.id,
    )
    db_session.add(holding)
    db_session.flush()
    return filing, holding


def test_compute_target_date_weekend(db_session):
    from app.services.market_data_service import compute_target_date

    saturday = datetime(2026, 2, 7, 12, 0, tzinfo=ET)
    target = compute_target_date(saturday)
    assert target.weekday() == 4  # Friday


def test_compute_target_date_before_close_uses_previous_business_day(db_session):
    from app.services.market_data_service import compute_target_date

    monday_morning = datetime(2026, 2, 2, 10, 0, tzinfo=ET)
    target = compute_target_date(monday_morning)
    assert target.weekday() == 4  # Friday


def test_refresh_inserts_when_missing(db_session):
    from app.services.market_data_service import MarketDataService

    _, stock = _make_user_stock(db_session)
    provider = FakeProvider()

    now_et = datetime(2026, 2, 4, 18, 0, tzinfo=ET)
    now_utc = now_et.astimezone(timezone.utc)

    service = MarketDataService(db_session, provider=provider, throttle_minutes=0)
    results = service.refresh_stock_prices([stock.id], reason="test", now=now_utc)

    assert results[0]["status"] == "refreshed"
    assert results[0]["target_date"]

    prices = (
        db_session.query(StockPrice)
        .filter(StockPrice.stock_id == stock.id)
        .all()
    )
    assert len(prices) == 1
    assert prices[0].close == 105.0


def test_refresh_confirm_after_close_once(db_session):
    from app.services.market_data_service import MarketDataService

    _, stock = _make_user_stock(db_session)
    provider = FakeProvider()

    target_date = date(2026, 2, 4)
    created_before_close = datetime(2026, 2, 4, 15, 0, tzinfo=ET).astimezone(timezone.utc)
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=target_date,
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1_000,
            source="seed",
            created_at=created_before_close,
        )
    )
    db_session.commit()

    now_et = datetime(2026, 2, 4, 18, 0, tzinfo=ET)
    now_utc = now_et.astimezone(timezone.utc)

    service = MarketDataService(db_session, provider=provider, throttle_minutes=0)
    results = service.refresh_stock_prices([stock.id], reason="test", now=now_utc)
    assert results[0]["status"] == "refreshed"

    prices = (
        db_session.query(StockPrice)
        .filter(StockPrice.stock_id == stock.id, StockPrice.price_date == target_date)
        .order_by(StockPrice.created_at.asc())
        .all()
    )
    assert len(prices) == 2

    # Second attempt should skip (latest created_at >= close buffer)
    later_utc = (now_et + timedelta(minutes=20)).astimezone(timezone.utc)
    results = service.refresh_stock_prices([stock.id], reason="test", now=later_utc)
    assert results[0]["status"] == "skipped"


def test_refresh_throttled(db_session):
    from app.services.market_data_service import MarketDataService

    _, stock = _make_user_stock(db_session)
    provider = FakeProvider()

    now_utc = datetime(2026, 2, 4, 18, 0, tzinfo=timezone.utc)
    recent = now_utc - timedelta(minutes=5)
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=date(2026, 2, 3),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1_000,
            source="seed",
            created_at=recent,
        )
    )
    db_session.commit()

    service = MarketDataService(db_session, provider=provider, throttle_minutes=10)
    results = service.refresh_stock_prices([stock.id], reason="test", now=now_utc)
    assert results[0]["status"] == "skipped"
    assert results[0]["reason"] == "throttled"


def test_refresh_endpoint_returns_results(client, db_session, monkeypatch, auth_headers):
    from app.services import market_data_service

    user, stock = _make_user_stock(db_session)
    provider = FakeProvider()

    def _fake_provider():
        return provider

    monkeypatch.setattr(market_data_service, "get_default_provider", _fake_provider)

    resp = client.post(
        "/api/v1/stocks/prices/refresh",
        headers=auth_headers(user),
        json={"stock_ids": [stock.id], "reason": "pool_page_open"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["stock_id"] == stock.id
    assert body[0]["status"] in {"refreshed", "skipped", "failed"}


def test_backfill_13f_linked_period_prices_skips_existing_and_uses_period_business_day(db_session):
    from app.services.market_data_service import MarketDataService

    manager = _make_manager(db_session)
    manager_2 = _make_manager(db_session, name="13F Fund Two")
    apple = Stock(ticker="AAPL", exchange="NDQ", company_name="Apple")
    microsoft = Stock(ticker="MSFT", exchange="NDQ", company_name="Microsoft")
    db_session.add_all([apple, microsoft])
    db_session.flush()
    period = date(2024, 3, 31)  # Sunday; target price date should be Friday.
    target_date = date(2024, 3, 29)
    _make_filing_holding(db_session, manager, apple, period=period, accession="backfill-a")
    _make_filing_holding(db_session, manager_2, microsoft, period=period, accession="backfill-m")
    db_session.add(
        StockPrice(
            stock_id=apple.id,
            price_date=target_date,
            open=90.0,
            high=95.0,
            low=89.0,
            close=94.0,
            volume=1000,
            source="seed",
        )
    )
    db_session.commit()

    provider = FakeProvider()
    service = MarketDataService(db_session, provider=provider, throttle_minutes=0)
    results = service.backfill_13f_linked_period_prices(
        periods=[period],
        reason="oracles_lens_test",
        now=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert sorted((row["ticker"], row["status"], row["target_date"]) for row in results) == [
        ("AAPL", "skipped", "2024-03-29"),
        ("MSFT", "refreshed", "2024-03-29"),
    ]
    assert provider.calls == [("MSFT", "NDQ", target_date)]
    microsoft_price = (
        db_session.query(StockPrice)
        .filter(StockPrice.stock_id == microsoft.id, StockPrice.price_date == target_date)
        .one()
    )
    assert microsoft_price.close == 105.0
    assert microsoft_price.source == "fake"


def test_backfill_13f_linked_period_prices_excludes_non_superinvestors_by_default(db_session):
    from app.services.market_data_service import MarketDataService

    manager = _make_manager(db_session, name="Index Holder", superinvestor=False)
    stock = Stock(ticker="SPY", exchange="NYSE", company_name="SPDR S&P 500 ETF")
    db_session.add(stock)
    db_session.flush()
    _make_filing_holding(
        db_session,
        manager,
        stock,
        period=date(2024, 6, 30),
        accession="non-superinvestor",
    )
    db_session.commit()

    provider = FakeProvider()
    service = MarketDataService(db_session, provider=provider, throttle_minutes=0)
    results = service.backfill_13f_linked_period_prices(periods=[date(2024, 6, 30)], reason="test")

    assert results == []
    assert provider.calls == []
