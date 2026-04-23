from datetime import date

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User
from scripts.backfill_owners_earnings_fact_nature import backfill_in_session


def test_backfill_owners_earnings_fact_nature_uses_source_inputs(db_session):
    user = User(email="owners_earnings_backfill@example.com")
    stock = Stock(ticker="OEPS", exchange="NYSE", company_name="Owners Earnings Test")
    db_session.add_all([user, stock])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="owners-earnings.pdf",
        source="upload",
        file_storage_key="/tmp/owners-earnings.pdf",
        parse_status="parsed",
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    period_end = date(2025, 12, 31)

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"fact_nature": "estimate"},
                    value_numeric=3.0,
                    unit="USD",
                    period_type="FY",
                    period_end_date=period_end,
                    source_type="parsed",
                    source_document_id=doc.id,
                    is_current=True,
                ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"fact_nature": "actual"},
                    value_numeric=1.0,
                    unit="USD",
                    period_type="FY",
                    period_end_date=period_end,
                    source_type="parsed",
                    source_document_id=doc.id,
                    is_current=True,
                ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "2.0"},
                    value_numeric=2.0,
                    unit="USD",
                    period_type="FY",
                    period_end_date=period_end,
                    source_type="parsed",
                    source_document_id=doc.id,
                    is_current=True,
                ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share_normalized",
                value_json={"raw": "2.0"},
                    value_numeric=2.0,
                    unit="USD",
                    period_type="AS_OF",
                    period_end_date=date(2026, 1, 9),
                    source_type="parsed",
                    source_document_id=doc.id,
                    is_current=True,
                ),
        ]
    )
    db_session.commit()

    target_ids = [
        fact.id
        for fact in db_session.query(MetricFact)
        .filter(MetricFact.stock_id == stock.id)
        .all()
        if fact.metric_key.startswith("owners_earnings_per_share")
    ]
    result = backfill_in_session(db_session, dry_run=False, metric_fact_ids=target_ids)

    assert result == {"matched": 2, "updated": 2}

    facts = {
        fact.metric_key: fact
        for fact in db_session.query(MetricFact)
        .filter(MetricFact.stock_id == stock.id)
        .all()
        if fact.metric_key.startswith("owners_earnings_per_share")
    }
    assert facts["owners_earnings_per_share"].value_json["fact_nature"] == "estimate"
    assert facts["owners_earnings_per_share_normalized"].value_json["fact_nature"] == "snapshot"


def test_backfill_owners_earnings_fact_nature_dry_run_rolls_back(db_session):
    user = User(email="owners_earnings_backfill_dry_run@example.com")
    stock = Stock(ticker="OEPSDRY", exchange="NYSE", company_name="Owners Earnings Dry")
    db_session.add_all([user, stock])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="owners-earnings-dry.pdf",
        source="upload",
        file_storage_key="/tmp/owners-earnings-dry.pdf",
        parse_status="parsed",
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="owners_earnings_per_share_normalized",
        value_json={"raw": "3.0"},
        value_numeric=3.0,
        unit="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 1, 9),
        source_type="parsed",
        source_document_id=doc.id,
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()

    result = backfill_in_session(db_session, dry_run=True, metric_fact_ids=[fact.id])
    assert result == {"matched": 1, "updated": 1}

    db_session.refresh(fact)
    assert fact.value_json == {"raw": "3.0"}
