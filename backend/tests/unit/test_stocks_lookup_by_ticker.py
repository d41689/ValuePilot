from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock, StockPrice
from app.models.users import User
from app.services.analysis_method_gate import register_reviewed_company_classification
from financial_truth_fixtures import authorize_parsed_facts


def _add_parsed_lineage(db_session, *, user_id: int, document_id: int) -> MetricExtraction:
    extraction = MetricExtraction(
        user_id=user_id,
        document_id=document_id,
        page_number=1,
        field_key="test_fixture",
        raw_value_text="fixture",
        original_text_snippet="fixture",
        parsed_value_json={"raw": "fixture"},
        confidence_score=1.0,
        parser_version="v1",
        parse_generation=1,
    )
    db_session.add(extraction)
    db_session.flush()
    return extraction


def _piotroski_fact(
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    year: int,
    value: float | None,
    value_json: dict | None = None,
) -> MetricFact:
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value,
        value_json=value_json or {
            "status": "calculated",
            "variant": "valueline_proxy",
                            "fact_nature": (
                                "estimate"
                                if metric_key == "score.piotroski.roa_positive" and year == 2026
                                else "actual"
                            ),
            "fiscal_year": year,
        },
        unit="score_component" if metric_key != "score.piotroski.total" else "score_total",
        period_type="FY",
        period_end_date=date(year, 12, 31),
        source_type="calculated",
        is_current=True,
    )


def test_lookup_stock_by_ticker_quarantines_unverifiable_legacy_piotroski_rows(
    client, db_session, auth_headers
):
    user = User(email="ticker_f_score@example.com")
    stock = Stock(ticker="FSC_TEST", exchange="NYSE", company_name="F SCORE INC", is_active=True)
    other_stock = Stock(ticker="OTHER_FS", exchange="NYSE", company_name="OTHER SCORE", is_active=True)
    db_session.add_all([user, stock, other_stock])
    db_session.commit()

    years = [2022, 2023, 2024, 2025, 2026]
    component_values = {
        "score.piotroski.roa_positive": [1, 1, 1, 1, 1],
        "score.piotroski.cfo_positive": [1, 1, 1, 1, 1],
        "score.piotroski.roa_improving": [1, 0, 1, 0, 1],
        "score.piotroski.accrual_quality": [1, 1, 0, 0, 0],
        "score.piotroski.leverage_declining": [0, 0, 1, 1, 1],
        "score.piotroski.current_ratio_improving": [0, 1, 1, 1, 0],
        "score.piotroski.no_dilution": [1, 1, 1, 1, 1],
        "score.piotroski.gross_margin_improving": [1, 1, 1, 0, 0],
        "score.piotroski.asset_turnover_improving": [0, 1, 1, 1, 0],
    }
    facts = []
    for metric_key, values in component_values.items():
        for year, value in zip(years, values):
            facts.append(
                _piotroski_fact(
                    user_id=user.id,
                    stock_id=stock.id,
                    metric_key=metric_key,
                    year=year,
                    value=float(value),
                    value_json={
                        "status": "calculated",
                        "variant": "valueline_proxy",
                        "fact_nature": (
                            "estimate"
                            if metric_key == "score.piotroski.roa_positive" and year == 2026
                            else "actual"
                        ),
                        "fiscal_year": year,
                        "formula": f"{metric_key}[Y] test formula",
                        "inputs": [
                            {
                                "metric_key": f"{metric_key}.input",
                                "value_numeric": float(value) * 10,
                                "period_end_date": f"{year}-12-31",
                                "fact_nature": (
                                    "estimate"
                                    if metric_key == "score.piotroski.roa_positive" and year == 2026
                                    else "actual"
                                ),
                            }
                        ],
                    },
                )
            )
    for year, value in zip(years, [7, 7, 8, 7, 7]):
        facts.append(
            _piotroski_fact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="score.piotroski.total",
                year=year,
                value=float(value),
            )
        )
    facts.append(
        _piotroski_fact(
            user_id=user.id,
            stock_id=other_stock.id,
            metric_key="score.piotroski.total",
            year=2026,
            value=2.0,
        )
    )
    db_session.add_all(facts)
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/fsc_test", headers=auth_headers(user)
    )

    assert response.status_code == 200
    card = response.json()["piotroski_f_score_card"]
    assert card["years"] == []
    assert card["rows"][-1]["metric_key"] == "score.piotroski.total"
    assert card["rows"][-1]["scores"] == []


