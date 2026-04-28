import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.ingestion.pdf_extractor import PdfExtractor
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User


FIXTURE_PDF = Path("tests/fixtures/value_line/axs.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/axs_v1.expected.json")


def load_expected_json() -> dict:
    with EXPECTED_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def upload_axs(client, db_session, user_factory, auth_headers) -> tuple[User, Stock, dict, int]:
    user = user_factory("axs_metric_facts@example.com")
    headers = auth_headers(user)

    expected = load_expected_json()
    pages = PdfExtractor.extract_pages_with_words(FIXTURE_PDF)

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ):
        resp = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("axs.pdf", b"%PDF-1.4\n%fake\n", "application/pdf")},
        )

    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["document_id"]

    stock = (
        db_session.query(Stock)
        .filter(Stock.ticker == "AXS", Stock.exchange == "NYSE")
        .one()
    )

    return user, stock, expected, doc_id


def _fact(
    db_session,
    *,
    stock_id: int,
    metric_key: str,
    source_document_id: int | None = None,
    period_end_date: date | None = None,
    period_type: str | None = None,
) -> MetricFact:
    query = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key == metric_key,
            MetricFact.source_type == "parsed",
            MetricFact.is_current.is_(True),
        )
        .order_by(MetricFact.id.desc())
    )
    if source_document_id is not None:
        query = query.filter(MetricFact.source_document_id == source_document_id)
    if period_end_date is not None:
        query = query.filter(MetricFact.period_end_date == period_end_date)
    if period_type is not None:
        query = query.filter(MetricFact.period_type == period_type)
    result = query.first()
    assert result is not None
    return result


def test_rating_event_text_fields_remain_evidence_only(client, db_session, user_factory, auth_headers):
    _, stock, expected, doc_id = upload_axs(client, db_session, user_factory, auth_headers)

    for key in ("timeliness", "safety", "technical"):
        event_date = date.fromisoformat(expected["ratings"][key]["event"]["date"])
        fact = (
            db_session.query(MetricFact)
            .filter(
                MetricFact.stock_id == stock.id,
                MetricFact.metric_key == f"rating.{key}_change",
                MetricFact.source_type == "parsed",
                MetricFact.source_document_id == doc_id,
                MetricFact.period_type == "EVENT",
                MetricFact.period_end_date == event_date,
                MetricFact.is_current.is_(True),
            )
            .first()
        )
        assert fact is None


def test_metric_facts_use_capital_structure_as_of_dates(client, db_session, user_factory, auth_headers):
    _, stock, expected, doc_id = upload_axs(client, db_session, user_factory, auth_headers)

    cap_as_of = date.fromisoformat(expected["capital_structure"]["as_of"])
    market_as_of = date.fromisoformat(expected["capital_structure"]["market_cap"]["as_of"])
    shares_as_of = date.fromisoformat(expected["capital_structure"]["common_stock"]["as_of"])

    total_debt = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="cap.total_debt",
        source_document_id=doc_id,
        period_end_date=cap_as_of,
    )
    assert total_debt.period_end_date == cap_as_of

    market_cap = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="mkt.market_cap",
        source_document_id=doc_id,
        period_end_date=market_as_of,
    )
    assert market_cap.period_end_date == market_as_of

    shares = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="equity.shares_outstanding",
        source_document_id=doc_id,
        period_end_date=shares_as_of,
    )
    assert shares.period_end_date == shares_as_of


def test_quarterly_series_full_year_facts_are_written(client, db_session, user_factory, auth_headers):
    _, stock, expected, doc_id = upload_axs(client, db_session, user_factory, auth_headers)

    premiums_2024 = expected["net_premiums_earned"]["by_year"][2]["full_year"]["value"]
    fact = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="is.net_premiums_earned",
        source_document_id=doc_id,
        period_end_date=date(2024, 12, 31),
        period_type="FY",
    )
    assert fact.value_numeric == premiums_2024 * 1_000_000.0
    assert fact.period_type == "FY"

    eps_2024 = expected["earnings_per_share"]["by_year"][2]["full_year"]["value"]
    eps_fact = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="per_share.eps",
        source_document_id=doc_id,
        period_end_date=date(2024, 12, 31),
        period_type="FY",
    )
    assert eps_fact.value_numeric == eps_2024
    assert eps_fact.period_type == "FY"

    q1_fact = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="per_share.eps",
        source_document_id=doc_id,
        period_end_date=date(2024, 3, 31),
        period_type="Q",
    )
    assert q1_fact.period_type == "Q"


def test_value_line_upload_creates_piotroski_partial_diagnostic_fact(
    client, db_session, user_factory, auth_headers
):
    _, stock, _, _ = upload_axs(client, db_session, user_factory, auth_headers)

    total = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "score.piotroski.total",
            MetricFact.source_type == "calculated",
            MetricFact.is_current.is_(True),
        )
        .order_by(MetricFact.period_end_date.desc())
        .first()
    )

    assert total is not None
    assert total.source_document_id is None
    assert total.value_numeric is None
    assert total.value_json["status"] == "partial"
    assert total.value_json["variant"] == "insurance_adjusted"
    assert total.value_json["calculation_version"] == "piotroski_value_line_v1"
    assert "missing_indicators" in total.value_json


def test_annual_financials_series_are_expanded(client, db_session, user_factory, auth_headers):
    _, stock, expected, doc_id = upload_axs(client, db_session, user_factory, auth_headers)

    net_profit_2017 = expected["annual_financials"]["income_statement_usd_millions"]["net_profit"]["2017"]
    fact = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="is.net_income",
        source_document_id=doc_id,
        period_end_date=date(2017, 12, 31),
        period_type="FY",
    )
    assert fact.value_numeric == net_profit_2017 * 1_000_000.0
    assert fact.period_type == "FY"


def test_annual_financials_estimate_years_keep_estimate_semantics(client, db_session, user_factory, auth_headers):
    _, stock, _, doc_id = upload_axs(client, db_session, user_factory, auth_headers)

    estimate_2025 = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="is.net_income",
        source_document_id=doc_id,
        period_end_date=date(2025, 12, 31),
        period_type="FY",
    )
    assert estimate_2025.value_json is not None
    assert "is_estimate" not in estimate_2025.value_json
    assert estimate_2025.value_json.get("fact_nature") == "estimate"

    actual_2024 = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="is.net_income",
        source_document_id=doc_id,
        period_end_date=date(2024, 12, 31),
        period_type="FY",
    )
    assert actual_2024.value_json is not None
    assert "is_estimate" not in actual_2024.value_json
    assert actual_2024.value_json.get("fact_nature") == "actual"


def test_commentary_and_projection_range_remain_non_numeric(client, db_session, user_factory, auth_headers):
    _, stock, _, doc_id = upload_axs(client, db_session, user_factory, auth_headers)

    commentary = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "analyst.commentary",
            MetricFact.source_type == "parsed",
            MetricFact.source_document_id == doc_id,
            MetricFact.is_current.is_(True),
        )
        .first()
    )
    assert commentary is None

    strength = _fact(
        db_session,
        stock_id=stock.id,
        metric_key="quality.financial_strength",
        source_document_id=doc_id,
    )
    assert strength.value_numeric is None


def test_dedupe_within_document_for_fy_metrics(client, db_session, user_factory, auth_headers):
    _, stock, _, doc_id = upload_axs(client, db_session, user_factory, auth_headers)

    results = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.net_income",
            MetricFact.period_type == "FY",
            MetricFact.period_end_date == date(2025, 12, 31),
            MetricFact.source_type == "parsed",
            MetricFact.source_document_id == doc_id,
        )
        .all()
    )
    assert len(results) == 1
