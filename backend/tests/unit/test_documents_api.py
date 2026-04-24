from datetime import date, datetime

import sqlalchemy as sa

from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument, DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact


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

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key="mkt.price",
                value_json={"raw": "1"},
                value_numeric=1.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=e1.id,
                source_document_id=doc_one.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_a.id,
                metric_key="mkt.price",
                value_json={"raw": "2"},
                value_numeric=2.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=e2.id,
                source_document_id=doc_two.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock_b.id,
                metric_key="mkt.price",
                value_json={"raw": "3"},
                value_numeric=3.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=e3.id,
                source_document_id=doc_two.id,
                is_current=True,
            ),
        ]
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

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "100"},
                value_numeric=100.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=old_extraction.id,
                source_document_id=old_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "110"},
                value_numeric=110.0,
                unit="USD",
                source_type="parsed",
                source_ref_id=new_extraction.id,
                source_document_id=new_doc.id,
                is_current=True,
            ),
        ]
    )
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
    assert parsed_fact.is_current is False
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

    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="mkt.price",
        value_numeric=68.11,
        unit="USD",
        source_type="parsed",
        source_document_id=doc.id,
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

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_json={"fact_nature": "actual"},
                value_numeric=100.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=left_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_json={"fact_nature": "actual"},
                value_numeric=120.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=right_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="estimate.eps_diluted",
                value_json={"fact_nature": "estimate"},
                value_numeric=21.5,
                unit="USD",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_document_id=left_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="estimate.eps_diluted",
                value_json={"fact_nature": "estimate"},
                value_numeric=22.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_document_id=right_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="snapshot.pe",
                value_json={"fact_nature": "snapshot"},
                value_numeric=28.0,
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_document_id=left_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="snapshot.pe",
                value_json={"fact_nature": "snapshot"},
                value_numeric=31.0,
                period_type="AS_OF",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=right_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"fact_nature": "snapshot"},
                value_numeric=250.0,
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_document_id=left_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"fact_nature": "snapshot"},
                value_numeric=250.0,
                period_type="AS_OF",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=right_doc.id,
                is_current=True,
            ),
        ]
    )

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


def test_documents_list_requires_auth(client, db_session):
    db_session.execute(sa.text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    db_session.commit()

    resp = client.get("/api/v1/documents")
    assert resp.status_code == 401, resp.text