def test_lookup_stock_by_ticker_returns_summary(client, db_session, auth_headers):
    user = User(email="ticker_lookup@example.com")
    stock = Stock(ticker="COCO_TEST", exchange="NDQ", company_name="VITA COCO", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()
    classification = register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="ordinary_operating",
        effective_from=date(2020, 1, 1),
        known_at=datetime.now(timezone.utc),
        review_reason="Test fixture reviewed as an ordinary operating company.",
    )
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

    summary_facts = [
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
    for fact in summary_facts:
        if fact.metric_key in {
            "owners_earnings_per_share",
            "owners_earnings_per_share_normalized",
        }:
            fact.value_json = {
                **(fact.value_json or {}),
                "analysis_method": {
                    "policy_version": "analysis-method-gate-v1",
                    "classification_id": classification.id,
                    "method_id": "ordinary-owner-economics-v1",
                    "evidence_complete": True,
                },
            }
    authorize_parsed_facts(db_session, document=doc, facts=summary_facts)
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
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/coco_test", headers=auth_headers(user)
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dcf_available"] is False
    assert payload["valuation_method"] == {
        "state": "unsupported",
        "reason": "valuation_method_pending_ft09",
        "policy_version": "analysis-method-gate-v1",
        "classification": "ordinary_operating",
        "classification_id": payload["valuation_method"]["classification_id"],
            "method_id": None,
            "required_evidence": [],
            "output_authorized": False,
            "conclusion_authorized": False,
    }
    assert payload["ticker"] == "COCO_TEST"
    assert payload["exchange"] == "NDQ"
    assert payload["company_name"] == "VITA COCO"
    assert payload["price"] is None
    assert payload["latest_price"] is None
    assert payload["latest_price_date"] == "2026-01-10"
    assert payload["latest_price_freshness"] == "unknown_freshness"
    assert payload["latest_price_reason"] == "price_currency_unavailable"
    assert payload["report_price_reference"] == 54.52
    assert payload["active_report_document_id"] == doc.id
    assert payload["active_report_date"] == "2026-01-09"
    assert payload["pe"] == 43.3
    assert payload["price_provenance"] is None
    assert payload["report_price_reference_provenance"] == {
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
    assert payload["oeps_normalized"] is None
    assert payload["oeps_normalized_provenance"] is None
    assert payload["oeps_series"] == []
    assert payload["dcf_inputs"] is None
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


def test_lookup_stock_by_ticker_returns_active_report_metadata(
    client, db_session, auth_headers
):
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

    report_facts = [
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
                is_current=True,
            ),
        ]
    authorize_parsed_facts(db_session, document=new_doc, facts=report_facts)
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/fico_test", headers=auth_headers(user)
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["active_report_document_id"] == new_doc.id
    assert payload["active_report_date"] == "2026-04-09"


def test_lookup_stock_by_ticker_prefers_duplicate_with_active_report(
    client, db_session, auth_headers
):
    user = User(email="ticker_duplicate_active@example.com")
    stale_stock = Stock(ticker="DUP_TEST", exchange="US", company_name="Duplicate Empty", is_active=True)
    active_stock = Stock(ticker="DUP_TEST", exchange="NDQ", company_name="Duplicate Active", is_active=True)
    db_session.add_all([user, stale_stock, active_stock])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="dup-active.pdf",
        source="upload",
        file_storage_key="/tmp/dup-active.pdf",
        parse_status="parsed",
        stock_id=active_stock.id,
        report_date=date(2026, 5, 1),
    )
    db_session.add(doc)
    db_session.commit()

    active_report_fact = MetricFact(
            user_id=user.id,
            stock_id=active_stock.id,
            metric_key="mkt.price",
            value_json={"raw": "429.99", "fact_nature": "snapshot"},
            value_numeric=429.99,
            unit="USD",
            period_type="AS_OF",
            period_end_date=date(2026, 5, 1),
            source_type="parsed",
            is_current=True,
        )
    authorize_parsed_facts(
        db_session, document=doc, facts=[active_report_fact]
    )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/dup_test", headers=auth_headers(user)
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["id"] == active_stock.id
    assert payload["exchange"] == "NDQ"
    assert payload["price"] is None
    assert payload["report_price_reference"] == 429.99
    assert payload["active_report_document_id"] == doc.id


