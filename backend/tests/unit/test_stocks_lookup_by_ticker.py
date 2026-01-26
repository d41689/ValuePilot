from datetime import date

from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User


def test_lookup_stock_by_ticker_returns_summary(client, db_session):
    user = User(email="ticker_lookup@example.com")
    stock = Stock(ticker="COCO_TEST", exchange="NDQ", company_name="VITA COCO", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "54.52", "normalized": 54.52, "unit": "USD"},
                value_numeric=54.52,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.pe",
                value_json={"raw": "43.3", "normalized": 43.3, "unit": "ratio"},
                value_numeric=43.3,
                unit="ratio",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share_normalized",
                value_json={"raw": "5.55", "normalized": 5.55, "unit": "USD"},
                value_numeric=5.55,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "5.2", "normalized": 5.2, "unit": "USD"},
                value_numeric=5.2,
                unit="USD",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "5.1", "normalized": 5.1, "unit": "USD"},
                value_numeric=5.1,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "5.0", "normalized": 5.0, "unit": "USD"},
                value_numeric=5.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "4.9", "normalized": 4.9, "unit": "USD"},
                value_numeric=4.9,
                unit="USD",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "4.8", "normalized": 4.8, "unit": "USD"},
                value_numeric=4.8,
                unit="USD",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "4.7", "normalized": 4.7, "unit": "USD"},
                value_numeric=4.7,
                unit="USD",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.sales.cagr_est",
                value_json={"value": 6.5},
                value_numeric=0.065,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.cash_flow.cagr_est",
                value_json={"value": 7.5},
                value_numeric=0.075,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"value": 7.5},
                value_numeric=0.075,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/coco_test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "COCO_TEST"
    assert payload["exchange"] == "NDQ"
    assert payload["company_name"] == "VITA COCO"
    assert payload["price"] == 54.52
    assert payload["pe"] == 43.3
    assert payload["oeps_normalized"] == 5.55
    assert payload["oeps_series"] == [
        {"year": 2026, "value": 5.2},
        {"year": 2025, "value": 5.1},
        {"year": 2024, "value": 5.0},
        {"year": 2023, "value": 4.9},
        {"year": 2022, "value": 4.8},
        {"year": 2021, "value": 4.7},
    ]
    assert payload["growth_rate_options"] == [
        {"key": "sales", "label": "Sales", "value": 6.5},
        {"key": "cash_flow", "label": "Cash Flow", "value": 7.5},
        {"key": "earnings", "label": "Earnings", "value": 7.5},
    ]


def test_lookup_stock_by_ticker_uses_revenues_growth_when_sales_missing(client, db_session):
    user = User(email="ticker_lookup_revenues@example.com")
    stock = Stock(ticker="REV_TEST", exchange="NDQ", company_name="REVENUES INC", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.revenues.cagr_est",
                value_json={"value": 11.0},
                value_numeric=0.11,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.cash_flow.cagr_est",
                value_json={"value": 7.5},
                value_numeric=0.075,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"value": 5.0},
                value_numeric=0.05,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/rev_test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "REV_TEST"
    assert payload["growth_rate_options"] == [
        {"key": "revenues", "label": "Revenues", "value": 11.0},
        {"key": "cash_flow", "label": "Cash Flow", "value": 7.5},
        {"key": "earnings", "label": "Earnings", "value": 5.0},
    ]


def test_lookup_stock_by_ticker_not_found(client):
    response = client.get("/api/v1/stocks/by_ticker/UNKNOWN")

    assert response.status_code == 404
