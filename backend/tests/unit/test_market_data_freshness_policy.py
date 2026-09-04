from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event

from app.models.stocks import Stock, StockPrice


class BatchProvider:
    name = "licensed_fixture"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], date]] = []

    def fetch_daily(self, symbols: list[str], target_date: date):
        self.calls.append((symbols, target_date))
        return {
            symbol: {
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": 105.0,
                "volume": 1_000_000,
                "currency": "USD",
                "source": self.name,
            }
            for symbol in symbols
        }


def _stock(db_session, ticker: str, *, exchange: str = "NASDAQ", active: bool = True):
    stock = Stock(
        ticker=ticker,
        exchange=exchange,
        market_country="US" if exchange != "UNKNOWN" else "UNKNOWN",
        company_name=f"{ticker} Corp",
        is_active=active,
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _price(
    db_session,
    stock: Stock,
    *,
    price_date: date,
    source: str,
    currency: str | None,
    close: float,
    created_at: datetime,
):
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
        created_at=created_at,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_expected_us_session_observes_exchange_holiday():
    from app.services.market_data_service import expected_session_on_or_before

    # Friday 2026-07-03 is the observed Independence Day market holiday.
    result = expected_session_on_or_before("NASDAQ", date(2026, 7, 4))

    assert result.calendar_code == "XNYS"
    assert result.session_date == date(2026, 7, 2)
    assert result.policy_version == "us-equity-calendar-v1.0"


def test_unknown_exchange_never_claims_freshness(db_session):
    from app.services.market_data_service import read_canonical_eod_price

    stock = _stock(db_session, "MYST", exchange="UNKNOWN")
    _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=10,
        created_at=datetime(2026, 7, 17, 22, tzinfo=timezone.utc),
    )

    result = read_canonical_eod_price(
        db_session,
        stock=stock,
        as_of=date(2026, 7, 20),
        source_priority=("licensed_fixture",),
    )

    assert result.freshness_state == "unknown_freshness"
    assert result.reason_code == "calendar_mapping_unavailable"
    assert result.expected_session_date is None


def test_canonical_read_prefers_source_priority_for_same_session(db_session):
    from app.services.market_data_service import read_canonical_eod_price

    stock = _stock(db_session, "AAPL")
    observed_at = datetime(2026, 7, 17, 22, tzinfo=timezone.utc)
    _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="yfinance",
        currency="USD",
        close=201,
        created_at=observed_at,
    )
    preferred = _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="twelvedata",
        currency="USD",
        close=200,
        created_at=observed_at,
    )

    result = read_canonical_eod_price(
        db_session,
        stock=stock,
        as_of=date(2026, 7, 20),
        source_priority=("twelvedata", "yfinance"),
    )

    assert result.price_id == preferred.id
    assert result.close == 200
    assert result.source == "twelvedata"
    assert result.freshness_state == "fresh"
    assert result.expected_session_date == date(2026, 7, 17)


def test_canonical_read_excludes_observations_ingested_after_knowledge_cutoff(
    db_session,
):
    from app.services.market_data_service import read_canonical_eod_price

    stock = _stock(db_session, "PIT")
    known = _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=100,
        created_at=datetime(2026, 7, 17, 22, tzinfo=timezone.utc),
    )
    _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=999,
        created_at=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
    )

    result = read_canonical_eod_price(
        db_session,
        stock=stock,
        as_of=date(2026, 7, 17),
        include_as_of_session=True,
        knowledge_cutoff=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
        source_priority=("licensed_fixture",),
    )

    assert result.price_id == known.id
    assert result.close == 100


def test_canonical_point_read_preserves_created_at_microseconds_before_id(db_session):
    from app.services.market_data_service import read_canonical_eod_price

    stock = _stock(db_session, "POINTUS")
    newer_lower_id = _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=200,
        created_at=datetime(2026, 7, 17, 22, 0, 0, 900000, tzinfo=timezone.utc),
    )
    older_higher_id = _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=100,
        created_at=datetime(2026, 7, 17, 22, 0, 0, 100000, tzinfo=timezone.utc),
    )
    assert newer_lower_id.id < older_higher_id.id

    result = read_canonical_eod_price(
        db_session,
        stock=stock,
        as_of=date(2026, 7, 20),
        source_priority=("licensed_fixture",),
    )

    assert result.price_id == newer_lower_id.id
    assert result.current_value == 200


def test_canonical_series_excludes_late_inserted_history(db_session):
    from app.services.market_data_service import read_canonical_eod_series

    stock = _stock(db_session, "SERIESPIT")
    known = _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=100,
        created_at=datetime(2026, 7, 17, 22, tzinfo=timezone.utc),
    )
    _price(
        db_session,
        stock,
        price_date=date(2026, 7, 16),
        source="licensed_fixture",
        currency="USD",
        close=1,
        created_at=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
    )

    rows = read_canonical_eod_series(
        db_session,
        stock_ids=[stock.id],
        through=date(2026, 7, 17),
        knowledge_cutoff=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
        source_priority=("licensed_fixture",),
    )[stock.id]

    assert [row.id for row in rows] == [known.id]


