from datetime import date, datetime, timezone

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.stocks import Stock, StockPrice
from app.models.users import User
from app.api.v1.endpoints import stocks as stocks_endpoint
from app.services import dcf_inputs
from app.services.dcf_inputs import DcfEvaluationClock


def test_lookup_uses_one_et_effective_clock_for_all_method_gates(
    client, db_session, auth_headers, monkeypatch
):
    user = User(email="ticker-clock@example.com")
    stock = Stock(ticker="CLOCK", exchange="NYSE", company_name="Clock Inc")
    db_session.add_all([user, stock])
    db_session.commit()
    evaluated_at = datetime(2026, 9, 4, 1, 30, tzinfo=timezone.utc)
    effective_as_of = date(2026, 9, 3)
    calls = []
    original_gate = dcf_inputs.reviewed_method_gate

    def capture_gate(session, **kwargs):
        calls.append(kwargs)
        return original_gate(session, **kwargs)

    monkeypatch.setattr(
        stocks_endpoint,
        "dcf_evaluation_clock",
        lambda: DcfEvaluationClock(evaluated_at, effective_as_of),
    )
    monkeypatch.setattr(dcf_inputs, "reviewed_method_gate", capture_gate)

    response = client.get(
        "/api/v1/stocks/by_ticker/CLOCK", headers=auth_headers(user)
    )

    assert response.status_code == 200, response.text
    assert len(calls) == 4
    assert {call["effective_as_of"] for call in calls} == {effective_as_of}
    assert {call["knowledge_at"] for call in calls} == {evaluated_at}
    for gate in response.json()["system_method_gates"].values():
        assert gate["effective_as_of"] == "2026-09-03"
        assert gate["knowledge_at"] == "2026-09-04T01:30:00+00:00"


def _piotroski_fact(
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    year: int,
    value: float | None,
    value_json: dict | None = None,
    lineage_fact_id: int | None = None,
) -> MetricFact:
    metadata = value_json or {
        "status": "calculated",
        "variant": "valueline_proxy",
        "fact_nature": (
            "estimate"
            if metric_key == "score.piotroski.roa_positive" and year == 2026
            else "actual"
        ),
        "fiscal_year": year,
    }
    if lineage_fact_id is not None:
        inputs = metadata.setdefault(
            "inputs",
            [
                {
                    "metric_key": f"{metric_key}.input",
                    "value_numeric": value,
                    "period_end_date": f"{year}-12-31",
                    "fact_nature": "actual",
                }
            ],
        )
        for item in inputs:
            if isinstance(item, dict):
                item.setdefault("fact_id", lineage_fact_id)
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value,
        value_json=metadata,
        unit="score_component" if metric_key != "score.piotroski.total" else "score_total",
        period_type="FY",
        period_end_date=date(year, 12, 31),
        source_type="calculated",
        is_current=True,
    )


