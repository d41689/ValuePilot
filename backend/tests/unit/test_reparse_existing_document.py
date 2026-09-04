from datetime import date
from pathlib import Path

import pytest

from app.ingestion.pdf_extractor import PdfExtractor
from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument, DocumentPage, ValueLineParseRun
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


def test_reparse_existing_document_handles_mtdr_cached_text_without_pdf_words(db_session):
    pdf_path = Path("tests/fixtures/value_line/mtdr.pdf")
    pages = PdfExtractor.extract_pages_with_words(pdf_path)
    page_number, text, _ = pages[0]

    user = User(email="reparse_mtdr_cached_text@example.com")
    db_session.add(user)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="mtdr.pdf",
        source="upload",
        file_storage_key="/tmp/mtdr-missing.pdf",
        parse_status="failed",
        raw_text=text,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add(
        DocumentPage(
            document_id=doc.id,
            page_number=page_number,
            page_text=text,
            text_extraction_method="native_text",
        )
    )
    db_session.commit()

    IngestionService(db_session).reparse_existing_document(
        user_id=user.id,
        document_id=doc.id,
        reextract_pdf=False,
    )

    db_session.refresh(doc)
    assert doc.parse_status == "parsed"
    assert doc.report_date == date(2026, 4, 24)
    assert doc.stock.ticker == "MTDR"
    assert doc.stock.exchange == "NYSE"
    assert doc.stock.company_name == "MATADOR RESOURCES"


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
                    "value_json": {
                        "fact_nature": "actual",
                        "mapping_id": "is.net_income.fy",
                        "source_mapping_version": service.mapping_spec.source_mapping_version,
                        "definition_basis": "adjusted",
                        "fiscal_year": 2024,
                        "period_duration_kind": "fiscal_year",
                        "dimensions_identity": "empty",
                    },
                    "unit": "USD",
                    "currency": "USD",
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
                    "value_json": {
                        "fact_nature": "actual",
                        "mapping_id": "is.net_income.fy",
                        "source_mapping_version": service.mapping_spec.source_mapping_version,
                        "definition_basis": "adjusted",
                        "fiscal_year": 2024,
                        "period_duration_kind": "fiscal_year",
                        "dimensions_identity": "empty",
                    },
                    "unit": "USD",
                    "currency": "USD",
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
    assert {fact.stock_id for fact in facts if fact.is_current} == {doc.stock_id}
    assert any(fact.stock_id == old_stock.id and not fact.is_current for fact in facts)
    assert extractions
    assert any(extraction.raw_value_text == "9" for extraction in extractions)
    assert any(extraction.raw_value_text != "9" for extraction in extractions)


def test_reparse_appends_mapping_revision_and_preserves_manual_lineage(db_session):
    user = User(email="reparse_mapping_history@example.com")
    stock = Stock(ticker="RMAP", exchange="NYSE", company_name="Reparse Mapping")
    db_session.add_all([user, stock])
    db_session.flush()
    text = (
        "REPARSE MAPPING\nNYSE-RMAP\nRECENT PRICE 10\n"
        "VALUE LINE\nAnalystX January 2, 2026\n"
    )
    doc = PdfDocument(
        user_id=user.id,
        file_name="rmap.pdf",
        source="upload",
        file_storage_key="/tmp/rmap.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        identity_needs_review=False,
        raw_text=text,
        report_date=date(2026, 1, 2),
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=doc.id,
            page_number=1,
            page_text=text,
            text_extraction_method="native_text",
        )
    )
    old_extraction = MetricExtraction(
        user_id=user.id,
        document_id=doc.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="9",
        original_text_snippet="RECENT PRICE 9",
        parsed_value_json={"raw": "9"},
        parser_version="v1",
    )
    db_session.add(old_extraction)
    db_session.flush()
    old_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_numeric=9,
        value_json={
            "mapping_id": "mkt.price.as_of",
            "source_mapping_version": "value-line-resolved-v1:old",
            "definition_basis": "adjusted",
            "dimensions_identity": "empty",
            "fact_nature": "snapshot",
        },
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 1, 2),
        source_type="parsed",
        source_document_id=doc.id,
        is_current=True,
    )
    db_session.add(old_fact)
    db_session.flush()
    correction = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_numeric=9.5,
        value_json={
            "fact_nature": "manual",
            "corrects_fact_id": old_fact.id,
            "definition_basis": "adjusted",
            "dimensions_identity": "empty",
        },
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 1, 2),
        source_type="manual",
        is_current=True,
    )
    db_session.add(correction)
    db_session.commit()

    service = IngestionService(db_session)
    generated = {
        "metric_key": "mkt.price",
        "value_numeric": 10.0,
        "value_text": None,
        "value_json": {
            "mapping_id": "mkt.price.as_of",
            "source_mapping_version": service.mapping_spec.source_mapping_version,
            "definition_basis": "adjusted",
            "dimensions_identity": "empty",
            "fact_nature": "snapshot",
        },
        "unit": "USD",
        "currency": "USD",
        "period_type": "AS_OF",
        "period_end_date": date(2026, 1, 2),
    }
    with patch.object(
        service.mapping_spec,
        "generate_facts",
        return_value=([generated], set(), set()),
    ):
        service.reparse_existing_document(
            user_id=user.id,
            document_id=doc.id,
            reextract_pdf=False,
        )

    db_session.expire_all()
    revisions = (
        db_session.query(MetricFact)
        .filter_by(
            source_document_id=doc.id,
            source_type="parsed",
            metric_key="mkt.price",
        )
        .order_by(MetricFact.id)
        .all()
    )
    assert len(revisions) == 2
    assert revisions[0].id == old_fact.id
    assert revisions[0].is_current is False
    assert revisions[0].value_json["source_mapping_version"].endswith(":old")
    assert revisions[1].is_current is True
    assert (
        revisions[1].value_json["source_mapping_version"]
        == service.mapping_spec.source_mapping_version
    )
    assert revisions[1].value_line_parse_run_id is not None
    assert db_session.get(MetricFact, correction.id).value_json["corrects_fact_id"] == old_fact.id
    assert db_session.get(MetricExtraction, old_extraction.id) is not None
    new_extractions = (
        db_session.query(MetricExtraction)
        .filter(
            MetricExtraction.document_id == doc.id,
            MetricExtraction.id != old_extraction.id,
        )
        .all()
    )
    assert new_extractions
    assert {
        extraction.value_line_parse_run_id for extraction in new_extractions
    } == {revisions[1].value_line_parse_run_id}
    parse_run = db_session.get(
        ValueLineParseRun, revisions[1].value_line_parse_run_id
    )
    assert parse_run.status == "succeeded"
    assert parse_run.completed_at is not None
    assert parse_run.source_mapping_version == service.mapping_spec.source_mapping_version


