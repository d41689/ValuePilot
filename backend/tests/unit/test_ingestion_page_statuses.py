"""Ingestion-level tests for requires_ocr detection (F7) and the
first-page-wins report_date rule (F3b).

See docs/tasks/2026-07-02_value-line-parser-historical-readiness.md.
"""

import io
from datetime import date
from unittest.mock import patch

from fastapi import UploadFile

from app.models.users import User
from app.services.ingestion_service import IngestionService


def _upload_file(name: str = "test.pdf") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(b"%PDF-1.4 fake"))


def _make_user(db_session, email: str) -> User:
    user = User(email=email)
    db_session.add(user)
    db_session.commit()
    return user


def _company_page_text(ticker: str, analyst_date: str) -> str:
    return (
        f"TEST {ticker} CORP. RECENT 50.00 P/E 10.0 VALUE\n"
        f"NYSE-{ticker} PRICE RATIO LINE\n"
        "TIMELINESS 3 Lowered1/2/26\n"
        "SAFETY 2 Raised1/5/24\n"
        f"AnalystA {analyst_date}\n"
    )


def test_near_empty_page_reports_requires_ocr(db_session):
    user = _make_user(db_session, "requires_ocr_test@example.com")

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=[(1, "   ", [])],
    ), patch(
        "app.services.ingestion_service.FileStorageService.save_upload_file",
        return_value="/tmp/fake-requires-ocr.pdf",
    ):
        service = IngestionService(db_session)
        doc, page_reports = service.process_upload(user_id=user.id, file=_upload_file())

    assert len(page_reports) == 1
    report = page_reports[0]
    assert report["status"] == "requires_ocr"
    assert report["error_code"] == "requires_ocr"
    assert doc.parse_status == "requires_ocr"


def test_multipage_report_date_first_page_wins(db_session, caplog):
    user = _make_user(db_session, "report_date_overwrite_test@example.com")

    pages = [
        (1, _company_page_text("TXA", "January 9, 2026"), []),
        (2, _company_page_text("TXB", "January 16, 2026"), []),
    ]

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=pages,
    ), patch(
        "app.services.ingestion_service.FileStorageService.save_upload_file",
        return_value="/tmp/fake-multipage.pdf",
    ):
        service = IngestionService(db_session)
        doc, page_reports = service.process_upload(user_id=user.id, file=_upload_file())

    statuses = [report["status"] for report in page_reports]
    assert statuses == ["parsed", "parsed"]
    # First page's date sticks; the mismatching second page must not overwrite.
    assert doc.report_date == date(2026, 1, 9)
    assert any("report_date" in record.message for record in caplog.records)