def test_lookup_stock_by_ticker_returns_dynamic_piotroski_card_from_current_stock(
    client, db_session, auth_headers
):
    user = User(email="ticker_f_score@example.com")
    stock = Stock(ticker="FSC_TEST", exchange="NYSE", company_name="F SCORE INC", is_active=True)
    other_stock = Stock(ticker="OTHER_FS", exchange="NYSE", company_name="OTHER SCORE", is_active=True)
    db_session.add_all([user, stock, other_stock])
    db_session.flush()
    lineage_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="piotroski.test_input",
        value_numeric=1,
        value_json={"manual_role": "original_input"},
        unit="ratio",
        period_type="AS_OF",
        period_end_date=date(2026, 12, 31),
        source_type="manual",
        is_current=True,
    )
    other_lineage_fact = MetricFact(
        user_id=user.id,
        stock_id=other_stock.id,
        metric_key="piotroski.test_input",
        value_numeric=1,
        value_json={"manual_role": "original_input"},
        unit="ratio",
        period_type="AS_OF",
        period_end_date=date(2026, 12, 31),
        source_type="manual",
        is_current=True,
    )
    db_session.add_all([lineage_fact, other_lineage_fact])
    db_session.flush()

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
                    lineage_fact_id=lineage_fact.id,
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
                lineage_fact_id=lineage_fact.id,
            )
        )
    facts.append(
        _piotroski_fact(
            user_id=user.id,
            stock_id=other_stock.id,
            metric_key="score.piotroski.total",
            year=2026,
            value=2.0,
            lineage_fact_id=other_lineage_fact.id,
        )
    )
    db_session.add_all(facts)
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/fsc_test", headers=auth_headers(user)
    )

    assert response.status_code == 200
    card = response.json()["piotroski_f_score_card"]
    assert card["years"] == [2022, 2023, 2024, 2025, 2026]
    assert len(card["rows"]) == 10
    rows_by_key = {row["metric_key"]: row for row in card["rows"]}
    assert list(rows_by_key) == [
        "score.piotroski.roa_positive",
        "score.piotroski.cfo_positive",
        "score.piotroski.roa_improving",
        "score.piotroski.accrual_quality",
        "score.piotroski.leverage_declining",
        "score.piotroski.current_ratio_improving",
        "score.piotroski.no_dilution",
        "score.piotroski.gross_margin_improving",
        "score.piotroski.asset_turnover_improving",
        "score.piotroski.total",
    ]

    roa_row = rows_by_key["score.piotroski.roa_positive"]
    assert roa_row["formula_details"]["used_values"] == [
        {
            "metric_key": "score.piotroski.roa_positive.input",
            "value_numeric": 10.0,
            "period_end_date": "2022-12-31",
            "fact_nature": "actual",
        },
        {
            "metric_key": "score.piotroski.roa_positive.input",
            "value_numeric": 10.0,
            "period_end_date": "2023-12-31",
            "fact_nature": "actual",
        },
        {
            "metric_key": "score.piotroski.roa_positive.input",
            "value_numeric": 10.0,
            "period_end_date": "2024-12-31",
            "fact_nature": "actual",
        },
        {
            "metric_key": "score.piotroski.roa_positive.input",
            "value_numeric": 10.0,
            "period_end_date": "2025-12-31",
            "fact_nature": "actual",
        },
        {
            "metric_key": "score.piotroski.roa_positive.input",
            "value_numeric": 10.0,
            "period_end_date": "2026-12-31",
            "fact_nature": "estimate",
        },
    ]
    assert roa_row["score_fact_natures"] == ["actual", "actual", "actual", "actual", "estimate"]

    for metric_key, row in rows_by_key.items():
        if metric_key != "score.piotroski.total":
            assert len(row["formula_details"]["used_values"]) == 5
    assert rows_by_key["score.piotroski.total"]["formula_details"]["used_values"] == []


