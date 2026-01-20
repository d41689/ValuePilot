from app.main import app
from app.models.users import User
from app.models.stocks import Stock
from app.models.facts import MetricFact


def test_screener_api_returns_metrics_payload(client, db_session):
    user = User(email="screener_metrics@example.com")
    db_session.add(user)
    db_session.commit()

    stock_ok = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)", is_active=True)
    stock_fail = Stock(ticker="FAIL", exchange="NYSE", company_name="Fail Co", is_active=True)
    db_session.add_all([stock_ok, stock_fail])
    db_session.commit()

    # Passing stock metrics for screen conditions
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="val.pe",
                value_json={"raw": "10", "normalized": 10, "unit": "ratio"},
                value_numeric=10,
                unit="ratio",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="val.dividend_yield",
                value_json={"raw": "2.0%", "normalized": 0.02, "unit": "ratio"},
                value_numeric=0.02,
                unit="ratio",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )

    # Failing stock metrics (pe_ratio too high)
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock_fail.id,
                metric_key="val.pe",
                value_json={"raw": "30", "normalized": 30, "unit": "ratio"},
                value_numeric=30,
                unit="ratio",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_fail.id,
                metric_key="val.dividend_yield",
                value_json={"raw": "2.0%", "normalized": 0.02, "unit": "ratio"},
                value_numeric=0.02,
                unit="ratio",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )

    # Metrics expected by the UI columns
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="is.net_income",
                value_json={"raw": "500", "normalized": 500, "unit": "USD"},
                value_numeric=500,
                unit="USD",
                period_type="FY",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="is.depreciation",
                value_json={"raw": "80", "normalized": 80, "unit": "USD"},
                value_numeric=80,
                unit="USD",
                period_type="FY",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.7", "normalized": 0.7, "unit": "USD"},
                value_numeric=0.7,
                unit="USD",
                period_type="FY",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100000000", "normalized": 100000000, "unit": "shares"},
                value_numeric=100000000,
                unit="shares",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="rating.timeliness",
                value_json={"value": 3},
                value_numeric=3,
                unit="number",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="rating.safety",
                value_json={"value": 3},
                value_numeric=3,
                unit="number",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="val.avg_dividend_yield",
                value_json={"raw": "1.6%", "normalized": 1.6, "unit": "percent"},
                value_numeric=0.016,
                unit="percent",
                period_type="FY",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="quality.financial_strength",
                value_text="B++",
                value_numeric=None,
                unit=None,
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="quality.stock_price_stability",
                value_json={"value": 80},
                value_numeric=80,
                unit="number",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="quality.price_growth_persistence",
                value_json={"value": 70},
                value_numeric=70,
                unit="number",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="quality.earnings_predictability",
                value_json={"value": 80},
                value_numeric=80,
                unit="number",
                period_type="AS_OF",
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    resp = client.post(
        "/api/v1/screener/run",
        json={
            "type": "AND",
            "conditions": [
                {"metric": "pe_ratio", "operator": "<", "value": 25},
                {"metric": "dividend_yield", "operator": ">", "value": 0.01},
            ],
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    result = next((row for row in data if row.get("id") == stock_ok.id), None)
    assert result is not None
    assert all(row.get("ticker") != "FAIL" for row in data)

    metrics = result["metrics"]
    assert metrics["net_profit_usd_millions"] == 500
    assert metrics["depreciation_usd_millions"] == 80
    assert metrics["capital_spending_per_share_usd"] == 0.7
    assert metrics["common_shares_outstanding_millions"] == 100
    assert metrics["timeliness"] == 3
    assert metrics["safety"] == 3
    assert metrics["avg_annual_dividend_yield_pct"] == 0.016
    assert metrics["company_financial_strength"] == "B++"
    assert metrics["stock_price_stability"] == 80
    assert metrics["price_growth_persistence"] == 70
    assert metrics["earnings_predictability"] == 80
