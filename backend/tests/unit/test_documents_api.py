from datetime import datetime

from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument, DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact


def test_documents_list_returns_companies_and_page_count(client, db_session):
    user = User(email="documents_list@example.com")
    db_session.add(user)
    db_session.commit()

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

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key="recent_price",
                value_json={"raw": "1"},
                value_numeric=1.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=e1.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key="recent_price",
                value_json={"raw": "2"},
                value_numeric=2.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=e2.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_b.id,
                metric_key="recent_price",
                value_json={"raw": "3"},
                value_numeric=3.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=e3.id,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    resp = client.get(f"/api/v1/documents?user_id={user.id}")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    doc_map = {doc["id"]: doc for doc in payload}
    assert doc_one.id in doc_map
    assert doc_two.id in doc_map

    one = doc_map[doc_one.id]
    assert one["page_count"] == 1
    assert one["parsed_page_count"] == 1
    assert one["companies"] == [{"ticker": "AOS", "company_name": "SMITH (A.O.)"}]

    two = doc_map[doc_two.id]
    assert two["page_count"] == 2
    assert two["parsed_page_count"] == 2
    assert {c["ticker"] for c in two["companies"]} == {"AOS", "MSFT"}


def test_documents_raw_text_endpoint(client, db_session):
    user = User(email="documents_raw@example.com")
    db_session.add(user)
    db_session.commit()

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

    resp = client.get(f"/api/v1/documents/{doc.id}/raw_text?user_id={user.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["raw_text"] == "hello world"