def test_lookup_stock_by_ticker_hides_piotroski_card_when_exact_lineage_is_missing(
    client, db_session, auth_headers
):
    user = User(email="ticker-f-score-missing-lineage@example.com")
    stock = Stock(
        ticker="FSC_NO_LINEAGE",
        exchange="NYSE",
        company_name="F SCORE NO LINEAGE INC",
        is_active=True,
    )
    db_session.add_all([user, stock])
    db_session.flush()
    db_session.add(
        _piotroski_fact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="score.piotroski.total",
            year=2025,
            value=9.0,
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/FSC_NO_LINEAGE",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    card = response.json()["piotroski_f_score_card"]
    assert card == {
        "years": [],
        "rows": [],
        "state": {
            "status": "unavailable",
            "reason_code": "unresolved_source_reconciliation",
            "blocking_reasons": ["derived_lineage_unavailable"],
        },
    }


def test_lookup_stock_by_ticker_returns_summary(client, db_session, auth_headers):
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

    facts = [
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
                value_json={
                    "raw": "5.1",
                    "normalized": 5.1,
                    "unit": "USD",
                    "user_authored_formula": True,
                },
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
                value_json={
                    "raw": "5.5",
                    "normalized": 5.5,
                    "unit": "USD",
                    "user_authored_formula": True,
                },
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
                value_json={
                    "raw": "5.3",
                    "normalized": 5.3,
                    "unit": "USD",
                    "user_authored_formula": True,
                },
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
                value_json={
                    "raw": "5.1",
                    "normalized": 5.1,
                    "unit": "USD",
                    "user_authored_formula": True,
                },
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
                value_json={
                    "raw": "4.9",
                    "normalized": 4.9,
                    "unit": "USD",
                    "user_authored_formula": True,
                },
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
                value_json={
                    "raw": "4.7",
                    "normalized": 4.7,
                    "unit": "USD",
                    "user_authored_formula": True,
                },
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
                value_json={
                    "raw": "4.5",
                    "normalized": 4.5,
                    "unit": "USD",
                    "user_authored_formula": True,
                },
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
    for fact in facts:
        fact.source_document_id = doc.id
        if fact.metric_key in {
            "per_share.eps",
            "is.depreciation",
            "per_share.capital_spending",
        }:
            fact.currency = "USD"
    db_session.add_all(facts)
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
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/coco_test", headers=auth_headers(user)
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "COCO_TEST"
    assert payload["exchange"] == "NDQ"
    assert payload["company_name"] == "VITA COCO"
    assert payload["report_price_reference"]["value"] == 54.52
    assert payload["report_price_reference"]["as_of_date"] == "2026-01-09"
    assert payload["report_price_reference"]["label"] == "report_reference"
    assert payload["current_price"]["status"] == "unavailable"
    assert payload["current_price"]["value"] is None
    assert payload["active_report_document_id"] == doc.id
    assert payload["active_report_date"] == "2026-01-09"
    assert payload["pe"] == 43.3
    assert isinstance(payload["pe"], (int, float))
    assert payload["report_price_reference"]["provenance"] == {
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
    assert isinstance(payload["oeps_normalized"], (int, float))
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
    assert all(
        isinstance(entry["value"], (int, float))
        for entry in payload["oeps_series"]
    )
    assert payload["dcf_inputs"]["valuation_currency"] == "USD"
    assert payload["dcf_inputs"]["currency_state"]["status"] == "available"
    assert payload["dcf_inputs"]["currency_state"]["reason_code"] is None
    assert len(payload["dcf_inputs"]["currency_state"]["provenance"]) == 3
    assert payload["dcf_inputs"]["input_manifest"]["manifest_version"] == "dcf-input-manifest-v1"
    assert payload["dcf_inputs"]["input_manifest"]["selection"] == "norm"
    assert payload["dcf_inputs"]["input_manifest"]["selected_year"] == 2024
    assert len(payload["dcf_inputs"]["input_manifest"]["facts"]) == 9
    assert len(payload["dcf_inputs"]["input_manifest_token"]) == 64
    assert {
        "role",
        "id",
        "stock_id",
        "metric_key",
        "source_type",
        "source_ref_id",
        "source_document_id",
        "period_type",
        "period_end_date",
        "value_numeric",
        "unit",
        "currency",
        "created_at",
    } == set(payload["dcf_inputs"]["input_manifest"]["facts"][0])
    manifest_times = {
        payload["dcf_inputs"]["input_manifest"]["evaluated_at"],
        *(
            entry["input_manifest"]["evaluated_at"]
            for entry in payload["dcf_inputs_series"]
        ),
    }
    assert len(manifest_times) == 1
    dcf_inputs_without_currency = {
        key: value
        for key, value in payload["dcf_inputs"].items()
        if key not in {
            "valuation_currency",
            "currency_state",
            "input_manifest",
            "input_manifest_token",
        }
    }
    assert dcf_inputs_without_currency == {
        "canonical_model_inputs": {
            "net_profit_per_share": "4.800",
            "depreciation_per_share": "0.900",
            "capital_spending_per_share": "0.600",
            "based_on_per_share": "5.100",
        },
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
    assert all(
        entry["valuation_currency"] == "USD"
        and entry["currency_state"]["status"] == "available"
        and entry["input_manifest"]["selection"] == entry["year"]
        and len(entry["input_manifest"]["facts"]) == 5
        for entry in payload["dcf_inputs_series"]
    )
    dcf_series_without_currency = [
        {
            key: value
            for key, value in entry.items()
            if key not in {
                "valuation_currency",
                "currency_state",
                "input_manifest",
                "input_manifest_token",
                "canonical_model_inputs",
            }
        }
        for entry in payload["dcf_inputs_series"]
    ]
    assert dcf_series_without_currency == [
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

    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=active_stock.id,
            metric_key="mkt.price",
            value_json={"raw": "429.99", "fact_nature": "snapshot"},
            value_numeric=429.99,
            unit="USD",
            period_type="AS_OF",
            period_end_date=date(2026, 5, 1),
            source_type="parsed",
            source_document_id=doc.id,
            is_current=True,
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/dup_test", headers=auth_headers(user)
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["id"] == active_stock.id
    assert payload["exchange"] == "NDQ"
    assert payload["report_price_reference"]["value"] == 429.99
    assert payload["active_report_document_id"] == doc.id


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

    db_session.add_all(
        [
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


def test_lookup_stock_by_ticker_uses_revenues_growth_when_sales_missing(
    client, db_session, auth_headers
):
    user = User(email="ticker_lookup_revenues@example.com")
    stock = Stock(ticker="REV_TEST", exchange="NDQ", company_name="REVENUES INC", is_active=True)
    db_session.add_all([user, stock])
    db_session.flush()
    doc = PdfDocument(
        user_id=user.id,
        file_name="revenues.pdf",
        source="value_line",
        file_storage_key="/tmp/revenues.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    db_session.add(doc)
    db_session.flush()

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
                source_document_id=doc.id,
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
                source_document_id=doc.id,
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
                source_document_id=doc.id,
                is_current=True,
            ),
        ]
    )
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


def test_lookup_stock_by_ticker_returns_typed_source_conflict_before_summary_aggregation(
    client, db_session, auth_headers
):
    user = User(email="ticker-source-conflict@example.com")
    stock = Stock(
        ticker="SUMMARY_CONFLICT",
        exchange="NYSE",
        company_name="SUMMARY CONFLICT INC",
        is_active=True,
    )
    db_session.add_all([user, stock])
    db_session.flush()
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_numeric=10,
                period_type="AS_OF",
                period_end_date=date(2026, 8, 31),
                source_type="parsed",
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_numeric=11,
                period_type="AS_OF",
                period_end_date=date(2026, 8, 31),
                source_type="manual",
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/SUMMARY_CONFLICT",
        headers=auth_headers(user),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "source_conflict",
        "message": (
            "stock_summary requires an explicit source selection; "
            "available sources: manual, parsed"
        ),
        "source_types": ["manual", "parsed"],
        "blocking_reasons": [],
    }


def test_lookup_stock_by_ticker_does_not_serialize_fact_known_after_evaluation_cutoff(
    client, db_session, auth_headers, monkeypatch
):
    user = User(email="ticker-post-cutoff@example.com")
    stock = Stock(
        ticker="POST_CUTOFF",
        exchange="NYSE",
        company_name="POST CUTOFF INC",
        is_active=True,
    )
    db_session.add_all([user, stock])
    db_session.flush()
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="val.pe",
            value_numeric=99,
            value_json={
                "mapping_id": "value-line.val.pe",
                "source_mapping_version": "value-line-spec-v2",
                "definition_basis": "adjusted",
                "dimensions_identity": "empty",
            },
            unit="ratio",
            period_type="AS_OF",
            period_end_date=date(2099, 9, 4),
            source_type="parsed",
            is_current=True,
            created_at=datetime(2099, 9, 4, 13, tzinfo=timezone.utc),
            updated_at=datetime(2099, 9, 4, 13, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        stocks_endpoint,
        "dcf_evaluation_clock",
        lambda: DcfEvaluationClock(
            datetime(2099, 9, 4, 12, tzinfo=timezone.utc),
            date(2099, 9, 4),
        ),
    )

    response = client.get(
        "/api/v1/stocks/by_ticker/POST_CUTOFF",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["pe"] is None
    assert payload["pe_provenance"] is None


def test_lookup_stock_by_ticker_returns_typed_source_conflict_before_growth_aggregation(
    client, db_session, auth_headers
):
    user = User(email="ticker-growth-conflict@example.com")
    stock = Stock(
        ticker="GROWTH_CONFLICT",
        exchange="NYSE",
        company_name="GROWTH CONFLICT INC",
        is_active=True,
    )
    db_session.add_all([user, stock])
    db_session.flush()
    for source_type, value in (("parsed", 0.05), ("manual", 0.06)):
        db_session.add(
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.sales.cagr_est",
                value_numeric=value,
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 8, 31),
                source_type=source_type,
                is_current=True,
            )
        )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/GROWTH_CONFLICT",
        headers=auth_headers(user),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_conflict"
    assert response.json()["detail"]["source_types"] == ["manual", "parsed"]
