from unittest.mock import patch

from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock

def test_upload_multipage_parses_each_page_independently(client, db_session, user_factory, auth_headers):
    user = user_factory("multipage_upload@example.com")
    headers = auth_headers(user)

    page1_text = (
        "SMITH (A.O.)\nNYSE-AOS\nRECENT PRICE 68.11\nP/E RATIO 17.4\nDIV'D YLD 2.0%\n"
        "VALUE LINE\nAnalystX January 2, 2026\n"
    )
    page2_text = (
        "MICROSOFT CORP.\nMSFT (NDQ)\nRECENT PRICE 420.00\nP/E RATIO 30.0\nDIV'D YLD 0.8%\n"
        "VALUE LINE\nAnalystY January 2, 2026\n"
    )

    pages = [
        (1, page1_text, []),
        (2, page2_text, []),
    ]

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ):
        resp = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("multi.pdf", b"%PDF-1.4\\n%fake\\n", "application/pdf")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] == 2
    assert body["status"] == "parsed"
    assert body["page_reports"][0]["page_number"] == 1
    assert body["page_reports"][0]["status"] == "parsed"
    assert body["page_reports"][0]["ticker"] == "AOS"
    assert body["page_reports"][1]["page_number"] == 2
    assert body["page_reports"][1]["status"] == "parsed"
    assert body["page_reports"][1]["ticker"] == "MSFT"

    # pdf_documents.stock_id MUST be NULL for multi-company container
    from app.models.artifacts import PdfDocument
    from app.models.extractions import MetricExtraction
    from app.models.stocks import Stock

    doc = db_session.get(PdfDocument, body["document_id"])
    assert doc.stock_id is None
    assert doc.parse_status == "parsed"

    # Each page should have extractions
    page_numbers = {
        p[0]
        for p in db_session.query(MetricExtraction.page_number)
        .filter(MetricExtraction.document_id == doc.id)
        .all()
    }
    assert page_numbers == {1, 2}

    # Stocks created/resolved for each page
    tickers = {
        (s.ticker, s.exchange)
        for s in db_session.query(Stock)
        .filter(Stock.ticker.in_(["AOS", "MSFT"]))
        .all()
    }
    assert ("AOS", "NYSE") in tickers
    assert ("MSFT", "NDQ") in tickers


def test_upload_multipage_non_company_pages_do_not_block_parsed_status(client, db_session, user_factory, auth_headers):
    user = user_factory("multipage_partial@example.com")
    headers = auth_headers(user)

    page1_text = "SMITH (A.O.)\nNYSE-AOS\nRECENT PRICE 68.11\nVALUE LINE\nAnalystX January 2, 2026\n"
    page2_text = "THIS IS NOT A VALUE LINE REPORT\n"

    pages = [
        (1, page1_text, []),
        (2, page2_text, []),
    ]

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ):
        resp = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("multi.pdf", b"%PDF-1.4\\n%fake\\n", "application/pdf")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] == 2
    assert body["status"] == "parsed"
    assert body["page_reports"][0]["status"] == "parsed"
    assert body["page_reports"][1]["status"] == "unsupported_template"
    assert body["page_reports"][1]["error_code"] == "unsupported_template"


def test_upload_multipage_identity_unresolved_reports_error_code(client, db_session, user_factory, auth_headers):
    user = user_factory("multipage_identity@example.com")
    headers = auth_headers(user)

    page1_text = "SMITH (A.O.)\nNYSE-AOS\nRECENT PRICE 68.11\nVALUE LINE\nAnalystX January 2, 2026\n"
    page2_text = "RECENT PRICE 12.34\nVALUE LINE\n"

    pages = [
        (1, page1_text, []),
        (2, page2_text, []),
    ]

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ):
        resp = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("multi.pdf", b"%PDF-1.4\\n%fake\\n", "application/pdf")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] == 2
    assert body["status"] == "parsed_partial"
    assert body["page_reports"][0]["status"] == "parsed"
    assert body["page_reports"][1]["status"] == "failed"
    assert body["page_reports"][1]["error_code"] == "identity_unresolved"


def test_upload_rolls_back_failed_page_writes_before_later_page_succeeds(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("multipage-savepoint@example.com")
    pages = [
        (
            1,
            "SMITH (A.O.)\nNYSE-AOS\nRECENT PRICE 68.11\nP/E RATIO 17.4\n"
            "VALUE LINE\nAnalystX January 2, 2026\n",
            [],
        ),
        (
            2,
            "MICROSOFT CORP.\nMSFT (NDQ)\nRECENT PRICE 420.00\nP/E RATIO 30.0\n"
            "VALUE LINE\nAnalystY January 2, 2026\n",
            [],
        ),
    ]
    calls = 0

    def fail_after_first_page_writes(*, user_id, stock_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("calculated metric failure after parsed writes")

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ), patch(
        "app.services.ingestion_service.IngestionService._run_calculated_metrics",
        side_effect=fail_after_first_page_writes,
    ):
        response = client.post(
            "/api/v1/documents/upload",
            headers=auth_headers(user),
            files={"file": ("multi.pdf", b"%PDF-1.4\n%fake\n", "application/pdf")},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "parsed_partial"
    assert [row["status"] for row in payload["page_reports"]] == ["failed", "parsed"]
    assert db_session.query(MetricExtraction).filter_by(
        document_id=payload["document_id"], page_number=1
    ).count() == 0
    aos = db_session.query(Stock).filter_by(ticker="AOS", exchange="NYSE").one_or_none()
    if aos is not None:
        assert db_session.query(MetricFact).filter_by(
            stock_id=aos.id, source_document_id=payload["document_id"]
        ).count() == 0
    msft = db_session.query(Stock).filter_by(ticker="MSFT", exchange="NDQ").one()
    assert db_session.query(MetricFact).filter_by(
        stock_id=msft.id, source_document_id=payload["document_id"]
    ).count() > 0
