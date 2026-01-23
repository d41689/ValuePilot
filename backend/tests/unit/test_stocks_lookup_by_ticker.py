from datetime import date

from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User


def test_lookup_stock_by_ticker_returns_summary(client, db_session):
    user = User(email="ticker_lookup@example.com")
    stock = Stock(ticker="COCO", exchange="NDQ", company_name="VITA COCO", is_active=True)
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
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/coco")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "COCO"
    assert payload["exchange"] == "NDQ"
    assert payload["company_name"] == "VITA COCO"
    assert payload["price"] == 54.52
    assert payload["pe"] == 43.3


def test_lookup_stock_by_ticker_not_found(client):
    response = client.get("/api/v1/stocks/by_ticker/UNKNOWN")

    assert response.status_code == 404
