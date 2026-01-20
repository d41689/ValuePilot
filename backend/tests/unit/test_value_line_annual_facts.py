import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.ingestion.pdf_extractor import PdfExtractor
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User


FIXTURE_PDF = Path("tests/fixtures/value_line/smith ao.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/ao_smith_v1.expected.json")


def load_expected_json() -> dict:
    with EXPECTED_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_upload_writes_annual_facts_latest_actual_and_estimate(client, db_session):
    user = User(email="annual_facts_test@example.com")
    db_session.add(user)
    db_session.commit()

    expected = load_expected_json()
    annual = expected["annual_financials"]
    years = annual["meta"]["historical_years"]
    actual_year = years[-2]
    estimate_year = years[-1]

    text = PdfExtractor.extract_text(FIXTURE_PDF)
    pages = [(1, text, [])]

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ):
        resp = client.post(
            f"/api/v1/documents/upload?user_id={user.id}",
            files={"file": ("single.pdf", b"%PDF-1.4\n%fake\n", "application/pdf")},
        )

    assert resp.status_code == 200, resp.text

    stock = (
        db_session.query(Stock)
        .filter(Stock.ticker == "AOS", Stock.exchange == "NYSE")
        .one()
    )

    net_profit_facts = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.net_income",
            MetricFact.source_type == "parsed",
        )
        .all()
    )
    assert net_profit_facts, "expected is.net_income facts"

    actual_fact = next(
        (
            f
            for f in net_profit_facts
            if f.period_end_date == date(actual_year, 12, 31) and f.is_current
        ),
        None,
    )
    estimate_fact = next(
        (
            f
            for f in net_profit_facts
            if f.period_end_date == date(estimate_year, 12, 31) and f.is_current
        ),
        None,
    )
    assert actual_fact is not None
    assert actual_fact.is_current is True
    assert actual_fact.period_type == "FY"
    actual_is_estimate = actual_fact.value_json.get("is_estimate") if actual_fact.value_json else None
    assert actual_is_estimate in (False, None)

    net_profit = annual["income_statement_usd_millions"]["net_profit"]
    expected_actual = net_profit[str(actual_year)]
    assert actual_fact.value_numeric == expected_actual * 1_000_000.0

    expected_estimate = net_profit.get(str(estimate_year))
    if expected_estimate is None:
        assert estimate_fact is None
    else:
        assert estimate_fact is not None
        assert estimate_fact.is_current is True
        assert estimate_fact.period_type == "FY"
        estimate_is_estimate = estimate_fact.value_json.get("is_estimate") if estimate_fact.value_json else None
        assert estimate_is_estimate is True
        assert estimate_fact.value_numeric == expected_estimate * 1_000_000.0

    dividend_facts = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "val.avg_dividend_yield",
            MetricFact.source_type == "parsed",
        )
        .all()
    )
    assert dividend_facts, "expected val.avg_dividend_yield facts"

    actual_dividend = next(
        (
            f
            for f in dividend_facts
            if f.period_end_date == date(actual_year, 12, 31) and f.is_current
        ),
        None,
    )
    assert actual_dividend is not None
    expected_dividend = annual["valuation_metrics"]["avg_annual_dividend_yield_pct"][str(actual_year)]
    assert actual_dividend.value_numeric == expected_dividend / 100.0

    estimate_dividend = next(
        (
            f
            for f in dividend_facts
            if f.period_end_date == date(estimate_year, 12, 31) and f.is_current
        ),
        None,
    )
    expected_estimate = annual["valuation_metrics"]["avg_annual_dividend_yield_pct"].get(str(estimate_year))
    if expected_estimate is None:
        assert estimate_dividend is None
    else:
        assert estimate_dividend is not None
        assert estimate_dividend.value_numeric == expected_estimate / 100.0
        dividend_is_estimate = estimate_dividend.value_json.get("is_estimate") if estimate_dividend.value_json else None
        assert dividend_is_estimate is True
