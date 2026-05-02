from datetime import date

from app.core.config import settings
from app.models.artifacts import PdfDocument
from app.models.stocks import Stock
from app.services.file_storage import FileStorageService
from app.services.ingestion_service import IngestionService


def test_file_storage_archives_value_line_pdf_to_canonical_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    service = FileStorageService()
    temp_path = tmp_path / "tmp" / "upload.pdf"
    temp_path.parent.mkdir(parents=True)
    temp_path.write_bytes(b"%PDF-1.4\nAOS report\n%%EOF\n")

    archived_path = service.archive_value_line_pdf(
        temp_path,
        exchange="nyse",
        ticker="AOS",
        report_date=date(2026, 1, 2),
    )

    assert archived_path.parent == tmp_path / "value_line" / "NYSE" / "AOS"
    assert archived_path.name.startswith("2026-01-02-")
    assert archived_path.suffix == ".pdf"
    assert archived_path.read_bytes() == b"%PDF-1.4\nAOS report\n%%EOF\n"
    assert not temp_path.exists()


def test_file_storage_reuses_existing_canonical_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    service = FileStorageService()

    first_temp = tmp_path / "tmp" / "first.pdf"
    second_temp = tmp_path / "tmp" / "second.pdf"
    first_temp.parent.mkdir(parents=True)
    first_temp.write_bytes(b"%PDF-1.4\nsame report\n%%EOF\n")
    second_temp.write_bytes(b"%PDF-1.4\nsame report\n%%EOF\n")

    first_path = service.archive_value_line_pdf(
        first_temp,
        exchange="NYSE",
        ticker="AOS",
        report_date=date(2026, 1, 2),
    )
    second_path = service.archive_value_line_pdf(
        second_temp,
        exchange="NYSE",
        ticker="AOS",
        report_date=date(2026, 1, 2),
    )

    assert second_path == first_path
    assert first_path.exists()
    assert not second_temp.exists()


def test_ingestion_archive_backfills_matching_document_paths(
    db_session, user_factory, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    user = user_factory("canonical-storage@example.com")
    other_user = user_factory("canonical-storage-other@example.com")
    stock = Stock(ticker="AOS", exchange="NYSE", company_name="SMITH (A.O.)")
    other_stock = Stock(ticker="MSFT", exchange="NDQ", company_name="Microsoft")
    db_session.add_all([stock, other_stock])
    db_session.commit()

    current_temp = tmp_path / "tmp" / "current.pdf"
    current_temp.parent.mkdir(parents=True)
    current_temp.write_bytes(b"%PDF-1.4\ncanonical report\n%%EOF\n")

    current_doc = PdfDocument(
        user_id=user.id,
        file_name="aos-current.pdf",
        source="upload",
        file_storage_key=str(current_temp),
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        stock_id=stock.id,
    )
    historical_same_report = PdfDocument(
        user_id=other_user.id,
        file_name="aos-lost.pdf",
        source="upload",
        file_storage_key="/code/storage/uploads/old-lost.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        stock_id=stock.id,
    )
    different_date = PdfDocument(
        user_id=user.id,
        file_name="aos-other-date.pdf",
        source="upload",
        file_storage_key="/code/storage/uploads/other-date.pdf",
        parse_status="parsed",
        report_date=date(2026, 2, 2),
        stock_id=stock.id,
    )
    different_stock = PdfDocument(
        user_id=user.id,
        file_name="msft.pdf",
        source="upload",
        file_storage_key="/code/storage/uploads/msft.pdf",
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        stock_id=other_stock.id,
    )
    different_existing_path = tmp_path / "legacy" / "aos-different.pdf"
    different_existing_path.parent.mkdir(parents=True)
    different_existing_path.write_bytes(b"%PDF-1.4\ndifferent revision\n%%EOF\n")
    same_date_different_existing_file = PdfDocument(
        user_id=user.id,
        file_name="aos-different-existing.pdf",
        source="upload",
        file_storage_key=str(different_existing_path),
        parse_status="parsed",
        report_date=date(2026, 1, 2),
        stock_id=stock.id,
    )
    db_session.add_all(
        [
            current_doc,
            historical_same_report,
            different_date,
            different_stock,
            same_date_different_existing_file,
        ]
    )
    db_session.commit()

    result = IngestionService(db_session)._archive_single_company_value_line_pdf(current_doc)
    db_session.commit()

    db_session.refresh(current_doc)
    db_session.refresh(historical_same_report)
    db_session.refresh(different_date)
    db_session.refresh(different_stock)
    db_session.refresh(same_date_different_existing_file)

    assert result is not None
    canonical_path = result["file_storage_key"]
    assert canonical_path.endswith(".pdf")
    assert "/value_line/NYSE/AOS/2026-01-02-" in canonical_path
    assert current_doc.file_storage_key == canonical_path
    assert historical_same_report.file_storage_key == canonical_path
    assert different_date.file_storage_key == "/code/storage/uploads/other-date.pdf"
    assert different_stock.file_storage_key == "/code/storage/uploads/msft.pdf"
    assert same_date_different_existing_file.file_storage_key == str(different_existing_path)
