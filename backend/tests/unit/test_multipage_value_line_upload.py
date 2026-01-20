from unittest.mock import patch

from app.models.users import User


def test_upload_multipage_parses_each_page_independently(client, db_session):
    user = User(email="multipage_upload@example.com")
    db_session.add(user)
    db_session.commit()

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
            f"/api/v1/documents/upload?user_id={user.id}",
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


def test_upload_multipage_non_company_pages_do_not_block_parsed_status(client, db_session):
    user = User(email="multipage_partial@example.com")
    db_session.add(user)
    db_session.commit()

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
            f"/api/v1/documents/upload?user_id={user.id}",
            files={"file": ("multi.pdf", b"%PDF-1.4\\n%fake\\n", "application/pdf")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] == 2
    assert body["status"] == "parsed"
    assert body["page_reports"][0]["status"] == "parsed"
    assert body["page_reports"][1]["status"] == "unsupported_template"
    assert body["page_reports"][1]["error_code"] == "unsupported_template"


def test_upload_multipage_identity_unresolved_reports_error_code(client, db_session):
    user = User(email="multipage_identity@example.com")
    db_session.add(user)
    db_session.commit()

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
            f"/api/v1/documents/upload?user_id={user.id}",
            files={"file": ("multi.pdf", b"%PDF-1.4\\n%fake\\n", "application/pdf")},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page_count"] == 2
    assert body["status"] == "parsed_partial"
    assert body["page_reports"][0]["status"] == "parsed"
    assert body["page_reports"][1]["status"] == "failed"
    assert body["page_reports"][1]["error_code"] == "identity_unresolved"