def test_canonical_series_preserves_created_at_microseconds_before_id(db_session):
    from app.services.market_data_service import read_canonical_eod_series

    stock = _stock(db_session, "SERIESUS")
    newer_lower_id = _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=200,
        created_at=datetime(2026, 7, 17, 22, 0, 0, 900000, tzinfo=timezone.utc),
    )
    older_higher_id = _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency="USD",
        close=100,
        created_at=datetime(2026, 7, 17, 22, 0, 0, 100000, tzinfo=timezone.utc),
    )
    assert newer_lower_id.id < older_higher_id.id

    rows = read_canonical_eod_series(
        db_session,
        stock_ids=[stock.id],
        through=date(2026, 7, 17),
        knowledge_cutoff=datetime(2026, 7, 17, 23, tzinfo=timezone.utc),
        source_priority=("licensed_fixture",),
    )[stock.id]

    assert [row.id for row in rows] == [newer_lower_id.id]
    assert float(rows[0].close) == 200


def test_batch_point_current_and_context_readers_are_constant_query_and_one_clock(
    db_session, monkeypatch
):
    from app.services import market_data_service
    from app.services.market_data_service import (
        read_canonical_eod_prices,
        read_current_eod_contexts,
        read_current_eod_prices,
    )

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "yfinance")
    monkeypatch.setattr(
        market_data_service.settings,
        "MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER",
        True,
    )
    before_close = datetime(2026, 7, 20, 20, 29, tzinfo=timezone.utc)
    after_close = datetime(2026, 7, 20, 20, 31, tzinfo=timezone.utc)
    stocks = [_stock(db_session, f"B{i:03d}") for i in range(101)]
    for stock in stocks:
        _price(
            db_session,
            stock,
            price_date=date(2026, 7, 17),
            source="yahoo",
            currency="USD",
            close=100,
            created_at=datetime(2026, 7, 17, 21, tzinfo=timezone.utc),
        )
        _price(
            db_session,
            stock,
            price_date=date(2026, 7, 20),
            source="yfinance",
            currency="USD",
            close=101,
            created_at=datetime(2026, 7, 20, 20, 30, 30, tzinfo=timezone.utc),
        )

    statements: list[str] = []
    connection = db_session.connection()

    def capture(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        points = read_canonical_eod_prices(
            db_session,
            stocks=stocks,
            as_of=date(2026, 7, 17),
            include_as_of_session=True,
            knowledge_cutoff=before_close,
        )
        point_queries = len(statements)
        statements.clear()
        current_before = read_current_eod_prices(
            db_session,
            stocks=stocks,
            evaluated_at=before_close,
        )
        current_queries = len(statements)
        statements.clear()
        contexts = read_current_eod_contexts(
            db_session,
            stocks=stocks,
            evaluated_at=after_close,
            history_days=370,
            required_currency_by_stock_id={stock.id: "USD" for stock in stocks},
        )
        context_queries = len(statements)
    finally:
        event.remove(connection, "before_cursor_execute", capture)

    assert point_queries == 1
    assert current_queries == 1
    assert context_queries == 2
    assert len(points) == len(current_before) == len(contexts) == 101
    assert {item.as_of_date for item in current_before.values()} == {date(2026, 7, 20)}
    assert {item.expected_session_date for item in current_before.values()} == {
        date(2026, 7, 17)
    }
    assert {item.current_price.as_of_date for item in contexts.values()} == {
        date(2026, 7, 20)
    }
    assert {item.current_price.expected_session_date for item in contexts.values()} == {
        date(2026, 7, 20)
    }
    assert {item.current_price.current_value for item in contexts.values()} == {101}


def test_missing_currency_is_typed_and_never_fresh(db_session):
    from app.services.market_data_service import read_canonical_eod_price

    stock = _stock(db_session, "MSFT")
    _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="legacy",
        currency=None,
        close=500,
        created_at=datetime(2026, 7, 17, 22, tzinfo=timezone.utc),
    )

    result = read_canonical_eod_price(
        db_session,
        stock=stock,
        as_of=date(2026, 7, 20),
        source_priority=("legacy",),
    )

    assert result.freshness_state == "unknown_freshness"
    assert result.reason_code == "price_currency_unavailable"


@pytest.mark.parametrize("currency", ["ZZZ", "XAU", "XDR", "CLF"])
def test_non_monetary_currency_is_typed_and_never_fresh(db_session, currency):
    from app.services.market_data_service import read_canonical_eod_price

    stock = _stock(db_session, "BADCCY")
    _price(
        db_session,
        stock,
        price_date=date(2026, 7, 17),
        source="licensed_fixture",
        currency=currency,
        close=100,
        created_at=datetime(2026, 7, 17, 22, tzinfo=timezone.utc),
    )

    result = read_canonical_eod_price(
        db_session,
        stock=stock,
        as_of=date(2026, 7, 20),
        source_priority=("licensed_fixture",),
    )

    assert result.status == "unavailable"
    assert result.current_value is None
    assert result.currency is None
    assert result.freshness_state == "unknown_freshness"
    assert result.reason_code == "price_currency_unavailable"


