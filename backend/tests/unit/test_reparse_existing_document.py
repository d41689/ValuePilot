from datetime import date

from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument, DocumentPage
from app.models.extractions import MetricExtraction
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
    db_session.refresh(doc)
    assert doc.report_date == date(2026, 1, 2)


def test_reparse_existing_document_falls_back_to_pdf_words_when_cached_text_missing(db_session):
    user = User(email="reparse_words_fallback@example.com")
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
        raw_text=None,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add(
        DocumentPage(
            document_id=doc.id,
            page_number=1,
            page_text="",
            text_extraction_method="native_text",
        )
    )
    db_session.commit()

    pages = [
        (
            1,
            "TESTCO\nNYSE-NEWP\nRECENT PRICE 10\nVALUE LINE\nAnalystX January 2, 2026\n",
            [],
        )
    ]

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ):
        service = IngestionService(db_session)
        service.reparse_existing_document(user_id=user.id, document_id=doc.id, reextract_pdf=False)

    facts = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.user_id == user.id,
            MetricFact.metric_key == "mkt.price",
            MetricFact.is_current.is_(True),
        )
        .all()
    )
    assert facts
    assert any(f.value_numeric == 10.0 for f in facts)


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


def test_reparse_existing_document_keeps_newer_document_current_for_same_metric_period(db_session):
    user = User(email="reparse_precedence_old@example.com")
    db_session.add(user)
    db_session.commit()

    stock = Stock(ticker="NEWP", exchange="NYSE", company_name="TESTCO")
    db_session.add(stock)
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="old.pdf",
        source="upload",
        file_storage_key="/tmp/old.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        identity_needs_review=False,
        raw_text="TESTCO RECENT 68.11\nNYSE-NEWP\nVALUE LINE\nAnalystX January 2, 2026\n",
        report_date=date(2026, 1, 2),
    )
    new_doc = PdfDocument(
        user_id=user.id,
        file_name="new.pdf",
        source="upload",
        file_storage_key="/tmp/new.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        identity_needs_review=False,
        raw_text="TESTCO RECENT 70.00\nNYSE-NEWP\nVALUE LINE\nAnalystX April 2, 2026\n",
        report_date=date(2026, 4, 2),
    )
    db_session.add_all([old_doc, new_doc])
    db_session.commit()

    db_session.add(
        DocumentPage(
            document_id=old_doc.id,
            page_number=1,
            page_text=old_doc.raw_text,
            text_extraction_method="native_text",
        )
    )
    db_session.add(
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
        )
    )
    db_session.commit()

    service = IngestionService(db_session)
    with patch.object(
        service.mapping_spec,
        "generate_facts",
        return_value=(
            [
                {
                    "metric_key": "is.net_income",
                    "value_numeric": 100.0,
                    "value_text": None,
                    "value_json": {"fact_nature": "actual"},
                    "unit": "USD",
                    "period_type": "FY",
                    "period_end_date": date(2024, 12, 31),
                }
            ],
            set(),
            set(),
        ),
    ):
        service.reparse_existing_document(user_id=user.id, document_id=old_doc.id, reextract_pdf=False)

    facts = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.user_id == user.id,
            MetricFact.metric_key == "is.net_income",
            MetricFact.period_type == "FY",
            MetricFact.period_end_date == date(2024, 12, 31),
        )
        .order_by(MetricFact.source_document_id.asc(), MetricFact.id.asc())
        .all()
    )

    assert len(facts) == 2
    old_fact = next(f for f in facts if f.source_document_id == old_doc.id)
    new_fact = next(f for f in facts if f.source_document_id == new_doc.id)
    assert old_fact.value_numeric == 100.0
    assert old_fact.is_current is False
    assert new_fact.value_numeric == 120.0
    assert new_fact.is_current is True