def test_failed_reparse_atomically_preserves_prior_current_revision(db_session):
    user = User(email="reparse-atomic-failure@example.com")
    stock = Stock(ticker="RFAIL", exchange="NYSE", company_name="Reparse Failure")
    db_session.add_all([user, stock])
    db_session.flush()
    text = (
        "REPARSE FAILURE\nNYSE-RFAIL\nRECENT PRICE 10\n"
        "VALUE LINE\nAnalystX January 2, 2026\n"
    )
    doc = PdfDocument(
        user_id=user.id,
        file_name="rfail.pdf",
        source="upload",
        file_storage_key="/tmp/rfail.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        identity_needs_review=False,
        raw_text=text,
        report_date=date(2026, 1, 2),
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=doc.id,
            page_number=1,
            page_text=text,
            text_extraction_method="native_text",
        )
    )
    prior = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_numeric=9,
        value_json={
            "mapping_id": "mkt.price.as_of",
            "source_mapping_version": "value-line-resolved-v1:prior",
            "definition_basis": "adjusted",
            "dimensions_identity": "empty",
        },
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 1, 2),
        source_type="parsed",
        source_document_id=doc.id,
        is_current=True,
    )
    db_session.add(prior)
    db_session.commit()

    generated = {
        "metric_key": "mkt.price",
        "value_numeric": 10.0,
        "value_text": None,
        "value_json": {
            "mapping_id": "mkt.price.as_of",
            "source_mapping_version": "value-line-resolved-v2:new",
            "definition_basis": "adjusted",
            "dimensions_identity": "empty",
        },
        "unit": "USD",
        "currency": "USD",
        "period_type": "AS_OF",
        "period_end_date": date(2026, 1, 2),
    }
    service = IngestionService(db_session)
    with patch.object(
        service.mapping_spec,
        "generate_facts",
        return_value=([generated], set(), set()),
    ), patch.object(
        service,
        "_run_calculated_metrics",
        side_effect=RuntimeError("post-write calculation failure"),
    ), pytest.raises(RuntimeError, match="post-write calculation failure"):
        service.reparse_existing_document(
            user_id=user.id,
            document_id=doc.id,
            reextract_pdf=False,
        )

    db_session.expire_all()
    revisions = db_session.query(MetricFact).filter_by(
        source_document_id=doc.id,
        source_type="parsed",
        metric_key="mkt.price",
    ).all()
    assert [fact.id for fact in revisions] == [prior.id]
    assert revisions[0].is_current is True
    assert db_session.query(ValueLineParseRun).filter_by(document_id=doc.id).count() == 0
    assert db_session.get(PdfDocument, doc.id).parse_status == "parsed"
