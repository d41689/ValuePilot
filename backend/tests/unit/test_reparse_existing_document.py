from datetime import date

from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument, DocumentPage
from app.models.facts import MetricFact
from app.services.ingestion_service import IngestionService
from unittest.mock import patch


def test_reparse_existing_document_deactivates_prior_parsed_facts(db_session):
    text = "TESTCO RECENT 68.11\nNYSE-NEWP\nVALUE LINE\nAnalystX January 2, 2026\n"
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
        metric_key="mkt.price",
        value_json={"raw": "68.11", "normalized": 68.11, "unit": "USD"},
        value_numeric=68.11,
        unit="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 1, 2),
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
        .filter(MetricFact.user_id == user.id, MetricFact.metric_key == "mkt.price")
        .order_by(MetricFact.id)
        .all()
    )
    assert len(facts) == 2
    assert facts[0].is_current is False
    assert facts[1].is_current is True


def test_reparse_existing_document_multi_page_updates_all_pages(db_session):
    user = User(email="reparse_multipage@example.com")
    db_session.add(user)
    db_session.commit()

    stock_one = Stock(ticker="ZZAQ", exchange="NYSE", company_name="Alpha Co")
    stock_two = Stock(ticker="ZZBQ", exchange="NDQ", company_name="Beta Co")
    db_session.add_all([stock_one, stock_two])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="multi.pdf",
        source="upload",
        file_storage_key="/tmp/multi.pdf",
        parse_status="parsed_partial",
        stock_id=None,
        identity_needs_review=False,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add_all(
        [
            DocumentPage(
                document_id=doc.id,
                page_number=1,
                page_text="stub1",
                text_extraction_method="native_text",
            ),
            DocumentPage(
                document_id=doc.id,
                page_number=2,
                page_text="stub2",
                text_extraction_method="native_text",
            ),
        ]
    )
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock_one.id,
                metric_key="mkt.price",
                value_json={"raw": "5", "normalized": 5, "unit": "USD"},
                value_numeric=5.0,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 2),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_two.id,
                metric_key="mkt.price",
                value_json={"raw": "6", "normalized": 6, "unit": "USD"},
                value_numeric=6.0,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 2),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    pages = [
        (1, "ALPHA CO\nNYSE-ZZAQ\nRECENT PRICE 10\nVALUE LINE\nAnalystX January 2, 2026\n", []),
        (2, "BETA CO\nZZBQ (NDQ)\nRECENT PRICE 20\nVALUE LINE\nAnalystY January 2, 2026\n", []),
    ]

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ):
        service = IngestionService(db_session)
        service.reparse_existing_document(user_id=user.id, document_id=doc.id, reextract_pdf=True)

    db_session.expire_all()
    facts = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.user_id == user.id,
            MetricFact.metric_key == "mkt.price",
        )
        .order_by(MetricFact.id)
        .all()
    )

    assert any(f.is_current and f.value_numeric == 10.0 for f in facts)
    assert any(f.is_current and f.value_numeric == 20.0 for f in facts)
    assert doc.stock_id is None


def test_reparse_existing_document_ignores_industry_pages_in_status(db_session):
    user = User(email="reparse_industry@example.com")
    db_session.add(user)
    db_session.commit()

    stock_one = Stock(ticker="ALP", exchange="NYSE", company_name="Alpha Co")
    stock_two = Stock(ticker="BET", exchange="NDQ", company_name="Beta Co")
    db_session.add_all([stock_one, stock_two])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="industry.pdf",
        source="upload",
        file_storage_key="/tmp/industry.pdf",
        parse_status="uploaded",
        stock_id=None,
        identity_needs_review=False,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add_all(
        [
            DocumentPage(
                document_id=doc.id,
                page_number=1,
                page_text="ALPHA CO\nNYSE-ALP\nRECENT PRICE 10\nVALUE LINE\nAnalystX January 2, 2026\n",
                text_extraction_method="native_text",
            ),
            DocumentPage(
                document_id=doc.id,
                page_number=2,
                page_text="INDUSTRY TIMELINESS: 60\nVALUE LINE\n",
                text_extraction_method="native_text",
            ),
            DocumentPage(
                document_id=doc.id,
                page_number=3,
                page_text="BETA CO\nNDQ-BET\nRECENT PRICE 20\nVALUE LINE\nAnalystY January 2, 2026\n",
                text_extraction_method="native_text",
            ),
        ]
    )
    db_session.commit()

    service = IngestionService(db_session)
    service.reparse_existing_document(user_id=user.id, document_id=doc.id, reextract_pdf=False)

    db_session.refresh(doc)
    assert doc.parse_status == "parsed"