def test_reparse_existing_document_promotes_newer_document_for_same_metric_period(db_session):
    user = User(email="reparse_precedence_new@example.com")
    db_session.add(user)
    db_session.commit()

    stock = Stock(ticker="NEWP", exchange="NYSE", company_name="TESTCO")
    db_session.add(stock)
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="old.pdf",
        source="upload",
        file_storage_key="/tmp/old.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        identity_needs_review=False,
        report_date=date(2026, 1, 2),
    )
    new_doc = PdfDocument(
        user_id=user.id,
        file_name="new.pdf",
        source="upload",
        file_storage_key="/tmp/new.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        identity_needs_review=False,
        raw_text="TESTCO RECENT 70.00\nNYSE-NEWP\nVALUE LINE\nAnalystX April 2, 2026\n",
        report_date=date(2026, 4, 2),
    )
    db_session.add_all([old_doc, new_doc])
    db_session.commit()

    db_session.add(
        DocumentPage(
            document_id=new_doc.id,
            page_number=1,
            page_text=new_doc.raw_text,
            text_extraction_method="native_text",
        )
    )
    db_session.add(
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
            is_current=True,
        )
    )
    db_session.commit()

    service = IngestionService(db_session)
    with patch.object(
        service.mapping_spec,
        "generate_facts",
        return_value=(
            [
                {
                    "metric_key": "is.net_income",
                    "value_numeric": 120.0,
                    "value_text": None,
                    "value_json": {"fact_nature": "actual"},
                    "unit": "USD",
                    "period_type": "FY",
                    "period_end_date": date(2024, 12, 31),
                }
            ],
            set(),
            set(),
        ),
    ):
        service.reparse_existing_document(user_id=user.id, document_id=new_doc.id, reextract_pdf=False)

    facts = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.user_id == user.id,
            MetricFact.metric_key == "is.net_income",
            MetricFact.period_type == "FY",
            MetricFact.period_end_date == date(2024, 12, 31),
        )
        .order_by(MetricFact.source_document_id.asc(), MetricFact.id.asc())
        .all()
    )

    assert len(facts) == 2
    old_fact = next(f for f in facts if f.source_document_id == old_doc.id)
    new_fact = next(f for f in facts if f.source_document_id == new_doc.id)
    assert old_fact.is_current is False
    assert new_fact.value_numeric == 120.0
    assert new_fact.is_current is True


def test_reparse_existing_document_replaces_prior_document_snapshot_when_identity_changes(db_session):
    user = User(email="reparse_identity_change@example.com")
    db_session.add(user)
    db_session.commit()

    old_stock = Stock(ticker="FNVD", exchange="NYSE", company_name="Franco-Nevada Old")
    new_stock = Stock(ticker="FNV", exchange="NYSE", company_name="Franco-Nevada Corp.")
    db_session.add_all([old_stock, new_stock])
    db_session.commit()

    text = "FRANCO-NEVADA RECENT PRICE 10\nNYSE-FNV\nVALUE LINE\nKevin Downing January 2, 2026\n"
    doc = PdfDocument(
        user_id=user.id,
        file_name="FNV.pdf",
        source="upload",
        file_storage_key="/tmp/fnv.pdf",
        parse_status="parsed",
        stock_id=old_stock.id,
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
    db_session.add(
        MetricExtraction(
            user_id=user.id,
            document_id=doc.id,
            page_number=1,
            field_key="recent_price",
            raw_value_text="9",
            original_text_snippet="RECENT PRICE 9",
            parsed_value_json={"raw": "9"},
            confidence_score=0.5,
            bbox_json=None,
            parser_template_id=None,
            parser_version="v1",
        )
    )
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=old_stock.id,
            metric_key="mkt.price",
            value_json={"raw": "9", "normalized": 9.0, "unit": "USD"},
            value_numeric=9.0,
            unit="USD",
            period_type="AS_OF",
            period_end_date=date(2026, 1, 2),
            source_type="parsed",
            source_document_id=doc.id,
            source_ref_id=None,
            is_current=True,
        )
    )
    db_session.commit()

    service = IngestionService(db_session)
    service.reparse_existing_document(user_id=user.id, document_id=doc.id, reextract_pdf=False)

    db_session.expire_all()
    db_session.refresh(doc)
    facts = (
        db_session.query(MetricFact)
        .filter(
            MetricFact.source_document_id == doc.id,
            MetricFact.source_type == "parsed",
        )
        .order_by(MetricFact.id.asc())
        .all()
    )
    extractions = (
        db_session.query(MetricExtraction)
        .filter(MetricExtraction.document_id == doc.id)
        .order_by(MetricExtraction.id.asc())
        .all()
    )

    assert facts
    assert doc.stock_id is not None
    assert doc.stock_id != old_stock.id
    assert {fact.stock_id for fact in facts} == {doc.stock_id}
    assert all(fact.is_current for fact in facts)
    assert all(fact.stock_id != old_stock.id for fact in facts)
    assert extractions
    assert all(extraction.raw_value_text != "9" for extraction in extractions)
