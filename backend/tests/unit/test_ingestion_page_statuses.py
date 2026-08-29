"""Ingestion-level tests for requires_ocr detection (F7) and the
first-page-wins report_date rule (F3b).

See docs/tasks/2026-07-02_value-line-parser-historical-readiness.md.
"""

import io
from datetime import date
from unittest.mock import patch

from fastapi import UploadFile
import pytest

from app.models.artifacts import PdfDocument
from app.models.users import User
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.ingestion_service import (
    IngestionService,
    _canonicalize_page_facts,
)


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


def test_upload_fails_before_filesystem_write_when_account_is_not_active(
    db_session,
):
    user = _make_user(db_session, "erased-before-upload@example.com")

    with patch(
        "app.services.ingestion_service.acquire_active_account_mutation_lock",
        return_value=False,
    ), patch(
        "app.services.ingestion_service.FileStorageService.save_upload_file"
    ) as save_upload:
        service = IngestionService(db_session)
        with pytest.raises(ValueError, match="Account is not active"):
            service.process_upload(user_id=user.id, file=_upload_file())

    save_upload.assert_not_called()


def test_upload_discards_new_file_when_document_registration_fails(
    db_session,
    monkeypatch,
    tmp_path,
):
    user = _make_user(db_session, "upload-registration-failure@example.com")
    service = IngestionService(db_session)
    service.storage.upload_dir = tmp_path
    saved_path = tmp_path / "tmp" / "unregistered.pdf"

    def _save_file(_upload, _destination):
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_bytes(b"private upload")
        return str(saved_path)

    monkeypatch.setattr(service.storage, "save_upload_file", _save_file)
    monkeypatch.setattr(
        db_session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("registration failed")),
    )

    with pytest.raises(RuntimeError, match="registration failed"):
        service.process_upload(user_id=user.id, file=_upload_file())

    assert not saved_path.exists()


def test_page_fact_conflict_uses_mapping_precedence_without_losing_evidence():
    selected = _canonicalize_page_facts(
        [
            {
                "metric_key": "bs.total_assets",
                "period_type": "FY",
                "period_end_date": date(2025, 12, 31),
                "value_numeric": 30_251_000_000.0,
                "unit": "USD",
                "value_json": {"fact_nature": "actual"},
                "source_extraction_field_key": "capital_structure",
            },
            {
                "metric_key": "bs.total_assets",
                "period_type": "FY",
                "period_end_date": date(2025, 12, 31),
                "value_numeric": 30_250_700_000.0,
                "unit": "USD",
                "value_json": {"fact_nature": "actual"},
                "source_extraction_field_key": "annual_financials",
            },
        ]
    )

    assert len(selected) == 1
    assert selected[0]["value_numeric"] == 30_250_700_000.0
    assert selected[0]["source_extraction_field_key"] == "annual_financials"
    assert selected[0]["value_json"]["mapping_conflicts"] == [
        {
            "source_extraction_field_key": "capital_structure",
            "value_numeric": 30_251_000_000.0,
            "value_text": None,
            "unit": "USD",
            "resolution": "mapping_spec_later_path_precedence",
        }
    ]


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


def test_failed_page_rolls_back_partial_extractions_and_canonical_facts(db_session):
    user = _make_user(db_session, "page_atomicity_test@example.com")
    page_text = _company_page_text("ATOM", "January 9, 2026")

    with patch(
        "app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
        return_value=[(1, page_text, [])],
    ), patch(
        "app.services.ingestion_service.FileStorageService.save_upload_file",
        return_value="/tmp/fake-page-atomicity.pdf",
    ):
        service = IngestionService(db_session)
        with patch.object(
            service.mapping_spec,
            "generate_facts",
            return_value=(
                [
                    {
                        "metric_key": "mkt.price",
                        "value_numeric": 50.0,
                        "value_text": None,
                        "value_json": {"fact_nature": "snapshot"},
                        "unit": "USD",
                        "period_type": "AS_OF",
                        "period_end_date": date(2026, 1, 9),
                        "source_extraction_field_key": "recent_price",
                    },
                    {
                        "metric_key": "val.pe",
                        "value_numeric": 10.0,
                        "value_text": None,
                        "value_json": {"fact_nature": "snapshot"},
                        "unit": "ratio",
                        "period_type": "AS_OF",
                        "period_end_date": date(2026, 1, 9),
                        "source_extraction_field_key": "missing_extraction",
                    },
                ],
                set(),
                set(),
            ),
        ):
            doc, page_reports = service.process_upload(
                user_id=user.id,
                file=_upload_file(),
            )

    assert doc.parse_status == "failed"
    assert page_reports[0]["status"] == "failed"
    assert "mapped_fact_missing_exact_extraction_lineage" in page_reports[0][
        "error_message"
    ]
    assert db_session.query(MetricExtraction).filter_by(document_id=doc.id).count() == 0
    assert (
        db_session.query(MetricFact)
        .filter(
            MetricFact.source_document_id == doc.id,
            MetricFact.source_type == "parsed",
        )
        .count()
        == 0
    )


def test_parsed_fact_collision_is_idempotent_only_for_exact_lineage(db_session):
    user = _make_user(db_session, "parsed-insert-only@example.com")
    stock = Stock(ticker="PIO", exchange="NYSE", company_name="Parsed Insert Only")
    db_session.add(stock)
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="insert-only.pdf",
        source="upload",
        file_storage_key="tests/insert-only.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    extraction = MetricExtraction(
        user_id=user.id,
        document_id=document.id,
        page_number=1,
        field_key="sales",
        raw_value_text="100",
        original_text_snippet="Sales 100",
        parsed_value_json={"value": 100},
        parser_version="test",
        parse_generation=document.current_parse_generation,
    )
    db_session.add(extraction)
    db_session.flush()

    values = {
        "user_id": user.id,
        "stock_id": stock.id,
        "metric_key": "is.sales",
        "value_json": {"raw": "100"},
        "value_numeric": 100.0,
        "value_text": None,
        "unit": "USD",
        "period_type": "FY",
        "period_end_date": date(2025, 12, 31),
        "source_type": "parsed",
        "source_ref_id": extraction.id,
        "source_document_id": document.id,
        "parse_generation": document.current_parse_generation,
        "is_current": True,
    }
    service = IngestionService(db_session)
    service._insert_parsed_fact_idempotent(values)
    service._insert_parsed_fact_idempotent(values)
    assert db_session.query(MetricFact).filter_by(
        source_document_id=document.id,
        metric_key="is.sales",
    ).count() == 1

    with pytest.raises(
        ValueError,
        match="parsed_fact_identity_conflict_requires_new_generation",
    ):
        service._insert_parsed_fact_idempotent(
            {**values, "value_numeric": 999.0}
        )
