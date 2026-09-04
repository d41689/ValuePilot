from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event

from app.models.users import User
from app.models.stocks import Stock, StockPool, PoolMembership, StockPrice
from app.models.facts import MetricFact
from app.core.security import hash_password


ET = ZoneInfo("America/New_York")
FAIR_VALUE_KEY = "val.fair_value"
TARGET_KEY = "target.price_18m.mid"
PIOTROSKI_TOTAL_KEY = "score.piotroski.total"


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


def _piotroski_total_fact(
    user_id: int,
    stock_id: int,
    year: int,
    score: float | None,
    *,
    fact_nature: str = "actual",
    partial_score: int | None = None,
    max_available_score: int | None = None,
) -> MetricFact:
    value_json = {
        "status": "partial" if score is None else "calculated",
        "variant": "standard",
        "fiscal_year": year,
        "fact_nature": fact_nature,
    }
    if partial_score is not None:
        value_json["partial_score"] = partial_score
    if max_available_score is not None:
        value_json["max_available_score"] = max_available_score
        value_json["available_indicators"] = max_available_score
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=PIOTROSKI_TOTAL_KEY,
        value_numeric=score,
        value_json=value_json,
        unit="score_total",
        period_type="FY",
        period_end_date=date(year, 12, 31),
        source_type="calculated",
        is_current=True,
    )


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


def test_overview_members_union_deduplicates_and_scopes_to_user(client, db_session, auth_headers):
    user = _make_user(db_session, "overview@example.com")
    other_user = _make_user(db_session, "other-overview@example.com")
    headers = auth_headers(user)

    pool_a = StockPool(user_id=user.id, name="Core", description=None)
    pool_b = StockPool(user_id=user.id, name="Ideas", description=None)
    other_pool = StockPool(user_id=other_user.id, name="Other", description=None)
    db_session.add_all([pool_a, pool_b, other_pool])
    db_session.commit()

    stock_a = _make_stock(db_session, "AAPL")
    stock_b = _make_stock(db_session, "MSFT")
    stock_c = _make_stock(db_session, "FICO")
    other_stock = _make_stock(db_session, "NVDA")

    db_session.add_all(
        [
            PoolMembership(
                user_id=user.id,
                pool_id=pool_a.id,
                stock_id=stock_a.id,
                inclusion_type="manual",
                rule_id=None,
            ),
            PoolMembership(
                user_id=user.id,
                pool_id=pool_a.id,
                stock_id=stock_b.id,
                inclusion_type="manual",
                rule_id=None,
            ),
            PoolMembership(
                user_id=user.id,
                pool_id=pool_b.id,
                stock_id=stock_b.id,
                inclusion_type="manual",
                rule_id=None,
            ),
            PoolMembership(
                user_id=user.id,
                pool_id=pool_b.id,
                stock_id=stock_c.id,
                inclusion_type="manual",
                rule_id=None,
            ),
            PoolMembership(
                user_id=other_user.id,
                pool_id=other_pool.id,
                stock_id=other_stock.id,
                inclusion_type="manual",
                rule_id=None,
            ),
        ]
    )
    db_session.commit()

    resp = client.get("/api/v1/stock_pools/overview/members", headers=headers)
    assert resp.status_code == 200

    rows = resp.json()
    assert {row["ticker"] for row in rows} == {"AAPL", "MSFT", "FICO"}
    assert [row["ticker"] for row in rows].count("MSFT") == 1
    assert all(row["membership_id"] is not None for row in rows)
    assert all(row["ticker"] != "NVDA" for row in rows)


