from datetime import date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument, DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from financial_truth_fixtures import authorize_parsed_facts


def test_documents_list_returns_companies_and_page_count(client, db_session, user_factory, auth_headers):
    user = user_factory("documents_list@example.com")
    headers = auth_headers(user)

    stock_a = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    stock_b = Stock(ticker="MSFT", exchange="NDQ", company_name="Microsoft")
    db_session.add_all([stock_a, stock_b])
    db_session.commit()

    doc_one = PdfDocument(
        user_id=user.id,
        file_name="aos.pdf",
        source="upload",
        file_storage_key="/tmp/aos.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        upload_time=datetime.utcnow(),
        stock_id=stock_a.id,
    )
    doc_two = PdfDocument(
        user_id=user.id,
        file_name="multi.pdf",
        source="upload",
        file_storage_key="/tmp/multi.pdf",
        parse_status="parsed_partial",
        upload_time=datetime.utcnow(),
        stock_id=None,
    )
    db_session.add_all([doc_one, doc_two])
    db_session.commit()

    db_session.add_all(
        [
            DocumentPage(
                document_id=doc_one.id,
                page_number=1,
                page_text="a",
                text_extraction_method="native_text",
            ),
            DocumentPage(
                document_id=doc_two.id,
                page_number=1,
                page_text="b",
                text_extraction_method="native_text",
            ),
            DocumentPage(
                document_id=doc_two.id,
                page_number=2,
                page_text="c",
                text_extraction_method="native_text",
            ),
        ]
    )

    e1 = MetricExtraction(
        user_id=user.id,
        document_id=doc_one.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="1",
        original_text_snippet="recent_price",
        confidence_score=0.9,
    )
    e2 = MetricExtraction(
        user_id=user.id,
        document_id=doc_two.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="2",
        original_text_snippet="recent_price",
        confidence_score=0.9,
    )
    e3 = MetricExtraction(
        user_id=user.id,
        document_id=doc_two.id,
        page_number=2,
        field_key="recent_price",
        raw_value_text="3",
        original_text_snippet="recent_price",
        confidence_score=0.9,
    )
    db_session.add_all([e1, e2, e3])
    db_session.flush()

    first_fact = MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key="mkt.price",
                value_json={"raw": "1"},
                value_numeric=1.0,
                unit="USD",
                source_type="parsed",
                is_current=True,
            )
    multi_a_fact = MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key="mkt.price",
                value_json={"raw": "2"},
                value_numeric=2.0,
                unit="USD",
                source_type="parsed",
                is_current=True,
            )
    multi_b_fact = MetricFact(
                user_id=user.id,
                stock_id=stock_b.id,
                metric_key="mkt.price",
                value_json={"raw": "3"},
                value_numeric=3.0,
                unit="USD",
                source_type="parsed",
                is_current=True,
            )
    authorize_parsed_facts(db_session, document=doc_one, facts=[first_fact])
    authorize_parsed_facts(
        db_session, document=doc_two, facts=[multi_a_fact, multi_b_fact]
    )
    db_session.commit()

    resp = client.get("/api/v1/documents", headers=headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    doc_map = {doc["id"]: doc for doc in payload}
    assert doc_one.id in doc_map
    assert doc_two.id in doc_map

    one = doc_map[doc_one.id]
    assert one["page_count"] == 1
    assert one["parsed_page_count"] == 1
    assert one["report_date"] == "2026-01-02"
    assert one["companies"] == [{"ticker": "AOS", "company_name": "SMITH (A.O.)"}]
    assert one["is_active_report"] is True
    assert one["active_for_tickers"] == ["AOS"]

    two = doc_map[doc_two.id]
    assert two["page_count"] == 2
    assert two["parsed_page_count"] == 2
    assert two["report_date"] is None
    assert {c["ticker"] for c in two["companies"]} == {"AOS", "MSFT"}
    assert two["is_active_report"] is True
    assert two["active_for_tickers"] == ["MSFT"]


def test_documents_list_hides_company_projection_without_exact_authority(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_list_quarantine@example.com")
    headers = auth_headers(user)
    bound_stock = Stock(
        ticker="BOUND",
        exchange="NYSE",
        company_name="Bound Company",
    )
    stale_stock = Stock(
        ticker="STALE",
        exchange="NYSE",
        company_name="Stale Projection",
    )
    db_session.add_all([bound_stock, stale_stock])
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        stock_id=bound_stock.id,
        file_name="bound-company.pdf",
        source="upload",
        file_storage_key="/tmp/bound-company.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        upload_time=datetime.utcnow(),
    )
    db_session.add(document)
    db_session.flush()

    # A retained pre-rollout projection can remain for audit after migration
    # 4900, but without exact extraction authority it must not project a
    # company onto the user-facing document list.
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stale_stock.id,
            metric_key="is.revenue",
            value_json={"fact_nature": "actual"},
            value_numeric=999,
            unit="USD",
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            source_type="parsed",
            source_document_id=document.id,
            is_current=False,
        )
    )
    db_session.flush()

    response = client.get("/api/v1/documents", headers=headers)

    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == document.id)
    assert item["companies"] == [
        {"ticker": "BOUND", "company_name": "Bound Company"}
    ]
    assert item["company_count"] == 1


def test_documents_list_orders_by_ticker_then_report_date(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_order@example.com")
    headers = auth_headers(user)

    stock_a = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    stock_f = Stock(ticker="FICO", exchange="NYSE", company_name="Fair Isaac")
    db_session.add_all([stock_a, stock_f])
    db_session.commit()

    fico_newer = PdfDocument(
        user_id=user.id,
        file_name="fico-newer.pdf",
        source="upload",
        file_storage_key="/tmp/fico-newer.pdf",
        parse_status="parsed",
        report_date=date(2026, 4, 30),
        upload_time=datetime(2026, 5, 3),
        stock_id=stock_f.id,
    )
    aos = PdfDocument(
        user_id=user.id,
        file_name="aos.pdf",
        source="upload",
        file_storage_key="/tmp/aos.pdf",
        parse_status="parsed",
        report_date=date(2026, 2, 28),
        upload_time=datetime(2026, 5, 2),
        stock_id=stock_a.id,
    )
    fico_older = PdfDocument(
        user_id=user.id,
        file_name="fico-older.pdf",
        source="upload",
        file_storage_key="/tmp/fico-older.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 31),
        upload_time=datetime(2026, 5, 1),
        stock_id=stock_f.id,
    )
    db_session.add_all([fico_newer, aos, fico_older])
    db_session.commit()

    resp = client.get("/api/v1/documents", headers=headers)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert [doc["id"] for doc in payload] == [aos.id, fico_older.id, fico_newer.id]


def test_documents_list_marks_latest_report_as_active_per_company(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_active@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="FICO", exchange="NYSE", company_name="Fair Isaac")
    db_session.add(stock)
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q1.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q1.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 9),
        upload_time=datetime.utcnow(),
    )
    new_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q2.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q2.pdf",
        parse_status="parsed",
        report_date=date(2026, 4, 9),
        upload_time=datetime.utcnow(),
    )
    db_session.add_all([old_doc, new_doc])
    db_session.commit()

    old_extraction = MetricExtraction(
        user_id=user.id,
        document_id=old_doc.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="100",
        original_text_snippet="recent_price",
        confidence_score=0.9,
    )
    new_extraction = MetricExtraction(
        user_id=user.id,
        document_id=new_doc.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="110",
        original_text_snippet="recent_price",
        confidence_score=0.9,
    )
    db_session.add_all([old_extraction, new_extraction])
    db_session.flush()

    old_fact = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "100"},
                value_numeric=100.0,
                unit="USD",
                source_type="parsed",
                is_current=False,
            )
    new_fact = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "110"},
                value_numeric=110.0,
                unit="USD",
                source_type="parsed",
                is_current=True,
            )
    authorize_parsed_facts(db_session, document=old_doc, facts=[old_fact])
    authorize_parsed_facts(db_session, document=new_doc, facts=[new_fact])
    db_session.commit()

    resp = client.get("/api/v1/documents", headers=headers)
    assert resp.status_code == 200, resp.text

    doc_map = {doc["id"]: doc for doc in resp.json()}
    assert doc_map[old_doc.id]["is_active_report"] is False
    assert doc_map[old_doc.id]["active_for_tickers"] == []
    assert doc_map[new_doc.id]["is_active_report"] is True
    assert doc_map[new_doc.id]["active_for_tickers"] == ["FICO"]