def test_lookup_stock_by_ticker_chooses_latest_period_not_latest_inserted_fact(
    client, db_session, auth_headers
):
    user = User(email="ticker_latest_period@example.com")
    stock = Stock(
        ticker="LATEST_PERIOD",
        exchange="NYSE",
        company_name="Latest Period Co",
        is_active=True,
    )
    db_session.add_all([user, stock])
    db_session.flush()
    newer_document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="latest-period-2026.pdf",
        source="value_line",
        file_storage_key="tests/latest-period-2026.pdf",
        parse_status="parsed",
    )
    older_document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="latest-period-2025.pdf",
        source="value_line",
        file_storage_key="tests/latest-period-2025.pdf",
        parse_status="parsed",
    )
    db_session.add_all([newer_document, older_document])
    db_session.flush()
    newer_period = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="val.pe",
        value_json={"raw": "18"},
        value_numeric=18.0,
        unit="ratio",
        period_type="AS_OF",
        period_end_date=date(2026, 6, 30),
        source_type="parsed",
        is_current=True,
    )
    authorize_parsed_facts(
        db_session, document=newer_document, facts=[newer_period]
    )
    db_session.flush()
    older_but_later_inserted = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="val.pe",
        value_json={"raw": "99"},
        value_numeric=99.0,
        unit="ratio",
        period_type="AS_OF",
        period_end_date=date(2025, 6, 30),
        source_type="parsed",
        is_current=True,
    )
    authorize_parsed_facts(
        db_session, document=older_document, facts=[older_but_later_inserted]
    )
    db_session.commit()
    assert older_but_later_inserted.id > newer_period.id

    response = client.get(
        "/api/v1/stocks/by_ticker/LATEST_PERIOD",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    assert response.json()["pe"] == 18.0
    assert response.json()["pe_provenance"]["period_end_date"] == "2026-06-30"


def test_lookup_stock_by_ticker_returns_actual_conflicts(
    client, db_session, auth_headers
):
    user = User(email="ticker_conflicts@example.com")
    stock = Stock(ticker="CONF_TEST", exchange="NYSE", company_name="Conflict Co", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="conf-q1.pdf",
        source="upload",
        file_storage_key="/tmp/conf-q1.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    new_doc = PdfDocument(
        user_id=user.id,
        file_name="conf-q2.pdf",
        source="upload",
        file_storage_key="/tmp/conf-q2.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 4, 9),
    )
    db_session.add_all([old_doc, new_doc])
    db_session.commit()

    conflict_facts = [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_json={"fact_nature": "actual", "raw": "100"},
                value_numeric=100.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=old_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_json={"fact_nature": "actual", "raw": "120"},
                value_numeric=120.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"fact_nature": "actual", "raw": "5.0"},
                value_numeric=5.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=old_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"fact_nature": "actual", "raw": "5.0"},
                value_numeric=5.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"fact_nature": "estimate", "value": 10.0},
                value_numeric=0.10,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=old_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"fact_nature": "estimate", "value": 12.0},
                value_numeric=0.12,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
        ]
    authorize_parsed_facts(
        db_session,
        document=old_doc,
        facts=[fact for fact in conflict_facts if not fact.is_current],
    )
    authorize_parsed_facts(
        db_session,
        document=new_doc,
        facts=[fact for fact in conflict_facts if fact.is_current],
    )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/conf_test", headers=auth_headers(user)
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["actual_conflict_count"] == 1
    assert payload["actual_conflicts"] == [
        {
            "metric_key": "is.net_income",
            "period_type": "FY",
            "period_end_date": "2024-12-31",
            "selection_rule": "latest_report_wins_for_same_actual_period",
            "current_value_numeric": 120.0,
            "current_value_text": None,
            "current_source_document_id": new_doc.id,
            "current_report_date": "2026-04-09",
            "previous_value_numeric": 100.0,
            "previous_value_text": None,
            "previous_source_document_id": old_doc.id,
            "previous_report_date": "2026-01-09",
            "observations": [
                {
                    "source_document_id": new_doc.id,
                    "source_report_date": "2026-04-09",
                    "value_numeric": 120.0,
                    "value_text": None,
                    "is_active_report": True,
                },
                {
                    "source_document_id": old_doc.id,
                    "source_report_date": "2026-01-09",
                    "value_numeric": 100.0,
                    "value_text": None,
                    "is_active_report": False,
                },
            ],
        }
    ]

    archived = client.delete(
        f"/api/v1/documents/{new_doc.id}", headers=auth_headers(user)
    )
    assert archived.status_code == 200, archived.text
    refreshed = client.get(
        "/api/v1/stocks/by_ticker/conf_test", headers=auth_headers(user)
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["actual_conflict_count"] == 0
    assert refreshed.json()["actual_conflicts"] == []


def test_lookup_stock_by_ticker_uses_revenues_growth_when_sales_missing(
    client, db_session, auth_headers
):
    user = User(email="ticker_lookup_revenues@example.com")
    stock = Stock(ticker="REV_TEST", exchange="NDQ", company_name="REVENUES INC", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="revenues.pdf",
        source="upload",
        file_storage_key="/tmp/revenues.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    db_session.add(doc)
    db_session.flush()
    growth_facts = [
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
                    is_current=True,
            ),
        ]
    authorize_parsed_facts(db_session, document=doc, facts=growth_facts)
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/rev_test", headers=auth_headers(user)
    )

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
            "value": 5.0,
            "provenance": {
                "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2026-01-09",
                    "is_active_report": True,
            },
        },
    ]