def test_watchlist_rows_batch_101_members_with_fixed_query_count(
    db_session, monkeypatch
):
    from app.api.v1.endpoints.stock_pools import _watchlist_rows_for_memberships
    from app.services import market_data_service
    from app.services.market_data_service import (
        ET,
        compute_target_date,
        expected_session_on_or_before,
    )

    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "yfinance")
    monkeypatch.setattr(
        market_data_service.settings,
        "MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER",
        True,
    )
    user = _make_user(db_session, "watchlist-batch-101@example.com")
    pool = StockPool(user_id=user.id, name="Batch 101")
    db_session.add(pool)
    db_session.flush()
    stocks = [
        Stock(ticker=f"W{i:03d}", exchange="NYSE", company_name=f"Watch {i}")
        for i in range(101)
    ]
    db_session.add_all(stocks)
    db_session.flush()
    members = [
        PoolMembership(
            user_id=user.id,
            pool_id=pool.id,
            stock_id=stock.id,
            inclusion_type="manual",
        )
        for stock in stocks
    ]
    db_session.add_all(members)
    now = datetime.now(timezone.utc)
    target = compute_target_date(now.astimezone(ET))
    previous = expected_session_on_or_before(
        "NYSE", target - timedelta(days=1)
    ).session_date
    assert previous is not None
    db_session.add_all(
        [
            StockPrice(
                stock_id=stock.id,
                price_date=price_date,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1,
                source="yfinance",
                currency="USD",
                created_at=(
                    now - timedelta(minutes=1)
                    if price_date == target
                    else datetime.combine(target, datetime.min.time(), timezone.utc)
                    - timedelta(hours=1)
                ),
            )
            for stock in stocks
            for price_date, close in ((previous, 99), (target, 100))
        ]
    )
    db_session.flush()

    statements: list[str] = []
    connection = db_session.connection()

    def capture(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        rows = _watchlist_rows_for_memberships(db_session, user.id, members)
    finally:
        event.remove(connection, "before_cursor_execute", capture)

    assert len(rows) == 101
    assert len(statements) == 5
    assert {row["delta_today"] for row in rows} == {1}
    assert len({row["current_price"]["as_of_date"] for row in rows}) == 1
    assert len(
        {row["current_price"]["expected_session_date"] for row in rows}
    ) == 1


def test_watchlist_previous_price_uses_same_live_knowledge_cutoff(
    db_session, monkeypatch
):
    from app.api.v1.endpoints import stock_pools as stock_pools_endpoint
    from app.services import market_data_service

    evaluated_at = datetime(2026, 2, 4, 17, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return evaluated_at if tz is not None else evaluated_at.replace(tzinfo=None)

    monkeypatch.setattr(stock_pools_endpoint, "datetime", FixedDateTime)
    monkeypatch.setattr(market_data_service.settings, "MARKET_DATA_PRIMARY", "yfinance")
    monkeypatch.setattr(
        market_data_service.settings,
        "MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER",
        True,
    )
    user = _make_user(db_session, "watchlist-previous-pit@example.com")
    pool = StockPool(user_id=user.id, name="PIT")
    known_stock = _make_stock(db_session, "KNOWN")
    future_stock = _make_stock(db_session, "FUTURE")
    db_session.add(pool)
    db_session.flush()
    members = [
        PoolMembership(
            user_id=user.id,
            pool_id=pool.id,
            stock_id=stock.id,
            inclusion_type="manual",
        )
        for stock in (known_stock, future_stock)
    ]
    db_session.add_all(members)
    db_session.add_all(
        [
            StockPrice(
                stock_id=stock.id,
                price_date=date(2026, 2, 3),
                open=100,
                high=100,
                low=100,
                close=100,
                volume=1,
                source="yfinance",
                currency="USD",
                created_at=datetime(2026, 2, 3, 22, tzinfo=timezone.utc),
            )
            for stock in (known_stock, future_stock)
        ]
    )
    db_session.add_all(
        [
            StockPrice(
                stock_id=known_stock.id,
                price_date=date(2026, 2, 2),
                open=98,
                high=98,
                low=98,
                close=98,
                volume=1,
                source="yfinance",
                currency="USD",
                # After target-date NY midnight (05:00 UTC), but known now.
                created_at=datetime(2026, 2, 3, 6, tzinfo=timezone.utc),
            ),
            StockPrice(
                stock_id=future_stock.id,
                price_date=date(2026, 2, 2),
                open=97,
                high=97,
                low=97,
                close=97,
                volume=1,
                source="yfinance",
                currency="USD",
                created_at=datetime(2026, 2, 4, 18, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.flush()

    rows = stock_pools_endpoint._watchlist_rows_for_memberships(
        db_session, user.id, members
    )
    by_ticker = {row["ticker"]: row for row in rows}

    assert by_ticker["KNOWN"]["delta_today"] == 2
    assert by_ticker["KNOWN"]["delta_today_state"] == {
        "status": "available",
        "reason_code": None,
        "currency": "USD",
    }
    assert by_ticker["FUTURE"]["delta_today"] is None
    assert by_ticker["FUTURE"]["delta_today_state"] == {
        "status": "unavailable",
        "reason_code": "price_missing",
        "currency": None,
    }


def test_pool_f_score_compare_returns_five_actual_and_two_estimate_years(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "fscore-compare@example.com")
    headers = auth_headers(user)
    pool = StockPool(user_id=user.id, name="Quality", description=None)
    db_session.add(pool)
    db_session.commit()

    stock_a = _make_stock(db_session, "ASML")
    stock_b = _make_stock(db_session, "FICO")
    db_session.add_all(
        [
            PoolMembership(
                user_id=user.id,
                pool_id=pool.id,
                stock_id=stock_a.id,
                inclusion_type="manual",
                rule_id=None,
            ),
            PoolMembership(
                user_id=user.id,
                pool_id=pool.id,
                stock_id=stock_b.id,
                inclusion_type="manual",
                rule_id=None,
            ),
        ]
    )
    db_session.add_all(
        [
            *[
                _piotroski_total_fact(user.id, stock_a.id, year, float(score))
                for year, score in [
                    (2019, 4),
                    (2020, 5),
                    (2021, 6),
                    (2022, 7),
                    (2023, 8),
                    (2024, 9),
                ]
            ],
            _piotroski_total_fact(user.id, stock_a.id, 2025, 7.0, fact_nature="estimate"),
            _piotroski_total_fact(user.id, stock_a.id, 2026, 6.0, fact_nature="estimate"),
            _piotroski_total_fact(user.id, stock_a.id, 2027, 5.0, fact_nature="estimate"),
            _piotroski_total_fact(
                user.id,
                stock_b.id,
                2024,
                None,
                partial_score=6,
                max_available_score=8,
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/api/v1/stock_pools/{pool.id}/f-score-compare", headers=headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["watchlist"] == {"id": pool.id, "name": "Quality"}
    assert payload["years"] == [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    row_a = next(row for row in payload["rows"] if row["ticker"] == "ASML")
    assert row_a["scores"] == [
        {"fiscal_year": 2020, "score": 5.0, "display_score": "5", "fact_nature": "actual", "status": "calculated"},
        {"fiscal_year": 2021, "score": 6.0, "display_score": "6", "fact_nature": "actual", "status": "calculated"},
        {"fiscal_year": 2022, "score": 7.0, "display_score": "7", "fact_nature": "actual", "status": "calculated"},
        {"fiscal_year": 2023, "score": 8.0, "display_score": "8", "fact_nature": "actual", "status": "calculated"},
        {"fiscal_year": 2024, "score": 9.0, "display_score": "9", "fact_nature": "actual", "status": "calculated"},
        {"fiscal_year": 2025, "score": 7.0, "display_score": "7", "fact_nature": "estimate", "status": "calculated"},
        {"fiscal_year": 2026, "score": 6.0, "display_score": "6", "fact_nature": "estimate", "status": "calculated"},
    ]
    row_b = next(row for row in payload["rows"] if row["ticker"] == "FICO")
    assert row_b["scores"][-3] == {
        "fiscal_year": 2024,
        "score": None,
        "display_score": "6/8",
        "fact_nature": "actual",
        "status": "partial",
    }


def test_overview_f_score_compare_deduplicates_members(client, db_session, auth_headers):
    user = _make_user(db_session, "overview-fscore-compare@example.com")
    headers = auth_headers(user)
    pool_a = StockPool(user_id=user.id, name="Core", description=None)
    pool_b = StockPool(user_id=user.id, name="Ideas", description=None)
    db_session.add_all([pool_a, pool_b])
    db_session.commit()

    stock = _make_stock(db_session, "MSFT")
    db_session.add_all(
        [
            PoolMembership(user_id=user.id, pool_id=pool_a.id, stock_id=stock.id, inclusion_type="manual"),
            PoolMembership(user_id=user.id, pool_id=pool_b.id, stock_id=stock.id, inclusion_type="manual"),
            _piotroski_total_fact(user.id, stock.id, 2024, 8.0),
        ]
    )
    db_session.commit()

    resp = client.get("/api/v1/stock_pools/overview/f-score-compare", headers=headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["watchlist"] == {"id": "overview", "name": "Overview"}
    assert [row["ticker"] for row in payload["rows"]] == ["MSFT"]


def test_pool_members_include_price_and_fair_value(client, db_session, monkeypatch, auth_headers):
    from app.api.v1.endpoints import stock_pools as stock_pools_endpoint

    user = _make_user(db_session, "watchlist2@example.com")
    headers = auth_headers(user)
    pool = StockPool(user_id=user.id, name="Value", description=None)
    db_session.add(pool)
    db_session.commit()

    stock_a = _make_stock(db_session, "AOS")
    stock_b = _make_stock(db_session, "MSFT")
    stock_c = _make_stock(db_session, "SHOP")

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
            stock_id=stock_c.id,
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
    from app.services.market_data_service import (
        read_canonical_eod_prices,
        read_current_eod_prices,
    )

    monkeypatch.setattr(
        stock_pools_endpoint,
        "read_current_eod_prices",
        lambda session, *, stocks, evaluated_at=None: read_current_eod_prices(
            session,
            stocks=stocks,
            evaluated_at=datetime(2026, 2, 4, 17, tzinfo=timezone.utc),
            source_priority=("seed",),
        ),
    )
    monkeypatch.setattr(
        stock_pools_endpoint,
        "read_canonical_eod_prices",
        lambda session, *, stocks, as_of_by_stock_id, knowledge_cutoff: read_canonical_eod_prices(
            session,
            stocks=stocks,
            as_of_by_stock_id=as_of_by_stock_id,
            knowledge_cutoff=knowledge_cutoff,
            source_priority=("seed",),
        ),
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
                currency="USD",
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
                currency="USD",
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
                currency="USD",
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
                currency="CAD",
                created_at=datetime(2026, 2, 2, 21, 0, tzinfo=timezone.utc),
            ),
            StockPrice(
                stock_id=stock_c.id,
                price_date=target_date,
                open=69.0,
                high=71.0,
                low=68.0,
                close=70.0,
                volume=1_000,
                source="seed",
                currency="CAD",
                created_at=datetime(2026, 2, 3, 21, 0, tzinfo=timezone.utc),
            ),
            StockPrice(
                stock_id=stock_c.id,
                price_date=prev_date,
                open=64.0,
                high=66.0,
                low=63.0,
                close=65.0,
                volume=1_000,
                source="seed",
                currency=None,
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
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key=PIOTROSKI_TOTAL_KEY,
                value_numeric=9.0,
                value_json={
                    "status": "calculated",
                    "variant": "valueline_proxy",
                    "fiscal_year": 2999,
                    "fact_nature": "estimate",
                },
                unit="score_total",
                period_type="FY",
                period_end_date=date(2999, 12, 31),
                source_type="calculated",
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key=PIOTROSKI_TOTAL_KEY,
                value_numeric=8.0,
                value_json={
                    "status": "calculated",
                    "variant": "valueline_proxy",
                    "fiscal_year": 2024,
                },
                unit="score_total",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="calculated",
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key=PIOTROSKI_TOTAL_KEY,
                value_numeric=None,
                value_json={
                    "status": "partial",
                    "variant": "insurance_adjusted",
                    "fiscal_year": 2023,
                    "partial_score": 6,
                    "available_indicators": 8,
                    "max_available_score": 8,
                    "missing_indicators": ["score.piotroski.current_ratio_improving"],
                },
                unit="score_total",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="calculated",
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key=PIOTROSKI_TOTAL_KEY,
                value_numeric=4.0,
                value_json={"status": "calculated", "variant": "standard", "fiscal_year": 2022},
                unit="score_total",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="calculated",
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key=PIOTROSKI_TOTAL_KEY,
                value_numeric=3.0,
                value_json={"status": "calculated", "variant": "standard", "fiscal_year": 2021},
                unit="score_total",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="calculated",
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/api/v1/stock_pools/{pool.id}/members", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3

    row_a = next(row for row in rows if row["ticker"] == "AOS")
    assert row_a["current_price"]["value"] == pytest.approx(100.0)
    assert row_a["current_price"]["price_date"] == target_date.isoformat()
    assert row_a["delta_today"] == pytest.approx(2.0)
    assert row_a["delta_today_state"] == {
        "status": "available",
        "reason_code": None,
        "currency": "USD",
    }
    assert row_a["fair_value"] == pytest.approx(200.0)
    assert row_a["fair_value_source"] == "manual"
    assert row_a["mos"] == pytest.approx(0.5)
    assert row_a["valuation_reference"] == pytest.approx(180.0)
    assert row_a["valuation_reference_source"] == TARGET_KEY
    assert row_a["discount_to_reference"] == pytest.approx((180.0 - 100.0) / 180.0)
    assert row_a["piotroski_f_scores"] == [
        {
            "period_end_date": "2024-12-31",
            "fiscal_year": 2024,
            "score": 8.0,
            "status": "calculated",
            "variant": "valueline_proxy",
            "partial_score": None,
            "available_indicators": None,
            "max_available_score": None,
            "missing_indicators": [],
        },
        {
            "period_end_date": "2023-12-31",
            "fiscal_year": 2023,
            "score": None,
            "status": "partial",
            "variant": "insurance_adjusted",
            "partial_score": 6,
            "available_indicators": 8,
            "max_available_score": 8,
            "missing_indicators": ["score.piotroski.current_ratio_improving"],
        },
        {
            "period_end_date": "2022-12-31",
            "fiscal_year": 2022,
            "score": 4.0,
            "status": "calculated",
            "variant": "standard",
            "partial_score": None,
            "available_indicators": None,
            "max_available_score": None,
            "missing_indicators": [],
        },
    ]

    row_b = next(row for row in rows if row["ticker"] == "MSFT")
    assert row_b["current_price"]["value"] == pytest.approx(50.0)
    assert row_b["delta_today"] is None
    assert row_b["delta_today_state"] == {
        "status": "unavailable",
        "reason_code": "currency_mismatch",
        "currency": None,
    }
    assert row_b["fair_value"] is None
    assert row_b["fair_value_source"] is None
    assert row_b["mos"] is None
    assert row_b["valuation_reference"] == pytest.approx(80.0)
    assert row_b["valuation_reference_source"] == TARGET_KEY
    assert row_b["discount_to_reference"] == pytest.approx(0.375)
    assert row_b["piotroski_f_scores"] == []

    row_c = next(row for row in rows if row["ticker"] == "SHOP")
    assert row_c["current_price"]["value"] == pytest.approx(70.0)
    assert row_c["delta_today"] is None
    assert row_c["delta_today_state"] == {
        "status": "unavailable",
        "reason_code": "price_currency_unavailable",
        "currency": None,
    }