def test_documents_raw_text_endpoint(client, db_session, user_factory, auth_headers):
    user = user_factory("documents_raw@example.com")
    headers = auth_headers(user)

    doc = PdfDocument(
        user_id=user.id,
        file_name="raw.pdf",
        source="upload",
        file_storage_key="/tmp/raw.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        raw_text="hello world",
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/raw_text", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["raw_text"] == "hello world"


def test_document_download_endpoint_streams_owned_pdf(
    client, db_session, user_factory, auth_headers, tmp_path
):
    user = user_factory("documents_download@example.com")
    headers = auth_headers(user)
    pdf_path = tmp_path / "stored-report.pdf"
    pdf_bytes = b"%PDF-1.4\nstored report\n%%EOF\n"
    pdf_path.write_bytes(pdf_bytes)

    doc = PdfDocument(
        user_id=user.id,
        file_name="AOS report.pdf",
        source="upload",
        file_storage_key=str(pdf_path),
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/download", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.content == pdf_bytes
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "attachment" in resp.headers["content-disposition"]
    assert "AOS%20report.pdf" in resp.headers["content-disposition"]


def test_document_download_endpoint_requires_document_ownership(
    client, db_session, user_factory, auth_headers, tmp_path
):
    owner = user_factory("documents_download_owner@example.com")
    intruder = user_factory("documents_download_intruder@example.com")
    pdf_path = tmp_path / "owned.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nowned\n%%EOF\n")

    doc = PdfDocument(
        user_id=owner.id,
        file_name="owned.pdf",
        source="upload",
        file_storage_key=str(pdf_path),
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/download", headers=auth_headers(intruder))

    assert resp.status_code == 404


def test_document_download_endpoint_reports_missing_storage_file(
    client, db_session, user_factory, auth_headers, tmp_path
):
    user = user_factory("documents_download_missing@example.com")
    headers = auth_headers(user)

    doc = PdfDocument(
        user_id=user.id,
        file_name="missing.pdf",
        source="upload",
        file_storage_key=str(tmp_path / "missing.pdf"),
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/download", headers=headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Stored document file not found"


def test_delete_document_archives_lineage_and_reconciles_current(
    client,
    db_session,
    user_factory,
    auth_headers,
    monkeypatch,
    tmp_path,
):
    user = user_factory("documents_delete@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="DEL", exchange="NYSE", company_name="Delete Co")
    db_session.add(stock)
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="delete-old.pdf",
        source="upload",
        file_storage_key="/tmp/delete-old.pdf",
        parse_status="parsed",
        report_date=date(2025, 12, 31),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    target_path = tmp_path / "delete-target.pdf"
    target_path.write_bytes(b"%PDF-1.4\nretained evidence\n%%EOF\n")
    target_doc = PdfDocument(
        user_id=user.id,
        file_name="delete-target.pdf",
        source="upload",
        file_storage_key=str(target_path),
        parse_status="parsed",
        report_date=date(2026, 1, 31),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add_all([old_doc, target_doc])
    db_session.commit()

    page = DocumentPage(
        document_id=target_doc.id,
        page_number=1,
        page_text="target",
        text_extraction_method="native_text",
    )
    extraction = MetricExtraction(
        user_id=user.id,
        document_id=target_doc.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="120",
        original_text_snippet="Recent price 120",
        confidence_score=0.9,
    )
    db_session.add_all([page, extraction])
    db_session.flush()

    old_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_json={"raw": "100"},
        value_numeric=100.0,
        unit="USD",
        period_type="AS_OF",
        as_of_date=date(2026, 1, 31),
        source_type="parsed",
        source_document_id=old_doc.id,
        is_current=False,
    )
    target_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_json={"raw": "120"},
        value_numeric=120.0,
        unit="USD",
        period_type="AS_OF",
        as_of_date=date(2026, 1, 31),
        source_type="parsed",
        source_ref_id=extraction.id,
        source_document_id=target_doc.id,
        is_current=True,
    )
    manual_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="val.pe",
        value_json={"raw": "20", "correction": True},
        value_numeric=20.0,
        period_type="AS_OF",
        as_of_date=date(2026, 1, 31),
        source_type="manual",
        source_document_id=target_doc.id,
        is_current=True,
    )
    stale_calculated_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        value_json={"score": 9},
        value_numeric=9.0,
        period_type="FY",
        period_end_date=date(2026, 12, 31),
        source_type="calculated",
        is_current=True,
    )
    authorize_parsed_facts(db_session, document=old_doc, facts=[old_fact])
    authorize_parsed_facts(db_session, document=target_doc, facts=[target_fact])
    db_session.add_all([manual_fact, stale_calculated_fact])
    db_session.commit()

    page_id = page.id
    extraction_id = extraction.id
    old_fact_id = old_fact.id
    target_fact_id = target_fact.id
    manual_fact_id = manual_fact.id
    stale_calculated_fact_id = stale_calculated_fact.id
    target_doc_id = target_doc.id
    calculator_calls: list[tuple[str, int, int]] = []

    def _record_ratio_call(self, *, user_id: int, stock_id: int) -> None:
        calculator_calls.append(("ratios", user_id, stock_id))

    def _record_fscore_call(self, *, user_id: int, stock_id: int) -> None:
        calculator_calls.append(("fscore", user_id, stock_id))

    monkeypatch.setattr(
        "app.services.document_dedupe_service.ValueLineRatioCalculator.calculate_for_stock",
        _record_ratio_call,
    )
    monkeypatch.setattr(
        "app.services.document_dedupe_service.PiotroskiFScoreCalculator.calculate_for_stock",
        _record_fscore_call,
    )

    resp = client.delete(f"/api/v1/documents/{target_doc_id}", headers=headers)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["archived_document_id"] == target_doc_id
    assert payload["lifecycle_state"] == "archived"
    archived = db_session.get(PdfDocument, target_doc_id)
    assert archived is not None
    assert archived.lifecycle_state == "archived"
    assert archived.retired_at is not None
    assert db_session.get(DocumentPage, page_id) is not None
    assert db_session.get(MetricExtraction, extraction_id) is not None
    archived_parsed_fact = db_session.get(MetricFact, target_fact_id)
    assert archived_parsed_fact is not None
    assert archived_parsed_fact.is_current is False
    assert db_session.get(MetricFact, manual_fact_id) is not None
    retained_calculated_fact = db_session.get(
        MetricFact, stale_calculated_fact_id
    )
    assert retained_calculated_fact is not None

    refreshed_old_fact = db_session.get(MetricFact, old_fact_id)
    assert refreshed_old_fact is not None
    assert refreshed_old_fact.is_current is True
    assert calculator_calls == [
        ("ratios", user.id, stock.id),
        ("fscore", user.id, stock.id),
    ]

    listed = client.get("/api/v1/documents", headers=headers)
    assert listed.status_code == 200
    assert target_doc_id not in {row["id"] for row in listed.json()}

    retained = client.get(
        f"/api/v1/documents/{target_doc_id}/download", headers=headers
    )
    assert retained.status_code == 200
    assert retained.content == target_path.read_bytes()


def test_delete_document_requires_owner(client, db_session, user_factory, auth_headers):
    owner = user_factory("documents_delete_owner@example.com")
    intruder = user_factory("documents_delete_intruder@example.com")

    doc = PdfDocument(
        user_id=owner.id,
        file_name="owned-delete.pdf",
        source="upload",
        file_storage_key="/tmp/owned-delete.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.delete(f"/api/v1/documents/{doc.id}", headers=auth_headers(intruder))

    assert resp.status_code == 404
    assert db_session.get(PdfDocument, doc.id) is not None


def test_database_rejects_document_unarchive_and_physical_delete(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory("documents_lifecycle_guard@example.com")
    doc = PdfDocument(
        user_id=owner.id,
        file_name="retained.pdf",
        source="upload",
        file_storage_key="/tmp/retained.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(doc)
    active_doc = PdfDocument(
        user_id=owner.id,
        file_name="active-retained.pdf",
        source="upload",
        file_storage_key="/tmp/active-retained.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(active_doc)
    db_session.commit()
    document_id = doc.id
    active_document_id = active_doc.id

    with pytest.raises(DBAPIError, match="requires audited account erasure"):
        db_session.execute(
            sa.text(
                "UPDATE pdf_documents SET lifecycle_state = 'erased', "
                "retired_at = now(), retirement_reason = 'account_erasure', "
                "retired_by_user_id = :user_id WHERE id = :document_id"
            ),
            {"user_id": owner.id, "document_id": active_document_id},
        )
    db_session.rollback()

    with pytest.raises(
        DBAPIError,
        match="completed account erasure forbids user-owned mutations",
    ):
        db_session.execute(
            sa.text(
                "INSERT INTO account_erasure_events "
                "(user_id, content_hash, summary_json) "
                "VALUES (:user_id, :content_hash, '{}'::jsonb)"
            ),
            {"user_id": owner.id, "content_hash": "a" * 64},
        )
        db_session.execute(
            sa.text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
        )
        db_session.execute(
            sa.text(
                "UPDATE pdf_documents SET lifecycle_state = 'erased', "
                "retired_at = now(), retirement_reason = 'account_erasure', "
                "retired_by_user_id = :user_id WHERE id = :document_id"
            ),
            {"user_id": owner.id, "document_id": active_document_id},
        )
        db_session.execute(
            sa.text("SET CONSTRAINTS trg_pdf_documents_erasure_audit IMMEDIATE")
        )
    db_session.rollback()

    response = client.delete(
        f"/api/v1/documents/{document_id}", headers=auth_headers(owner)
    )
    assert response.status_code == 200

    with pytest.raises(DBAPIError, match="cannot return to active"):
        db_session.execute(
            sa.text(
                "UPDATE pdf_documents SET lifecycle_state = 'active', "
                "retired_at = NULL, retired_by_user_id = NULL, "
                "retirement_reason = NULL WHERE id = :document_id"
            ),
            {"document_id": document_id},
        )
    db_session.rollback()

    with pytest.raises(DBAPIError, match="use lifecycle retirement"):
        db_session.execute(
            sa.text("DELETE FROM pdf_documents WHERE id = :document_id"),
            {"document_id": document_id},
        )
    db_session.rollback()


def test_document_evidence_endpoint_returns_evidence_only_fields(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_evidence@example.com")
    headers = auth_headers(user)

    doc = PdfDocument(
        user_id=user.id,
        file_name="fico.pdf",
        source="upload",
        file_storage_key="/tmp/fico.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        report_date=date(2026, 1, 9),
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add_all(
        [
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="business_description",
                raw_value_text="Provides analytics software.",
                original_text_snippet="Business: Provides analytics software.",
                confidence_score=0.9,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="analyst_commentary",
                raw_value_text="Margins should expand through FY2027.",
                original_text_snippet="Commentary: Margins should expand through FY2027.",
                confidence_score=0.9,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="timeliness",
                raw_value_text="2",
                original_text_snippet="Timeliness 2 Raised 12/19/25",
                parsed_value_json={"value": 2, "notes": "Raised 12/19/25"},
                confidence_score=0.9,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="safety",
                raw_value_text="1",
                original_text_snippet="Safety 1",
                parsed_value_json={"value": 1},
                confidence_score=0.9,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="technical",
                raw_value_text="3",
                original_text_snippet="Technical 3 Lowered 11/01/25",
                parsed_value_json={"value": 3, "notes": "Lowered 11/01/25"},
                confidence_score=0.9,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="business_description",
                raw_value_text="Older stale description.",
                original_text_snippet="Older Business: Older stale description.",
                confidence_score=0.6,
                parser_version="v0",
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/evidence", headers=headers)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["document_id"] == doc.id
    evidence_map = {item["mapping_id"]: item for item in payload["evidence"]}

    business = evidence_map["company.business_description.as_of"]
    assert business["metric_key"] == "company.business_description"
    assert business["fact_nature"] == "opinion"
    assert business["storage_role"] == "evidence_only"
    assert business["source"] == "metric_extractions"
    assert business["field_key"] == "business_description"
    assert business["period_type"] == "AS_OF"
    assert business["period_end_date"] == "2026-01-09"
    assert business["value_text"] == "Provides analytics software."
    assert business["value_json"] is None
    assert business["original_text_snippet"] == "Business: Provides analytics software."

    commentary = evidence_map["analyst.commentary.as_of"]
    assert commentary["metric_key"] == "analyst.commentary"
    assert commentary["value_text"] == "Margins should expand through FY2027."

    timeliness_event = evidence_map["rating.timeliness.event"]
    assert timeliness_event["metric_key"] == "rating.timeliness_change"
    assert timeliness_event["period_type"] == "EVENT"
    assert timeliness_event["period_end_date"] == "2025-12-19"
    assert timeliness_event["value_text"] == "raised"
    assert timeliness_event["value_json"] == {
        "type": "raised",
        "date": "2025-12-19",
        "raw": "Raised 12/19/25",
    }

    technical_event = evidence_map["rating.technical.event"]
    assert technical_event["metric_key"] == "rating.technical_change"
    assert technical_event["period_end_date"] == "2025-11-01"
    assert technical_event["value_text"] == "lowered"

    assert "rating.safety.event" not in evidence_map


def test_document_evidence_endpoint_requires_document_ownership(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory("documents_evidence_owner@example.com")
    intruder = user_factory("documents_evidence_intruder@example.com")

    doc = PdfDocument(
        user_id=owner.id,
        file_name="owned.pdf",
        source="upload",
        file_storage_key="/tmp/owned.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/evidence", headers=auth_headers(intruder))
    assert resp.status_code == 404


def test_document_review_endpoint_returns_grouped_facts_with_lineage(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="aos.pdf",
        source="upload",
        file_storage_key="/tmp/aos.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    extraction = MetricExtraction(
        user_id=user.id,
        document_id=doc.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="$68.11",
        original_text_snippet="Recent price $68.11",
        confidence_score=0.92,
        parser_version="v1",
        as_of_date=date(2026, 1, 2),
    )
    db_session.add(extraction)
    db_session.flush()

    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_json={"raw": "$68.11", "fact_nature": "snapshot"},
        value_numeric=68.11,
        unit="USD",
        period_type="AS_OF",
        as_of_date=date(2026, 1, 2),
        source_type="parsed",
        source_ref_id=extraction.id,
        source_document_id=doc.id,
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["document"] == {
        "id": doc.id,
        "file_name": "aos.pdf",
        "ticker": "AOS",
        "exchange": "NYSE",
        "company_name": "SMITH (A.O.)",
        "report_date": "2026-01-02",
    }
    group_map = {group["key"]: group for group in payload["groups"]}
    assert "identity_header" in group_map

    item = group_map["identity_header"]["items"][0]
    assert item["metric_key"] == "mkt.price"
    assert item["label"] == "Price"
    assert item["fact_id"] == fact.id
    assert item["display_value"] == "$68.11"
    assert item["value_numeric"] == 68.11
    assert item["unit"] == "USD"
    assert item["period_type"] == "AS_OF"
    assert item["as_of_date"] == "2026-01-02"
    assert item["source_type"] == "parsed"
    assert item["is_current"] is True
    assert item["editable"] is True
    assert item["lineage_available"] is True
    assert item["lineage"] == {
        "extraction_id": extraction.id,
        "document_id": doc.id,
        "page_number": 1,
        "original_text_snippet": "Recent price $68.11",
    }


def test_document_review_endpoint_returns_header_summary_fields(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_summary@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="aos-summary.pdf",
        source="upload",
        file_storage_key="/tmp/aos-summary.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    extraction = MetricExtraction(
        user_id=user.id,
        document_id=doc.id,
        page_number=1,
        field_key="header_summary",
        raw_value_text="summary fixture",
        original_text_snippet="summary fixture",
        confidence_score=1.0,
        parser_version="v1",
        parse_generation=1,
    )
    db_session.add(extraction)
    db_session.flush()
    facts = [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "$68.11", "fact_nature": "snapshot"},
                value_numeric=68.11,
                unit="USD",
                period_type="AS_OF",
                as_of_date=date(2026, 1, 2),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.pe",
                value_json={"raw": "18.5", "fact_nature": "snapshot"},
                value_numeric=18.5,
                unit="ratio",
                period_type="AS_OF",
                as_of_date=date(2026, 1, 2),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.pe_trailing",
                value_json={"raw": "17.9", "fact_nature": "snapshot"},
                value_numeric=17.9,
                unit="ratio",
                period_type="AS_OF",
                as_of_date=date(2026, 1, 2),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.pe_median",
                value_json={"raw": "22.0", "fact_nature": "snapshot"},
                value_numeric=22.0,
                unit="ratio",
                period_type="AS_OF",
                as_of_date=date(2026, 1, 2),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.relative_pe",
                value_json={"raw": "0.93", "fact_nature": "snapshot"},
                value_numeric=0.93,
                unit="ratio",
                period_type="AS_OF",
                as_of_date=date(2026, 1, 2),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.dividend_yield",
                value_json={"raw": "2.0%", "fact_nature": "snapshot"},
                value_numeric=0.02,
                unit="percent",
                period_type="AS_OF",
                as_of_date=date(2026, 1, 2),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
        ]
    for fact in facts:
        fact.source_ref_id = extraction.id
        fact.parse_generation = 1
    db_session.add_all(facts)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["document"]["exchange"] == "NYSE"
    assert payload["summary"] == {
        "recent_price": {
            "metric_key": "mkt.price",
            "label": "Recent Price",
            "display_value": "$68.11",
            "value_numeric": 68.11,
            "unit": "USD",
        },
        "pe_ratio": {
            "metric_key": "val.pe",
            "label": "P/E Ratio",
            "display_value": "18.5",
            "value_numeric": 18.5,
            "unit": "ratio",
        },
        "pe_trailing": {
            "metric_key": "val.pe_trailing",
            "label": "P/E Trailing",
            "display_value": "17.9",
            "value_numeric": 17.9,
            "unit": "ratio",
        },
        "pe_median": {
            "metric_key": "val.pe_median",
            "label": "P/E Median",
            "display_value": "22.0",
            "value_numeric": 22.0,
            "unit": "ratio",
        },
        "relative_pe_ratio": {
            "metric_key": "val.relative_pe",
            "label": "Relative P/E Ratio",
            "display_value": "0.93",
            "value_numeric": 0.93,
            "unit": "ratio",
        },
        "dividend_yield": {
            "metric_key": "val.dividend_yield",
            "label": "Div'd Yld",
            "display_value": "2.0%",
            "value_numeric": 0.02,
            "unit": "percent",
        },
    }


def test_document_review_endpoint_returns_parser_capital_structure_block(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_capital_structure@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="FNV", exchange="NYSE", company_name="FRANCO-NEVADA")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="fnv-capital.pdf",
        source="upload",
        file_storage_key="/tmp/fnv-capital.pdf",
        parse_status="parsed",
        report_date=date(2025, 12, 26),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add_all(
        [
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="capital_structure_as_of",
                raw_value_text="2025-09-30",
                original_text_snippet="CAPITAL STRUCTURE as of 9/30/25",
                confidence_score=0.95,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="total_debt",
                raw_value_text="None",
                original_text_snippet="Total Debt None",
                confidence_score=0.95,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="pension_plan",
                raw_value_text="No Defined Benefit Pension Plan",
                parsed_value_json={
                    "defined_benefit": False,
                    "notes": "No Defined Benefit Pension Plan",
                },
                original_text_snippet="No Defined Benefit Pension Plan",
                confidence_score=0.95,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="common_stock_shares_outstanding",
                raw_value_text="192,800,000",
                parsed_value_json={"as_of": "2025-09-30"},
                original_text_snippet="Common Stock 192,800,000 shares",
                confidence_score=0.95,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="market_cap",
                raw_value_text="$40.9 billion",
                parsed_value_json={"notes": "Large Cap"},
                original_text_snippet="Market Cap: $40.9 billion (Large Cap)",
                confidence_score=0.95,
                parser_version="v1",
            ),
        ]
    )
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "192,800,000", "fact_nature": "snapshot"},
                value_numeric=192_800_000.0,
                unit="shares",
                period_type="AS_OF",
                as_of_date=date(2025, 9, 30),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.market_cap",
                value_json={"raw": "$40.9 billion", "fact_nature": "snapshot"},
                value_numeric=40_900_000_000.0,
                unit="USD",
                period_type="AS_OF",
                as_of_date=date(2025, 9, 30),
                source_type="parsed",
                source_document_id=doc.id,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    assert resp.json()["capital_structure"] == {
        "as_of": "2025-09-30",
        "total_debt": {"display": "None", "normalized": None, "unit": "USD"},
        "lt_interest_percent_of_capital": None,
        "leases_uncapitalized": None,
        "pension_plan": {
            "defined_benefit": False,
            "notes": "No Defined Benefit Pension Plan",
        },
        "common_stock": {
            "shares_outstanding": {
                "display": "192,800,000",
                "normalized": 192800000.0,
                "unit": "shares",
            },
            "as_of": "2025-09-30",
        },
        "market_cap": {
            "display": "$40.9 billion",
            "normalized": 40900000000.0,
            "unit": "USD",
            "market_cap_category": "Large Cap",
        },
    }


def test_document_review_endpoint_returns_parser_current_position_block(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_current_position@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="aos-current-position.pdf",
        source="upload",
        file_storage_key="/tmp/aos-current-position.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add(
        MetricExtraction(
            user_id=user.id,
            document_id=doc.id,
            page_number=1,
            field_key="current_position_usd_millions",
            raw_value_text=None,
            parsed_value_json={
                "years": ["2023", "2024", "2025-09-30"],
                "cash_assets": [363.4, 276.1, 172.8],
                "receivables": [596.0, 541.4, 589.0],
                "inventory_lifo": [497.4, 532.1, 507.3],
                "other_current_assets": [43.5, 43.3, 47.0],
                "current_assets_total": [1500.3, 1392.9, 1316.1],
                "accounts_payable": [600.4, 588.7, 521.4],
                "debt_due": [10.0, 10.0, 19.0],
                "other_current_liabilities": [334.9, 298.5, 312.1],
                "current_liabilities_total": [945.3, 897.2, 852.5],
            },
            original_text_snippet="CURRENTPOSITION ...",
            confidence_score=0.7,
            parser_version="v1",
        )
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    assert resp.json()["current_position"] == {
        "unit": "USD_millions",
        "periods": [
            {
                "label": "2023",
                "period_end_date": "2023-12-31",
                "assets": {
                    "cash_assets": 363.4,
                    "receivables": 596.0,
                    "inventory_lifo": 497.4,
                    "other_current_assets": 43.5,
                    "total_current_assets": 1500.3,
                },
                "liabilities": {
                    "accounts_payable": 600.4,
                    "debt_due": 10.0,
                    "other_current_liabilities": 334.9,
                    "total_current_liabilities": 945.3,
                },
            },
            {
                "label": "2024",
                "period_end_date": "2024-12-31",
                "assets": {
                    "cash_assets": 276.1,
                    "receivables": 541.4,
                    "inventory_lifo": 532.1,
                    "other_current_assets": 43.3,
                    "total_current_assets": 1392.9,
                },
                "liabilities": {
                    "accounts_payable": 588.7,
                    "debt_due": 10.0,
                    "other_current_liabilities": 298.5,
                    "total_current_liabilities": 897.2,
                },
            },
            {
                "label": "9/30/25",
                "period_end_date": "2025-09-30",
                "assets": {
                    "cash_assets": 172.8,
                    "receivables": 589.0,
                    "inventory_lifo": 507.3,
                    "other_current_assets": 47.0,
                    "total_current_assets": 1316.1,
                },
                "liabilities": {
                    "accounts_payable": 521.4,
                    "debt_due": 19.0,
                    "other_current_liabilities": 312.1,
                    "total_current_liabilities": 852.5,
                },
            },
        ],
    }


def test_document_review_endpoint_returns_parser_annual_financials_block(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_annual_financials@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="FNV", exchange="NYSE", company_name="FRANCO-NEVADA")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="fnv-annual-financials.pdf",
        source="upload",
        file_storage_key="/tmp/fnv-annual-financials.pdf",
        parse_status="parsed",
        report_date=date(2025, 12, 26),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    parsed_json = {
        "annual_financials_and_ratios_2015_2026_with_projection_2028_2030": {
            "years": [2024, 2025, 2026],
            "fiscal_year_end_month": 12,
            "projection_year_range": "2028-2030",
            "per_share": {
                "sales_per_share_usd": [5.79, 9.1, 12.0],
                "cash_flow_per_share_usd": [4.38, 6.75, 8.65],
                "earnings_per_share_usd": [3.21, 5.35, 7.15],
            },
            "valuation": {
                "avg_annual_pe_ratio": [38.8, 37.3, None],
                "relative_pe_ratio": [2.16, 2.13, None],
            },
            "income_statement_usd_millions": {
                "sales": [1113.6, 1750.0, 2300.0],
                "operating_margin_pct": [85.5, 88.0, 86.0],
                "net_profit": [618.1, 1025.0, 1375.0],
            },
            "balance_sheet_and_returns_usd_millions": {
                "working_capital": [1649.3, 500.0, 1150.0],
                "long_term_debt": [None, 457.3, None],
                "shareholders_equity": [5996.6, 7200.0, 7800.0],
            },
            "projection_2028_2030": {
                "sales_per_share_usd": 15.6,
                "avg_annual_pe_ratio": 35.0,
                "sales": 2960.0,
                "working_capital": 2200.0,
            },
        }
    }
    db_session.add(
        MetricExtraction(
            user_id=user.id,
            document_id=doc.id,
            page_number=1,
            field_key="tables_time_series",
            raw_value_text=None,
            parsed_value_json=parsed_json,
            original_text_snippet="TABLES_TIME_SERIES ...",
            confidence_score=0.8,
            parser_version="v1",
        )
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    annual = resp.json()["annual_financials"]
    assert annual["meta"]["historical_years"] == [2024, 2025, 2026]
    assert annual["meta"]["projection_year_range"] == "2028-2030"
    assert annual["per_unit_metrics"]["sales"]["2024"] == 5.79
    assert annual["per_unit_metrics"]["sales"]["projection_2028_2030"] == 15.6
    assert annual["valuation_metrics"]["avg_annual_pe_ratio"]["projection_2028_2030"] == 35.0
    assert annual["income_statement_usd_millions"]["sales"]["projection_2028_2030"] == 2960.0
    assert annual["balance_sheet_and_returns_usd_millions"]["long_term_debt"]["2024"] is None
    assert annual["balance_sheet_and_returns_usd_millions"]["long_term_debt"]["2025"] == 457.3


def test_document_review_endpoint_returns_total_return_block(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_total_return@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="AXS", exchange="NYSE", company_name="AXIS Capital")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="axs-total-return.pdf",
        source="upload",
        file_storage_key="/tmp/axs-total-return.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 9),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add(
        MetricExtraction(
            user_id=user.id,
            document_id=doc.id,
            page_number=1,
            field_key="price_semantics_and_returns",
            raw_value_text=None,
            parsed_value_json={
                "value_line_total_return_as_of": "2025-12-29",
                "total_return": {
                    "stock": {"1y": 0.244, "3y": 1.171, "5y": 1.502},
                    "index": {"1y": 0.036, "3y": 0.392, "5y": 0.685},
                },
            },
            original_text_snippet="% TOT. RETURN 12/29/25",
            confidence_score=0.8,
            parser_version="v1",
        )
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    total_return = resp.json()["total_return"]
    assert total_return["as_of_date"] == "2025-12-29"
    assert total_return["unit"] == "percent"
    assert total_return["fact_nature"] == "snapshot"
    assert total_return["series"] == [
        {"name": "this_stock", "window_years": 1, "value_pct": 24.4},
        {"name": "this_stock", "window_years": 3, "value_pct": 117.1},
        {"name": "this_stock", "window_years": 5, "value_pct": 150.2},
        {"name": "vl_arithmetic_index", "window_years": 1, "value_pct": 3.6},
        {"name": "vl_arithmetic_index", "window_years": 3, "value_pct": 39.2},
        {"name": "vl_arithmetic_index", "window_years": 5, "value_pct": 68.5},
    ]


def test_document_review_endpoint_returns_parser_annual_and_quarterly_blocks(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_time_series@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="FNV", exchange="NYSE", company_name="FRANCO-NEVADA")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="fnv-time-series.pdf",
        source="upload",
        file_storage_key="/tmp/fnv-time-series.pdf",
        parse_status="parsed",
        report_date=date(2025, 12, 26),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
        raw_text="Annual Rates Est'd 22-24 to'28-'30 Quarterly Sales Earnings Per Share",
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add_all(
        [
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="annual_rates_of_change",
                raw_value_text=None,
                parsed_value_json={
                    "sales": {
                        "past_10y": 0.09,
                        "past_5y": 0.135,
                        "est_to_2028_2030": 0.075,
                    },
                    "cash_flow_per_share": {
                        "past_10y": 0.145,
                        "past_5y": 0.155,
                        "est_to_2028_2030": 0.11,
                    },
                },
                original_text_snippet="Annual Rates ...",
                confidence_score=0.8,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="quarterly_sales_usd_millions",
                raw_value_text=None,
                parsed_value_json=[
                    {
                        "calendar_year": 2024,
                        "q1": 256.8,
                        "q2": 260.1,
                        "q3": 275.7,
                        "q4": 321.0,
                        "full_year": 1113.6,
                        "quarter_month_order": ["Mar", "Jun", "Sep", "Dec"],
                        "fiscal_year_end_month": 12,
                    },
                    {
                        "calendar_year": 2025,
                        "q1": 368.4,
                        "q2": 369.4,
                        "q3": 487.7,
                        "q4": 524.5,
                        "full_year": 1750.0,
                        "quarter_month_order": ["Mar", "Jun", "Sep", "Dec"],
                        "fiscal_year_end_month": 12,
                    },
                ],
                original_text_snippet="Quarterly Sales ...",
                confidence_score=0.8,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="earnings_per_share",
                raw_value_text=None,
                parsed_value_json=[
                    {
                        "calendar_year": 2024,
                        "q1": 0.76,
                        "q2": 0.75,
                        "q3": 0.80,
                        "q4": 0.95,
                        "full_year": 3.21,
                        "quarter_month_order": ["Mar", "Jun", "Sep", "Dec"],
                        "fiscal_year_end_month": 12,
                    }
                ],
                original_text_snippet="Earnings Per Share ...",
                confidence_score=0.8,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=doc.id,
                page_number=1,
                field_key="quarterly_dividends_paid_per_share",
                raw_value_text=None,
                parsed_value_json=[
                    {
                        "calendar_year": 2024,
                        "q1": 0.36,
                        "q2": 0.36,
                        "q3": 0.36,
                        "q4": 0.36,
                        "full_year": 1.44,
                        "quarter_month_order": ["Mar", "Jun", "Sep", "Dec"],
                        "fiscal_year_end_month": 12,
                    }
                ],
                original_text_snippet="Quarterly Dividends Paid ...",
                confidence_score=0.8,
                parser_version="v1",
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["annual_rates"]["metrics"][0]["metric_key"] == "sales"
    assert payload["annual_rates"]["metrics"][0]["past_10y_cagr_pct"] == 9
    assert payload["annual_rates"]["metrics"][0]["estimated_cagr_pct"] == {
        "from_period": "2022-2024",
        "to_period": "2028-2030",
        "value": 7.5,
    }
    # Q1-Q3 2025 are actual (period ended well before the Dec 26 report); Q4 (Dec 31) is estimated.
    assert payload["quarterly_sales"]["by_year"][1]["quarters"]["Q1"]["fact_nature"] == "actual"
    assert payload["quarterly_sales"]["by_year"][1]["quarters"]["Q4"]["fact_nature"] == "estimate"
    assert payload["quarterly_sales"]["by_year"][1]["full_year"]["value"] == 1750.0
    assert payload["earnings_per_share"]["by_year"][0]["full_year"]["value"] == 3.21
    assert payload["quarterly_dividends_paid"]["by_year"][0]["full_year"]["value"] == 1.44


def test_document_review_endpoint_returns_parser_quarterly_revenues_block(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_quarterly_revenues@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="ADBE", exchange="NDQ", company_name="ADOBE INC.")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="adobe-quarterly-revenues.pdf",
        source="upload",
        file_storage_key="/tmp/adobe-quarterly-revenues.pdf",
        parse_status="parsed",
        report_date=date(2025, 1, 31),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
        raw_text="Quarterly Revenues Earnings Per Share QuarterlyDividendsPaid 2021 2022 No Cash Dividends Being Paid 2025",
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add(
        MetricExtraction(
            user_id=user.id,
            document_id=doc.id,
            page_number=1,
            field_key="quarterly_revenues_usd_millions",
            raw_value_text=None,
            parsed_value_json=[
                {
                    "calendar_year": 2024,
                    "q1": 5182.0,
                    "q2": 5309.0,
                    "q3": 5408.0,
                    "q4": 5606.0,
                    "full_year": 21505.0,
                    "quarter_month_order": ["Feb", "May", "Aug", "Nov"],
                    "fiscal_year_end_month": 11,
                }
            ],
            original_text_snippet="Quarterly Revenues ...",
            confidence_score=0.8,
            parser_version="v1",
        )
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=headers)
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["quarterly_sales"] is None
    assert payload["quarterly_revenues"]["unit"] == "USD_millions"
    assert payload["quarterly_revenues"]["by_year"][0]["quarters"]["Q1"]["value"] == 5182.0
    assert payload["quarterly_revenues"]["by_year"][0]["quarters"]["Q4"]["period_end"] == "2024-11-30"
    assert payload["quarterly_dividends_paid"]["note"] == "No cash dividends being paid"
    assert payload["quarterly_dividends_paid"]["by_year"][-1]["calendar_year"] == 2025


def test_document_review_endpoint_requires_document_ownership(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory("documents_review_owner@example.com")
    intruder = user_factory("documents_review_intruder@example.com")

    doc = PdfDocument(
        user_id=owner.id,
        file_name="owned-review.pdf",
        source="upload",
        file_storage_key="/tmp/owned-review.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/review", headers=auth_headers(intruder))
    assert resp.status_code == 404


def test_document_review_correction_creates_manual_current_fact_without_mutating_extraction(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_correct@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="aos-correct.pdf",
        source="upload",
        file_storage_key="/tmp/aos-correct.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    extraction = MetricExtraction(
        user_id=user.id,
        document_id=doc.id,
        page_number=1,
        field_key="market_cap",
        raw_value_text="$9.5 billion",
        original_text_snippet="Market Cap: $9.5 billion",
        confidence_score=0.92,
        parser_version="v1",
    )
    db_session.add(extraction)
    db_session.flush()

    parsed_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.market_cap",
        value_json={"raw": "$9.5 billion", "fact_nature": "snapshot"},
        value_numeric=9_500_000_000.0,
        unit="USD",
        period_type="AS_OF",
        as_of_date=date(2026, 1, 2),
        source_type="parsed",
        source_ref_id=extraction.id,
        source_document_id=doc.id,
        is_current=True,
    )
    db_session.add(parsed_fact)
    db_session.commit()

    resp = client.post(
        f"/api/v1/documents/{doc.id}/review/facts/{parsed_fact.id}/corrections",
        headers=headers,
        json={"value": "$9.6 billion", "note": "Checked against report."},
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(extraction)
    db_session.refresh(parsed_fact)
    manual_fact = db_session.get(MetricFact, resp.json()["fact_id"])

    assert extraction.corrected_by_user is False
    assert extraction.corrected_at is None
    # Source-specific current slots preserve immutable parsed truth. Product
    # consumers resolve the current manual correction ahead of this parsed row.
    assert parsed_fact.is_current is True
    assert manual_fact is not None
    assert manual_fact.source_type == "manual"
    assert manual_fact.source_document_id == doc.id
    assert manual_fact.source_ref_id == extraction.id
    assert manual_fact.is_current is True
    assert manual_fact.value_numeric == 9_600_000_000.0
    assert manual_fact.unit == "USD"
    assert manual_fact.value_json["raw"] == "$9.6 billion"
    assert manual_fact.value_json["correction"] is True
    assert manual_fact.value_json["note"] == "Checked against report."


def test_document_review_correction_rejects_fact_from_another_document(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_wrong_doc@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="aos-target.pdf",
        source="upload",
        file_storage_key="/tmp/aos-target.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    other_doc = PdfDocument(
        user_id=user.id,
        file_name="aos-other.pdf",
        source="upload",
        file_storage_key="/tmp/aos-other.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add_all([doc, other_doc])
    db_session.commit()

    other_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_numeric=68.11,
        unit="USD",
        source_type="parsed",
        source_document_id=other_doc.id,
        is_current=True,
    )
    db_session.add(other_fact)
    db_session.commit()

    resp = client.post(
        f"/api/v1/documents/{doc.id}/review/facts/{other_fact.id}/corrections",
        headers=headers,
        json={"value": "70"},
    )
    assert resp.status_code == 404


def test_document_review_correction_rejects_unparseable_numeric_value_without_writes(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_review_bad_value@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    db_session.add(stock)
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="aos-bad-value.pdf",
        source="upload",
        file_storage_key="/tmp/aos-bad-value.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.commit()

    extraction = MetricExtraction(
        user_id=user.id,
        document_id=doc.id,
        page_number=1,
        field_key="recent_price",
        raw_value_text="68.11",
        original_text_snippet="RECENT PRICE 68.11",
        confidence_score=1.0,
        parser_version="v1",
        parse_generation=1,
    )
    db_session.add(extraction)
    db_session.flush()

    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_numeric=68.11,
        unit="USD",
        source_type="parsed",
        source_document_id=doc.id,
        source_ref_id=extraction.id,
        parse_generation=1,
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()

    before_count = db_session.scalar(sa.select(sa.func.count(MetricFact.id)))
    resp = client.post(
        f"/api/v1/documents/{doc.id}/review/facts/{fact.id}/corrections",
        headers=headers,
        json={"value": "not a number"},
    )

    db_session.refresh(fact)
    after_count = db_session.scalar(sa.select(sa.func.count(MetricFact.id)))
    assert resp.status_code == 400
    assert fact.is_current is True
    assert after_count == before_count


def test_extraction_correction_appends_source_linked_fact_without_mutating_extraction(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("extraction_correction_immutable@example.com")
    stock = Stock(ticker="IMMUT", exchange="NYSE", company_name="Immutable Co")
    db_session.add(stock)
    db_session.flush()
    doc = PdfDocument(
        user_id=user.id,
        file_name="immutable.pdf",
        source="upload",
        file_storage_key="/tmp/immutable.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.flush()
    parsed_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_json={"raw": "68.11", "fact_nature": "snapshot"},
        value_numeric=68.11,
        unit="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 1, 2),
        source_type="parsed",
        is_current=True,
    )
    authorize_parsed_facts(db_session, document=doc, facts=[parsed_fact])
    extraction = db_session.get(MetricExtraction, parsed_fact.source_ref_id)
    original_raw_value = extraction.raw_value_text
    db_session.commit()

    response = client.post(
        f"/api/v1/extractions/{extraction.id}/correct",
        headers=auth_headers(user),
        json={"corrected_value": "$70.00"},
    )

    assert response.status_code == 200, response.text
    db_session.refresh(extraction)
    fact = db_session.get(MetricFact, response.json()["fact_id"])
    assert extraction.corrected_by_user is False
    assert extraction.corrected_at is None
    assert extraction.raw_value_text == original_raw_value
    assert fact is not None
    assert fact.source_type == "manual"
    assert fact.source_document_id == doc.id
    assert fact.source_ref_id == extraction.id
    assert fact.metric_key == "mkt.price"
    assert fact.period_type == "AS_OF"
    assert fact.period_end_date == date(2026, 1, 2)
    assert fact.value_numeric == pytest.approx(70.0)


def test_extraction_target_correction_remains_visible_to_valuation_reader(
    client, db_session, user_factory, auth_headers
):
    from app.services.valuation import (
        VALUE_LINE_TARGET_MANUAL_CORRECTION_REFERENCE,
        read_valuation_context,
    )

    user = user_factory("extraction_target_correction@example.com")
    stock = Stock(ticker="XTGT", exchange="NYSE", company_name="Target Co")
    db_session.add(stock)
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="target-correction.pdf",
        source="upload",
        file_storage_key="/tmp/target-correction.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    parsed = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="target.price_18m.mid",
        value_numeric=150,
        unit="USD",
        currency="USD",
        period_type="TARGET_HORIZON",
        period_end_date=date(2027, 12, 31),
        source_type="parsed",
        is_current=True,
    )
    authorize_parsed_facts(db_session, document=document, facts=[parsed])
    extraction = db_session.get(MetricExtraction, parsed.source_ref_id)
    db_session.commit()

    response = client.post(
        f"/api/v1/extractions/{extraction.id}/correct",
        headers=auth_headers(user),
        json={"corrected_value": "$155"},
    )

    assert response.status_code == 200, response.text
    corrected = db_session.get(MetricFact, response.json()["fact_id"])
    assert corrected.value_json["corrected_from_fact_id"] == parsed.id
    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    assert context.system_reference_value == 155
    assert context.system_reference_fact_id == corrected.id
    assert (
        context.system_reference_type
        == VALUE_LINE_TARGET_MANUAL_CORRECTION_REFERENCE
    )


def test_extraction_correction_rejects_archived_source_without_writes(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("extraction_correction_archived@example.com")
    stock = Stock(ticker="ARCH", exchange="NYSE", company_name="Archived Co")
    db_session.add(stock)
    db_session.flush()
    doc = PdfDocument(
        user_id=user.id,
        file_name="archived.pdf",
        source="upload",
        file_storage_key="/tmp/archived.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        stock_id=stock.id,
    )
    db_session.add(doc)
    db_session.flush()
    extraction = MetricExtraction(
        user_id=user.id,
        document_id=doc.id,
        page_number=1,
        field_key="is.sales",
        raw_value_text="100",
        original_text_snippet="Sales 100",
        confidence_score=0.9,
    )
    db_session.add(extraction)
    db_session.commit()

    archived = client.delete(
        f"/api/v1/documents/{doc.id}", headers=auth_headers(user)
    )
    assert archived.status_code == 200, archived.text
    before_count = db_session.scalar(sa.select(sa.func.count(MetricFact.id)))

    response = client.post(
        f"/api/v1/extractions/{extraction.id}/correct",
        headers=auth_headers(user),
        json={"corrected_value": "101"},
    )

    assert response.status_code == 410, response.text
    assert response.json()["detail"]["code"] == "source_unavailable"
    assert response.json()["detail"]["reason"] == "document_archived"
    db_session.refresh(extraction)
    assert extraction.corrected_by_user is False
    assert extraction.corrected_at is None
    assert db_session.scalar(sa.select(sa.func.count(MetricFact.id))) == before_count


def test_extraction_correction_rebuilds_ratios_and_piotroski_projection(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("extraction_correction_rebuild@example.com")
    stock = Stock(ticker="REBLD", exchange="NYSE", company_name="Rebuild Co")
    db_session.add(stock)
    db_session.flush()
    doc = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="rebuild.pdf",
        source="upload",
        file_storage_key="/tmp/rebuild.pdf",
        parse_status="parsed",
    )
    db_session.add(doc)
    db_session.flush()
    slot = {"period_type": "FY", "period_end_date": date(2025, 12, 31)}
    net_income = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_numeric=100,
                unit="USD",
                source_type="parsed",
                is_current=True,
                **slot,
            )
    total_assets = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="bs.total_assets",
                value_numeric=1000,
                unit="USD",
                source_type="parsed",
                is_current=True,
                **slot,
            )
    authorize_parsed_facts(
        db_session, document=doc, facts=[net_income, total_assets]
    )
    net_income_extraction = db_session.get(MetricExtraction, net_income.source_ref_id)
    db_session.flush()
    old_roa = ValueLineRatioCalculator(db_session).calculate_for_stock(
        user_id=user.id, stock_id=stock.id
    )[0]
    old_score = next(
        fact
        for fact in PiotroskiFScoreCalculator(db_session).calculate_for_stock(
            user_id=user.id, stock_id=stock.id
        )
        if fact.metric_key == "score.piotroski.total"
    )
    db_session.commit()
    assert old_roa.value_numeric == pytest.approx(0.1)

    response = client.post(
        f"/api/v1/extractions/{net_income_extraction.id}/correct",
        headers=auth_headers(user),
        json={"corrected_value": "200"},
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()

    current_roa = db_session.query(MetricFact).filter_by(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="returns.roa",
        is_current=True,
    ).one()
    current_score = db_session.query(MetricFact).filter_by(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        is_current=True,
    ).one()
    assert current_roa.value_numeric == pytest.approx(0.2)
    assert current_roa.id != old_roa.id
    assert current_score.id != old_score.id
    assert db_session.get(MetricFact, old_roa.id).is_current is False
    assert db_session.get(MetricFact, old_score.id).is_current is False


def test_documents_compare_endpoint_returns_structured_diffs_by_fact_nature(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_compare@example.com")
    headers = auth_headers(user)

    stock = Stock(ticker="FICO", exchange="NYSE", company_name="Fair Isaac")
    db_session.add(stock)
    db_session.commit()

    left_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q1.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q1.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 9),
        upload_time=datetime.utcnow(),
    )
    right_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q2.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q2.pdf",
        parse_status="parsed",
        report_date=date(2026, 4, 9),
        upload_time=datetime.utcnow(),
    )
    db_session.add_all([left_doc, right_doc])
    db_session.commit()

    def compare_fact(
        metric_key: str,
        fact_nature: str,
        value: float,
        period_type: str,
        period_end_date: date,
        *,
        is_current: bool,
        unit: str | None = None,
    ) -> MetricFact:
        return MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key=metric_key,
            value_json={"fact_nature": fact_nature},
            value_numeric=value,
            unit=unit,
            period_type=period_type,
            period_end_date=period_end_date,
            source_type="parsed",
            is_current=is_current,
        )

    left_facts = [
        compare_fact(
            "is.net_income",
            "actual",
            100.0,
            "FY",
            date(2024, 12, 31),
            is_current=False,
            unit="USD",
        ),
        compare_fact(
            "estimate.eps_diluted",
            "estimate",
            21.5,
            "FY",
            date(2026, 12, 31),
            is_current=False,
            unit="USD",
        ),
        compare_fact(
            "snapshot.pe",
            "snapshot",
            28.0,
            "AS_OF",
            date(2026, 1, 9),
            is_current=False,
        ),
        compare_fact(
            "mkt.price",
            "snapshot",
            250.0,
            "AS_OF",
            date(2026, 1, 9),
            is_current=False,
        ),
    ]
    right_facts = [
        compare_fact(
            "is.net_income",
            "actual",
            120.0,
            "FY",
            date(2024, 12, 31),
            is_current=True,
            unit="USD",
        ),
        compare_fact(
            "estimate.eps_diluted",
            "estimate",
            22.0,
            "FY",
            date(2026, 12, 31),
            is_current=True,
            unit="USD",
        ),
        compare_fact(
            "snapshot.pe",
            "snapshot",
            31.0,
            "AS_OF",
            date(2026, 4, 9),
            is_current=True,
        ),
        compare_fact(
            "mkt.price",
            "snapshot",
            250.0,
            "AS_OF",
            date(2026, 4, 9),
            is_current=True,
        ),
    ]
    authorize_parsed_facts(db_session, document=left_doc, facts=left_facts)
    authorize_parsed_facts(db_session, document=right_doc, facts=right_facts)

    db_session.add_all(
        [
            MetricExtraction(
                user_id=user.id,
                document_id=left_doc.id,
                page_number=1,
                field_key="analyst_commentary",
                raw_value_text="Margins should expand gradually.",
                original_text_snippet="Commentary: Margins should expand gradually.",
                confidence_score=0.9,
                parser_version="v1",
            ),
            MetricExtraction(
                user_id=user.id,
                document_id=right_doc.id,
                page_number=1,
                field_key="analyst_commentary",
                raw_value_text="Margins should expand sharply through FY2027.",
                original_text_snippet="Commentary: Margins should expand sharply through FY2027.",
                confidence_score=0.9,
                parser_version="v1",
            ),
        ]
    )
    db_session.commit()

    resp = client.get(
        f"/api/v1/documents/compare?left_document_id={left_doc.id}&right_document_id={right_doc.id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["left_document"] == {
        "id": left_doc.id,
        "file_name": "fico-q1.pdf",
        "report_date": "2026-01-09",
    }
    assert payload["right_document"] == {
        "id": right_doc.id,
        "file_name": "fico-q2.pdf",
        "report_date": "2026-04-09",
    }
    assert payload["shared_tickers"] == ["FICO"]

    sections = {section["fact_nature"]: section for section in payload["sections"]}
    assert [section["fact_nature"] for section in payload["sections"]] == [
        "actual",
        "estimate",
        "snapshot",
        "opinion",
    ]

    assert sections["actual"]["items"] == [
        {
            "stock_ticker": "FICO",
            "metric_key": "is.net_income",
            "mapping_id": None,
            "period_type": "FY",
            "period_end_date": "2024-12-31",
            "label": "FICO · is.net_income",
            "change_type": "changed",
            "left_value": "100",
            "right_value": "120",
        }
    ]
    assert sections["estimate"]["items"] == [
        {
            "stock_ticker": "FICO",
            "metric_key": "estimate.eps_diluted",
            "mapping_id": None,
            "period_type": "FY",
            "period_end_date": "2026-12-31",
            "label": "FICO · estimate.eps_diluted",
            "change_type": "changed",
            "left_value": "21.5",
            "right_value": "22",
        }
    ]
    assert sections["snapshot"]["items"] == [
        {
            "stock_ticker": "FICO",
            "metric_key": "snapshot.pe",
            "mapping_id": None,
            "period_type": "AS_OF",
            "period_end_date": "2026-01-09",
            "label": "FICO · snapshot.pe",
            "change_type": "changed",
            "left_value": "28",
            "right_value": "31",
        }
    ]
    assert sections["opinion"]["items"] == [
        {
            "stock_ticker": None,
            "metric_key": "analyst.commentary",
            "mapping_id": "analyst.commentary.as_of",
            "period_type": "AS_OF",
            "period_end_date": "2026-01-09",
            "label": "analyst.commentary.as_of",
            "change_type": "changed",
            "left_value": "Margins should expand gradually.",
            "right_value": "Margins should expand sharply through FY2027.",
        }
    ]


def test_documents_compare_hides_parsed_facts_without_exact_authority(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("documents_compare_quarantine@example.com")
    stock = Stock(
        ticker="CMPQUAR",
        exchange="NYSE",
        company_name="Compare Quarantine",
    )
    db_session.add(stock)
    db_session.flush()
    left_doc = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="compare-exact-left.pdf",
        source="upload",
        file_storage_key="/tmp/compare-exact-left.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 1),
    )
    right_doc = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="compare-exact-right.pdf",
        source="upload",
        file_storage_key="/tmp/compare-exact-right.pdf",
        parse_status="parsed",
        report_date=date(2026, 4, 1),
    )
    db_session.add_all([left_doc, right_doc])
    db_session.flush()
    left_exact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_json={"fact_nature": "actual"},
        value_numeric=100,
        unit="USD",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        is_current=False,
    )
    right_exact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_json={"fact_nature": "actual"},
        value_numeric=110,
        unit="USD",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        is_current=True,
    )
    authorize_parsed_facts(db_session, document=left_doc, facts=[left_exact])
    authorize_parsed_facts(db_session, document=right_doc, facts=[right_exact])
    db_session.commit()

    # Simulate a retained pre-rollout/quarantined projection. It remains audit
    # data but has no immutable exact extraction authority for product display.
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.revenue",
                value_json={"fact_nature": "actual"},
                value_numeric=999,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=left_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.revenue",
                value_json={"fact_nature": "actual"},
                value_numeric=1111,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=right_doc.id,
                is_current=False,
            ),
        ]
    )
    db_session.flush()

    response = client.get(
        "/api/v1/documents/compare"
        f"?left_document_id={left_doc.id}&right_document_id={right_doc.id}",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    actual_keys = {
        item["metric_key"]
        for section in response.json()["sections"]
        if section["fact_nature"] == "actual"
        for item in section["items"]
    }
    assert "is.net_income" in actual_keys
    assert "is.revenue" not in actual_keys


def test_documents_list_requires_auth(client, db_session):
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 401, resp.text