def test_lookup_stock_by_ticker_not_found(client, db_session, auth_headers):
    user = User(email="ticker_missing@example.com")
    db_session.add(user)
    db_session.commit()
    response = client.get(
        "/api/v1/stocks/by_ticker/UNKNOWN", headers=auth_headers(user)
    )

    assert response.status_code == 404


def test_lookup_stock_by_ticker_never_exposes_another_users_private_facts(
    client, db_session, auth_headers
):
    owner = User(email="ticker_private_owner@example.com")
    viewer = User(email="ticker_private_viewer@example.com")
    stock = Stock(
        ticker="PRIVATE_TEST",
        exchange="NYSE",
        company_name="PRIVATE FACTS INC",
        is_active=True,
    )
    db_session.add_all([owner, viewer, stock])
    db_session.commit()
    db_session.add_all(
        [
            _piotroski_fact(
                user_id=owner.id,
                stock_id=stock.id,
                metric_key="score.piotroski.total",
                year=2026,
                value=9.0,
            ),
            MetricFact(
                user_id=owner.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_numeric=123.45,
                unit="USD/share",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="calculated",
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/PRIVATE_TEST",
        headers=auth_headers(viewer),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["oeps_series"] == []
    assert payload["piotroski_f_score_card"]["years"] == []
    assert payload["active_report_document_id"] is None


def test_lookup_stock_by_ticker_never_treats_admin_upload_as_shared(
    client, db_session, auth_headers
):
    admin_owner = User(
        email="ticker_admin_private_owner@example.com",
        role="admin",
    )
    viewer = User(email="ticker_admin_private_viewer@example.com")
    stock = Stock(
        ticker="ADMIN_PRIVATE",
        exchange="NYSE",
        company_name="ADMIN PRIVATE FACTS INC",
        is_active=True,
    )
    db_session.add_all([admin_owner, viewer, stock])
    db_session.flush()
    document = PdfDocument(
        user_id=admin_owner.id,
        stock_id=stock.id,
        file_name="admin-private.pdf",
        source="value_line",
        file_storage_key="tests/admin-private.pdf",
        parse_status="parsed",
        report_date=date(2026, 8, 1),
    )
    db_session.add(document)
    db_session.flush()
    private_pe = MetricFact(
        user_id=admin_owner.id,
        stock_id=stock.id,
        metric_key="val.pe",
        value_numeric=7.0,
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

    response = client.get(
        "/api/v1/stocks/by_ticker/ADMIN_PRIVATE",
        headers=auth_headers(viewer),
    )
    facts_response = client.get(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(viewer),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["pe"] is None
    assert payload["pe_provenance"] is None
    assert payload["active_report_document_id"] is None
    assert payload["active_report_date"] is None
    assert facts_response.status_code == 200, facts_response.text
    assert facts_response.json() == []
