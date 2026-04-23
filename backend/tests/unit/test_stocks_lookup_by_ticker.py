from datetime import date, datetime, timezone

from sqlalchemy import update

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.stocks import Stock, StockPrice
from app.models.users import User


def test_lookup_stock_by_ticker_returns_summary(client, db_session):
    user = User(email="ticker_lookup@example.com")
    stock = Stock(ticker="COCO_TEST", exchange="NDQ", company_name="VITA COCO", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="coco.pdf",
        source="upload",
        file_storage_key="/tmp/coco.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    db_session.add(doc)
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
                value_json={"raw": "5.1", "normalized": 5.1, "unit": "USD"},
                value_numeric=5.1,
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
                value_json={"raw": "5.5", "normalized": 5.5, "unit": "USD"},
                value_numeric=5.5,
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
                value_json={"raw": "5.3", "normalized": 5.3, "unit": "USD"},
                value_numeric=5.3,
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
                value_json={"raw": "5.1", "normalized": 5.1, "unit": "USD"},
                value_numeric=5.1,
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
                value_json={"raw": "4.7", "normalized": 4.7, "unit": "USD"},
                value_numeric=4.7,
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
                value_json={"raw": "4.5", "normalized": 4.5, "unit": "USD"},
                value_numeric=4.5,
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
                metric_key="per_share.eps",
                value_json={"raw": "5.0", "normalized": 5.0, "unit": "USD"},
                value_numeric=5.0,
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
                metric_key="per_share.eps",
                value_json={"raw": "4.9", "normalized": 4.9, "unit": "USD"},
                value_numeric=4.9,
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
                metric_key="per_share.eps",
                value_json={"raw": "4.8", "normalized": 4.8, "unit": "USD"},
                value_numeric=4.8,
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
                metric_key="per_share.eps",
                value_json={"raw": "4.7", "normalized": 4.7, "unit": "USD"},
                value_numeric=4.7,
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
                metric_key="per_share.eps",
                value_json={"raw": "4.6", "normalized": 4.6, "unit": "USD"},
                value_numeric=4.6,
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
                metric_key="per_share.eps",
                value_json={"raw": "4.5", "normalized": 4.5, "unit": "USD"},
                value_numeric=4.5,
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
                metric_key="is.depreciation",
                value_json={"raw": "100", "normalized": 100.0, "unit": "USD"},
                value_numeric=100.0,
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
                metric_key="is.depreciation",
                value_json={"raw": "100", "normalized": 100.0, "unit": "USD"},
                value_numeric=100.0,
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
                metric_key="is.depreciation",
                value_json={"raw": "90", "normalized": 90.0, "unit": "USD"},
                value_numeric=90.0,
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
                metric_key="is.depreciation",
                value_json={"raw": "80", "normalized": 80.0, "unit": "USD"},
                value_numeric=80.0,
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
                metric_key="is.depreciation",
                value_json={"raw": "70", "normalized": 70.0, "unit": "USD"},
                value_numeric=70.0,
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
                metric_key="is.depreciation",
                value_json={"raw": "70", "normalized": 70.0, "unit": "USD"},
                value_numeric=70.0,
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
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.5", "normalized": 0.5, "unit": "USD"},
                value_numeric=0.5,
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
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
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
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
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
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
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
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
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
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.7", "normalized": 0.7, "unit": "USD"},
                value_numeric=0.7,
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
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=date(2026, 1, 10),
            open=54.0,
            high=56.5,
            low=53.5,
            close=55.25,
            adj_close=None,
            volume=123456,
            source="yfinance",
            created_at=datetime(2026, 1, 10, 21, 0, tzinfo=timezone.utc),
        )
    )
    db_session.flush()
    db_session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == user.id,
            MetricFact.stock_id == stock.id,
            MetricFact.source_type == "parsed",
        )
        .values(source_document_id=doc.id)
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/coco_test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "COCO_TEST"
    assert payload["exchange"] == "NDQ"
    assert payload["company_name"] == "VITA COCO"
    assert payload["price"] == 54.52
    assert payload["latest_price"] == 55.25
    assert payload["latest_price_date"] == "2026-01-10"
    assert payload["active_report_document_id"] == doc.id
    assert payload["active_report_date"] == "2026-01-09"
    assert payload["pe"] == 43.3
    assert payload["price_provenance"] == {
        "source_type": "parsed",
        "source_document_id": doc.id,
        "source_report_date": "2026-01-09",
        "period_end_date": "2026-01-09",
        "is_active_report": True,
    }
    assert payload["pe_provenance"] == {
        "source_type": "parsed",
        "source_document_id": doc.id,
        "source_report_date": "2026-01-09",
        "period_end_date": "2026-01-09",
        "is_active_report": True,
    }
    assert payload["oeps_normalized"] == 5.1
    assert payload["oeps_normalized_provenance"] == {
        "source_type": "parsed",
        "source_document_id": doc.id,
        "source_report_date": "2026-01-09",
        "period_end_date": "2026-01-09",
        "is_active_report": True,
    }
    assert payload["oeps_series"] == [
        {
            "year": 2026,
            "value": 5.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2025,
            "value": 5.3,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2025-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2024,
            "value": 5.1,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2024-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2023,
            "value": 4.9,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2023-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2022,
            "value": 4.7,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2022-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2021,
            "value": 4.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2021-12-31",
                "is_active_report": True,
            },
        },
    ]
    assert payload["dcf_inputs"] == {
        "net_profit_per_share": {
            "value": 4.8,
            "source": "fact",
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2024-12-31",
                "is_active_report": True,
            },
        },
        "depreciation_per_share": {
            "value": 0.9,
            "source": "computed",
            "provenance": {
                "inputs": [
                    {
                        "metric_key": "is.depreciation",
                        "source_type": "parsed",
                        "source_document_id": doc.id,
                        "source_report_date": "2026-01-09",
                        "period_end_date": "2024-12-31",
                        "is_active_report": True,
                    },
                    {
                        "metric_key": "equity.shares_outstanding",
                        "source_type": "parsed",
                        "source_document_id": doc.id,
                        "source_report_date": "2026-01-09",
                        "period_end_date": "2024-12-31",
                        "is_active_report": True,
                    },
                ],
            },
        },
        "capital_spending_per_share": {
            "value": 0.6,
            "source": "fact",
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2024-12-31",
                "is_active_report": True,
            },
        },
    }
    assert payload["dcf_inputs_series"][0]["net_profit_per_share"]["provenance"]["period_end_date"] == "2026-12-31"
    assert payload["dcf_inputs_series"][0]["depreciation_per_share"]["provenance"]["inputs"][0]["metric_key"] == "is.depreciation"
    assert payload["dcf_inputs_series"] == [
        {
            "year": 2026,
            "net_profit_per_share": {
                "value": 5.0,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2026-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 1.0,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2026-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2026-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.5,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2026-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2025,
            "net_profit_per_share": {
                "value": 4.9,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2025-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 1.0,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2025-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2025-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2025-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2024,
            "net_profit_per_share": {
                "value": 4.8,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2024-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.9,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2024-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2024-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2024-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2023,
            "net_profit_per_share": {
                "value": 4.7,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2023-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.8,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2023-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2023-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2023-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2022,
            "net_profit_per_share": {
                "value": 4.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2022-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.7,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2022-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2022-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2022-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2021,
            "net_profit_per_share": {
                "value": 4.5,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2021-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.7,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2021-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2021-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.7,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2021-12-31",
                    "is_active_report": True,
                },
            },
        },
    ]
    assert payload["growth_rate_options"] == [
        {
            "key": "sales",
            "label": "Sales",
            "value": 6.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-01-09",
                "is_active_report": True,
            },
        },
        {
            "key": "cash_flow",
            "label": "Cash Flow",
            "value": 7.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-01-09",
                "is_active_report": True,
            },
        },
        {
            "key": "earnings",
            "label": "Earnings",
            "value": 7.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-01-09",
                "is_active_report": True,
            },
        },
    ]


def test_lookup_stock_by_ticker_returns_active_report_metadata(client, db_session):
    user = User(email="ticker_active_report@example.com")
    stock = Stock(ticker="FICO_TEST", exchange="NYSE", company_name="Fair Isaac", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q1.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q1.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    new_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q2.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q2.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 4, 9),
    )
    db_session.add_all([old_doc, new_doc])
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "110", "fact_nature": "snapshot"},
                value_numeric=110.0,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.pe",
                value_json={"raw": "35", "fact_nature": "snapshot"},
                value_numeric=35.0,
                unit="ratio",
                period_type="AS_OF",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/fico_test")
    assert response.status_code == 200

    payload = response.json()
    assert payload["active_report_document_id"] == new_doc.id
    assert payload["active_report_date"] == "2026-04-09"


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
        {
            "key": "revenues",
            "label": "Revenues",
            "value": 11.0,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": None,
                "source_report_date": None,
                "period_end_date": "2026-01-09",
                "is_active_report": False,
            },
        },
        {
            "key": "cash_flow",
            "label": "Cash Flow",
            "value": 7.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": None,
                "source_report_date": None,
                "period_end_date": "2026-01-09",
                "is_active_report": False,
            },
        },
        {
            "key": "earnings",
            "label": "Earnings",
            "value": 5.0,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": None,
                "source_report_date": None,
                "period_end_date": "2026-01-09",
                "is_active_report": False,
            },
        },
    ]


def test_lookup_stock_by_ticker_not_found(client):
    response = client.get("/api/v1/stocks/by_ticker/UNKNOWN")

    assert response.status_code == 404
