import uuid
from datetime import datetime, date
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import update
from fastapi import UploadFile

from app.models.artifacts import PdfDocument, DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.services.file_storage import FileStorageService
from app.services.identity_service import IdentityService
from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.normalization.scaler import Scaler

class IngestionService:
    def __init__(self, db: Session):
        self.db = db
        self.storage = FileStorageService()
        self.identity_service = IdentityService(db)

    def process_upload(self, user_id: int, file: UploadFile) -> tuple[PdfDocument, list[dict]]:
        """
        Handles the full upload and ingestion process:
        1. Save file to storage.
        2. Create PdfDocument record.
        3. Extract text (Phase 1 of extraction).
        4. Save DocumentPage records.
        5. Parse pages independently (multi-page supported).
        6. Run Normalization & Fact Creation per page-resolved stock.
        """
        # 1. Save file
        file_ext = Path(file.filename).suffix if file.filename else ".pdf"
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        saved_path_str = self.storage.save_upload_file(file, unique_filename)
        saved_path = Path(saved_path_str)

        # 2. Create PdfDocument record
        doc = PdfDocument(
            user_id=user_id,
            file_name=file.filename or "unknown.pdf",
            source="upload",
            file_storage_key=saved_path_str,
            parse_status="uploaded",
            upload_time=datetime.now()
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        page_reports: list[dict] = []

        try:
            # 3. Extract text
            # For V1 we assume native text extraction is primary
            pages_data = PdfExtractor.extract_pages_with_words(saved_path)
            
            full_text_parts = []
            page_words: dict[int, list[dict]] = {}

            # 4. Save DocumentPage records
            for page_num, text, words in pages_data:
                full_text_parts.append(text)
                page_words[page_num] = words
                page_record = DocumentPage(
                    document_id=doc.id,
                    page_number=page_num,
                    page_text=text,
                    text_extraction_method="native_text"
                )
                self.db.add(page_record)
            
            # Update main document with cached raw text
            doc.raw_text = "\n".join(full_text_parts)
            doc.parse_status = "parsing"
            self.db.add(doc)
            self.db.commit()
            self.db.refresh(doc)

            is_multi_company_container = len(pages_data) > 1
            if is_multi_company_container:
                doc.stock_id = None

            def is_value_line_page(text: str) -> bool:
                upper = (text or "").upper()
                return ("VALUE LINE" in upper) or ("VALUELINE" in upper)

            parsed_pages = 0

            for page_num, text, words in pages_data:
                try:
                    if not is_value_line_page(text):
                        page_reports.append(
                            {
                                "page_number": page_num,
                                "status": "failed",
                                "parser_version": "v1",
                                "error_code": "unsupported_template",
                                "error_message": "Page did not match Value Line V1 template.",
                            }
                        )
                        continue

                    parser = ValueLineV1Parser(text, page_words={1: words})
                    identity_info = parser.extract_identity()

                    try:
                        stock, needs_review, note = self.identity_service.resolve_stock(identity_info)
                    except ValueError:
                        page_reports.append(
                            {
                                "page_number": page_num,
                                "status": "failed",
                                "parser_version": "v1",
                                "error_code": "identity_unresolved",
                                "error_message": "Could not resolve ticker/exchange for page.",
                            }
                        )
                        continue

                    if not is_multi_company_container:
                        doc.stock_id = stock.id
                        doc.identity_needs_review = needs_review

                    if needs_review and note:
                        doc.notes = (doc.notes or "") + f"\n[page {page_num}] {note}"

                    extractions = parser.parse()

                    for ext in extractions:
                        metric_record = MetricExtraction(
                            user_id=user_id,
                            document_id=doc.id,
                            page_number=page_num,
                            field_key=ext.field_key,
                            raw_value_text=ext.raw_value_text,
                            original_text_snippet=ext.original_text_snippet,
                            parsed_value_json=ext.parsed_value_json,
                            confidence_score=ext.confidence_score,
                            bbox_json=ext.bbox_json,
                            parser_template_id=None,
                            parser_version="v1",
                        )
                        self.db.add(metric_record)
                        self.db.flush()

                        non_numeric_keys = {
                            "report_date",
                            "analyst_name",
                            "business_description",
                            "annual_rates_of_change",
                            "current_position_usd_millions",
                            "quarterly_sales_usd_millions",
                            "earnings_per_share",
                            "quarterly_dividends_paid_per_share",
                            "institutional_decisions",
                            "company_financial_strength",
                        }
                        value_type = "number"
                        if "yield" in ext.field_key or "pct" in ext.field_key:
                            value_type = "percent"
                        elif "ratio" in ext.field_key:
                            value_type = "ratio"
                        elif ext.field_key in {"beta", "relative_pe_ratio"}:
                            value_type = "ratio"
                        elif "_usd" in ext.field_key:
                            value_type = "currency"

                        norm_val, norm_unit = (None, None)
                        if ext.raw_value_text is not None and ext.field_key not in non_numeric_keys:
                            norm_val, norm_unit = Scaler.normalize(ext.raw_value_text, value_type)

                        metric_key = ext.field_key
                        period_type = None
                        period_end_date = None
                        if isinstance(ext.parsed_value_json, dict):
                            period_type = ext.parsed_value_json.get("period_type")
                            period_end = ext.parsed_value_json.get("period_end_date")
                            if period_end:
                                try:
                                    period_end_date = date.fromisoformat(period_end)
                                except ValueError:
                                    period_end_date = None

                        update_stmt = (
                            update(MetricFact)
                            .where(
                                MetricFact.stock_id == stock.id,
                                MetricFact.metric_key == metric_key,
                                MetricFact.source_type == "parsed",
                                MetricFact.is_current.is_(True),
                            )
                            .values(is_current=False)
                        )
                        if period_end_date:
                            update_stmt = update_stmt.where(MetricFact.period_end_date == period_end_date)
                        self.db.execute(update_stmt)

                        value_json: object = {"raw": ext.raw_value_text, "normalized": norm_val, "unit": norm_unit}
                        if ext.parsed_value_json is not None:
                            value_json = (
                                dict(ext.parsed_value_json)
                                if isinstance(ext.parsed_value_json, dict)
                                else ext.parsed_value_json
                            )
                            if isinstance(value_json, dict):
                                if ext.raw_value_text is not None:
                                    value_json.setdefault("raw", ext.raw_value_text)
                                if norm_val is not None:
                                    value_json.setdefault("normalized", norm_val)
                                if norm_unit is not None:
                                    value_json.setdefault("unit", norm_unit)

                        self.db.add(
                            MetricFact(
                                user_id=user_id,
                                stock_id=stock.id,
                                metric_key=metric_key,
                                value_json=value_json,  # type: ignore[arg-type]
                                value_numeric=norm_val,
                                unit=norm_unit,
                                period_type=period_type,
                                period_end_date=period_end_date,
                                source_type="parsed",
                                source_ref_id=metric_record.id,
                                is_current=True,
                            )
                        )

                    parsed_pages += 1
                    page_reports.append(
                        {
                            "page_number": page_num,
                            "status": "parsed",
                            "parser_version": "v1",
                            "stock_id": stock.id,
                            "ticker": stock.ticker,
                            "exchange": stock.exchange,
                        }
                    )
                except Exception as e:
                    page_reports.append(
                        {
                            "page_number": page_num,
                            "status": "failed",
                            "parser_version": "v1",
                            "error_code": "parse_error",
                            "error_message": str(e),
                        }
                    )
                    continue

            if parsed_pages == 0:
                doc.parse_status = "failed"
            elif parsed_pages < len(pages_data):
                doc.parse_status = "parsed_partial"
            else:
                doc.parse_status = "parsed"
            
            self.db.commit()
            self.db.refresh(doc)
            
        except Exception as e:
            # Handle failure
            doc.parse_status = "failed"
            doc.notes = f"Extraction failed: {str(e)}"
            self.db.commit()
            raise e

        return doc, page_reports

    def reparse_existing_document(self, *, user_id: int, document_id: int, reextract_pdf: bool = False) -> PdfDocument:
        """
        Re-runs parsing on an existing document without mutating prior metric_extractions rows.
        Inserts new metric_extractions + metric_facts and deactivates prior parsed current facts per metric_key.
        """
        doc = self.db.get(PdfDocument, document_id)
        if not doc or doc.user_id != user_id:
            raise ValueError("Document not found for user")

        page_words: dict[int, list[dict]] = {}
        if reextract_pdf:
            saved_path = self.storage.get_file_path(doc.file_storage_key)
            pages_data = PdfExtractor.extract_pages_with_words(saved_path)
            # Refresh stored page text cache (raw_text is optional cache per PRD)
            self.db.query(DocumentPage).filter(DocumentPage.document_id == doc.id).delete()
            full_text_parts = []
            for page_num, text, words in pages_data:
                full_text_parts.append(text)
                page_words[page_num] = words
                self.db.add(
                    DocumentPage(
                        document_id=doc.id,
                        page_number=page_num,
                        page_text=text,
                        text_extraction_method="native_text",
                    )
                )
            doc.raw_text = "\n".join(full_text_parts)
        else:
            if not doc.raw_text:
                doc.raw_text = "\n".join([p.page_text or "" for p in doc.pages])

        parser = ValueLineV1Parser(doc.raw_text or "", page_words=page_words)
        identity_info = parser.extract_identity()
        self.identity_service.resolve_stock_identity(doc, identity_info)

        extractions = parser.parse()
        for ext in extractions:
            metric_record = MetricExtraction(
                user_id=user_id,
                document_id=doc.id,
                page_number=ext.page_number,
                field_key=ext.field_key,
                raw_value_text=ext.raw_value_text,
                original_text_snippet=ext.original_text_snippet,
                parsed_value_json=ext.parsed_value_json,
                confidence_score=ext.confidence_score,
                bbox_json=ext.bbox_json,
                parser_template_id=None,
                parser_version="v1",
            )
            self.db.add(metric_record)
            self.db.flush()

            if doc.stock_id:
                value_type = "number"
                non_numeric_keys = {
                    "report_date",
                    "analyst_name",
                    "business_description",
                    "annual_rates_of_change",
                    "current_position_usd_millions",
                    "quarterly_sales_usd_millions",
                    "earnings_per_share",
                    "quarterly_dividends_paid_per_share",
                    "institutional_decisions",
                    "company_financial_strength",
                }
                if "yield" in ext.field_key or "pct" in ext.field_key:
                    value_type = "percent"
                elif "ratio" in ext.field_key:
                    value_type = "ratio"
                elif ext.field_key in {"beta", "relative_pe_ratio"}:
                    value_type = "ratio"
                elif "_usd" in ext.field_key:
                    value_type = "currency"

                norm_val, norm_unit = (None, None)
                if ext.raw_value_text is not None and ext.field_key not in non_numeric_keys:
                    norm_val, norm_unit = Scaler.normalize(ext.raw_value_text, value_type)
                metric_key = ext.field_key
                period_type = None
                period_end_date = None
                if isinstance(ext.parsed_value_json, dict):
                    period_type = ext.parsed_value_json.get("period_type")
                    period_end = ext.parsed_value_json.get("period_end_date")
                    if period_end:
                        try:
                            period_end_date = date.fromisoformat(period_end)
                        except ValueError:
                            period_end_date = None

                update_stmt = (
                    update(MetricFact)
                    .where(
                        MetricFact.stock_id == doc.stock_id,
                        MetricFact.metric_key == metric_key,
                        MetricFact.source_type == "parsed",
                        MetricFact.is_current.is_(True),
                    )
                    .values(is_current=False)
                )
                if period_end_date:
                    update_stmt = update_stmt.where(MetricFact.period_end_date == period_end_date)
                self.db.execute(update_stmt)

                value_json: object = {"raw": ext.raw_value_text, "normalized": norm_val, "unit": norm_unit}
                if ext.parsed_value_json is not None:
                    value_json = (
                        dict(ext.parsed_value_json)
                        if isinstance(ext.parsed_value_json, dict)
                        else ext.parsed_value_json
                    )
                    if isinstance(value_json, dict):
                        if ext.raw_value_text is not None:
                            value_json.setdefault("raw", ext.raw_value_text)
                        if norm_val is not None:
                            value_json.setdefault("normalized", norm_val)
                        if norm_unit is not None:
                            value_json.setdefault("unit", norm_unit)

                self.db.add(
                    MetricFact(
                        user_id=user_id,
                        stock_id=doc.stock_id,
                        metric_key=metric_key,
                        value_json=value_json,  # type: ignore[arg-type]
                        value_numeric=norm_val,
                        unit=norm_unit,
                        period_type=period_type,
                        period_end_date=period_end_date,
                        source_type="parsed",
                        source_ref_id=metric_record.id,
                        is_current=True,
                    )
                )

        doc.parse_status = "parsed"
        self.db.commit()
        self.db.refresh(doc)
        return doc
