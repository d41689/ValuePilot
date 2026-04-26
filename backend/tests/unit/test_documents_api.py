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

    db_session.add_all(
        [
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
    )
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
