from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument, DocumentPage
from app.models.facts import MetricFact
from app.services.ingestion_service import IngestionService


def test_reparse_existing_document_deactivates_prior_parsed_facts(db_session):
    text = "TESTCO RECENT 68.11\nNYSE-NEWP\n"
    user = User(email="reparse_test@example.com")
    db_session.add(user)
    db_session.commit()

    stock = Stock(ticker="NEWP", exchange="NYSE", company_name="TESTCO")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="smith.pdf",
        source="upload",
        file_storage_key="/tmp/does-not-matter.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        identity_needs_review=False,
        raw_text=text,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add(
        DocumentPage(
            document_id=doc.id,
            page_number=1,
            page_text=text,
            text_extraction_method="native_text",
        )
    )
    db_session.commit()

    # Simulate a previous parse for the same metric_key
    old = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="recent_price",
        value_json={"raw": "68.11", "normalized": 68.11, "unit": "USD"},
        value_numeric=68.11,
        unit="USD",
        source_type="parsed",
        source_ref_id=None,
        is_current=True,
    )
    db_session.add(old)
    db_session.commit()

    service = IngestionService(db_session)
    service.reparse_existing_document(user_id=user.id, document_id=doc.id, reextract_pdf=False)

    facts = (
        db_session.query(MetricFact)
        .filter(MetricFact.stock_id == stock.id, MetricFact.metric_key == "recent_price")
        .order_by(MetricFact.id)
        .all()
    )
    assert len(facts) == 2
    assert facts[0].is_current is False
    assert facts[1].is_current is True
