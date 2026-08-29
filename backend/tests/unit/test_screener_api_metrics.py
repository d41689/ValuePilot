from app.models.stocks import Stock
from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from datetime import date, datetime, timezone
import sqlalchemy as sa

from app.services.analysis_method_gate import register_reviewed_company_classification
from app.services.screener_service import ScreenerService
from financial_truth_fixtures import authorize_parsed_facts


def test_screener_api_returns_metrics_payload(
    client, db_session, user_factory, auth_headers, monkeypatch
):
    user = user_factory("screener_metrics@example.com")

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
            # A canonical SEC actual is base USD, not Value Line's display
            # scale. Even if it is otherwise visible, the legacy screener
            # result contract must not select or relabel it before FT-05/06.
            MetricFact(
                user_id=None,
                stock_id=stock_ok.id,
                metric_key="is.net_income",
                value_json={"fact_nature": "actual"},
                value_numeric=500_000_000,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="sec",
                source_ref_id=999_999,
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
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_ok.id,
                metric_key="val.avg_dividend_yield",
                value_json={"raw": "3.0%", "normalized": 3.0, "unit": "percent", "fact_nature": "estimate"},
                value_numeric=0.03,
                unit="percent",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
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
    monkeypatch.setattr(
        ScreenerService,
        "_visibility_predicate",
        lambda *_args, **_kwargs: sa.true(),
    )

    resp = client.post(
        "/api/v1/screener/run",
        headers=auth_headers(user),
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


def test_screener_cannot_use_owner_earnings_before_output_authorization(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("screener_owner_gate@example.com")
    stock = Stock(
        ticker="OEGATE",
        exchange="NYSE",
        company_name="Owner Earnings Gate",
        is_active=True,
    )
    db_session.add(stock)
    db_session.flush()
    classification = register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="ordinary_operating",
        effective_from=date(2020, 1, 1),
        known_at=datetime.now(timezone.utc),
        review_reason="Reviewed ordinary operating company.",
    )
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="owners_earnings_per_share_normalized",
            value_numeric=10.0,
            value_json={
                "analysis_method": {
                    "policy_version": "analysis-method-gate-v1",
                    "classification_id": classification.id,
                    "method_id": "ordinary-owner-economics-v1",
                    "evidence_complete": True,
                }
            },
            unit="USD",
            period_type="AS_OF",
            period_end_date=date(2025, 12, 31),
            source_type="calculated",
            is_current=True,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/screener/run",
        headers=auth_headers(user),
        json={
            "type": "AND",
            "conditions": [
                {
                    "metric": "owners_earnings_per_share_normalized",
                    "operator": ">",
                    "value": 1,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert all(row["id"] != stock.id for row in response.json())


def test_screener_never_treats_admin_upload_as_shared(
    client, db_session, user_factory, auth_headers
):
    admin_owner = user_factory(
        "screener-admin-private-owner@example.com",
        role="admin",
    )
    viewer = user_factory("screener-admin-private-viewer@example.com")
    stock = Stock(
        ticker="SCRADMINPRIVATE",
        exchange="NYSE",
        company_name="Screener Admin Private",
        is_active=True,
    )
    db_session.add(stock)
    db_session.flush()
    document = PdfDocument(
        user_id=admin_owner.id,
        stock_id=stock.id,
        file_name="screener-admin-private.pdf",
        source="value_line",
        file_storage_key="tests/screener-admin-private.pdf",
        parse_status="parsed",
        report_date=date(2026, 8, 1),
    )
    db_session.add(document)
    db_session.flush()
    private_pe = MetricFact(
        user_id=admin_owner.id,
        stock_id=stock.id,
        metric_key="val.pe",
        value_numeric=5.0,
        unit="ratio",
        period_type="AS_OF",
        period_end_date=date(2026, 8, 1),
        source_type="parsed",
        is_current=True,
    )
    authorize_parsed_facts(
        db_session,
        document=document,
        facts=[private_pe],
    )
    db_session.commit()

    response = client.post(
        "/api/v1/screener/run",
        headers=auth_headers(viewer),
        json={
            "type": "AND",
            "conditions": [
                {"metric": "pe_ratio", "operator": "<", "value": 10}
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert all(row["id"] != stock.id for row in response.json())