def test_refresh_batches_eligible_stocks_and_persists_validated_currency(db_session):
    from app.services.market_data_service import MarketDataService

    apple = _stock(db_session, "AAPL")
    microsoft = _stock(db_session, "MSFT")
    inactive = _stock(db_session, "OLD", active=False)
    provider = BatchProvider()
    service = MarketDataService(db_session, provider=provider, throttle_minutes=0)

    result = service.refresh_stock_prices(
        [apple.id, microsoft.id, inactive.id, apple.id],
        reason="coverage_queue",
        now=datetime(2026, 7, 20, 23, tzinfo=timezone.utc),
    )

    assert provider.calls == [(["AAPL", "MSFT"], date(2026, 7, 20))]
    by_stock = {row["stock_id"]: row for row in result}
    assert by_stock[apple.id]["status"] == "refreshed"
    assert by_stock[microsoft.id]["status"] == "refreshed"
    assert by_stock[inactive.id] == {
        "stock_id": inactive.id,
        "status": "blocked",
        "reason": "stock_inactive",
        "target_date": None,
    }
    rows = (
        db_session.query(StockPrice)
        .filter(StockPrice.stock_id.in_([apple.id, microsoft.id]))
        .all()
    )
    assert len(rows) == 2
    assert {row.currency for row in rows} == {"USD"}


def test_provider_payload_without_currency_is_rejected(db_session):
    from app.services.market_data_service import MarketDataService

    class MissingCurrencyProvider(BatchProvider):
        def fetch_daily(self, symbols: list[str], target_date: date):
            payload = super().fetch_daily(symbols, target_date)
            for row in payload.values():
                row.pop("currency")
            return payload

    stock = _stock(db_session, "NVDA")
    result = MarketDataService(
        db_session,
        provider=MissingCurrencyProvider(),
        throttle_minutes=0,
    ).refresh_stock_prices(
        [stock.id],
        reason="coverage_queue",
        now=datetime(2026, 7, 20, 23, tzinfo=timezone.utc),
    )

    assert result[0]["status"] == "failed"
    assert result[0]["reason"] == "provider_currency_missing"
    assert db_session.query(StockPrice).filter_by(stock_id=stock.id).count() == 0


def test_provider_payload_with_non_iso_currency_is_rejected(db_session):
    from app.services.market_data_service import MarketDataService

    class NonIsoCurrencyProvider(BatchProvider):
        def fetch_daily(self, symbols: list[str], target_date: date):
            payload = super().fetch_daily(symbols, target_date)
            for row in payload.values():
                row["currency"] = "ZZZ"
            return payload

    stock = _stock(db_session, "BADWRITE")
    result = MarketDataService(
        db_session,
        provider=NonIsoCurrencyProvider(),
        throttle_minutes=0,
    ).refresh_stock_prices(
        [stock.id],
        reason="coverage_queue",
        now=datetime(2026, 7, 20, 23, tzinfo=timezone.utc),
    )

    assert result[0]["status"] == "failed"
    assert result[0]["reason"] == "provider_currency_missing"
    assert db_session.query(StockPrice).filter_by(stock_id=stock.id).count() == 0


def test_provider_selection_fails_closed_without_explicit_authorization(monkeypatch):
    from app.services import market_data_service

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "yfinance")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_SECONDARY", "none")
    monkeypatch.setattr(
        market_data_service.settings,
        "MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER",
        False,
    )
    monkeypatch.setattr(
        market_data_service.settings,
        "MARKET_DATA_COMMERCIAL_ENABLED",
        False,
    )

    provider = market_data_service.get_default_provider()

    assert provider.name == "unconfigured"


def test_configured_commercial_provider_requires_key_and_authorization(monkeypatch):
    from app.services import market_data_service

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "twelvedata")
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_SECONDARY", "none")
    monkeypatch.setattr(market_data_service.settings, "TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(
        market_data_service.settings,
        "MARKET_DATA_COMMERCIAL_ENABLED",
        True,
    )

    provider = market_data_service.get_default_provider()

    assert provider.name == "twelvedata"


def test_supported_equity_probe_fetches_persists_reads_and_classifies_fresh(db_session):
    """Deterministic Phase-1 success probe: a configured adapter path cannot
    pass merely by returning `blocked` for every stock.
    """
    from app.services.market_data_service import (
        MarketDataService,
        read_canonical_eod_price,
    )

    stock = _stock(db_session, "PROBE")
    provider = BatchProvider()
    refresh = MarketDataService(
        db_session, provider=provider, throttle_minutes=0
    ).refresh_stock_prices(
        [stock.id],
        reason="configured_provider_probe",
        now=datetime(2026, 7, 20, 23, tzinfo=timezone.utc),
    )
    canonical = read_canonical_eod_price(
        db_session,
        stock=stock,
        as_of=date(2026, 7, 21),
        source_priority=("licensed_fixture",),
    )

    assert refresh[0]["status"] == "refreshed"
    assert refresh[0]["currency"] == "USD"
    assert canonical.close == 105
    assert canonical.currency == "USD"
    assert canonical.price_date == date(2026, 7, 20)
    assert canonical.freshness_state == "fresh"
