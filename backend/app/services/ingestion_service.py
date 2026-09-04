import logging
import re
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, update, select, text
from sqlalchemy.dialects.postgresql import insert
from fastapi import UploadFile

from app.models.artifacts import (
    PdfDocument,
    DocumentPage,
    ValueLineFactExtractionInput,
    ValueLineParseRun,
)
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.file_storage import FileStorageService
from app.services.identity_service import IdentityService
from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.v1_value_line.page_json import build_value_line_page_json
from app.ingestion.parsers.v1_value_line.semantics import has_value_line_markers
from app.ingestion.normalization.scaler import Scaler
from app.services.mapping_spec import load_resolved_value_line_mapping_spec
from app.services.owners_earnings import (
    OE_INPUT_KEYS,
    build_normalized_owners_earnings_fact,
    build_owners_earnings_facts,
)
from app.services.canonical_financials import MethodGateDecision, reviewed_method_gate
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator


LOGGER = logging.getLogger(__name__)
VALUE_LINE_REPARSE_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('valuepilot:value-line-reparse-document:' || "
    "CAST(:document_id AS text), 0))"
)

# Image-only (scanned) pages yield an empty or near-empty native text layer,
# while genuine Value Line company pages carry thousands of characters. The
# threshold is deliberately minimal — it flags "effectively empty" pages (a
# text layer that cannot even hold one header line) as needing OCR, which is
# not yet implemented (see docs/BACKLOG.md).
MIN_PARSEABLE_PAGE_TEXT_CHARS = 20


def _is_company_page(text: str) -> bool:
    upper = (text or "").upper()
    # Includes glued text-layer variants ("RECENT109.10", "RECEN1T062.19").
    return re.search(r"\bRECEN(?:\dT|T)\s*(?:PRICE\s+)?\d", upper) is not None


def _is_company_candidate(text: str, identity_ticker: Optional[str]) -> bool:
    """A page is only a company-page candidate when it is structurally a
    Value Line report — a bare ticker in a non-VL PDF must not parse."""
    if not has_value_line_markers(text):
        return False
    return bool(identity_ticker) or _is_company_page(text)

class IngestionService:
    NON_NUMERIC_KEYS = {
        "report_date",
        "analyst_name",
        "analyst_commentary",
        "business_description",
        "annual_rates_of_change",
        "institutional_decisions",
        "company_financial_strength",
        "capital_structure_as_of",
        "market_cap_as_of",
        "pension_assets_as_of",
        "price_semantics_and_returns",
        "long_term_projection_year_range",
    }
    CAPITAL_STRUCTURE_AS_OF_KEYS = {
        "total_debt",
        "debt_due_in_5_years",
        "lt_debt",
        "lt_interest",
        "debt_percent_of_capital",
        "lt_interest_percent_of_capital",
        "leases_uncapitalized_annual_rentals",
        "pension_obligations",
        "preferred_stock",
        "preferred_dividend",
    }
    RANGE_KEYS = {
        "target_18m_low",
        "target_18m_high",
        "target_18m_mid",
        "target_18m_upside_pct",
        "long_term_projection_year_range",
        "long_term_projection_high_price",
        "long_term_projection_high_price_gain_pct",
        "long_term_projection_high_total_return_pct",
        "long_term_projection_low_price",
        "long_term_projection_low_price_gain_pct",
        "long_term_projection_low_total_return_pct",
    }

    def __init__(self, db: Session):
        self.db = db
        self.storage = FileStorageService()
        self.identity_service = IdentityService(db)
        self.mapping_spec = load_resolved_value_line_mapping_spec()

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
        saved_path_str = self.storage.save_upload_file(file, f"tmp/{unique_filename}")
        saved_path = Path(saved_path_str)

        # 2. Create PdfDocument record
        doc = PdfDocument(
            user_id=user_id,
            file_name=file.filename or "unknown.pdf",
            source="upload",
            file_storage_key=saved_path_str,
            parse_status="uploaded",
            upload_time=datetime.now(),
            report_date=None,
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

            parse_run = self._start_value_line_parse_run(
                user_id=user_id,
                document_id=doc.id,
            )

            is_multi_company_container = len(pages_data) > 1
            if is_multi_company_container:
                doc.stock_id = None

            company_pages = 0
            parsed_company_pages = 0
            requires_ocr_pages = 0

            for page_num, text, words in pages_data:
                page_savepoint = None
                try:
                    if len((text or "").strip()) < MIN_PARSEABLE_PAGE_TEXT_CHARS:
                        requires_ocr_pages += 1
                        page_reports.append(
                            {
                                "page_number": page_num,
                                "status": "requires_ocr",
                                "parser_version": "v1",
                                "error_code": "requires_ocr",
                                "error_message": (
                                    "Text layer too sparse for native parsing; "
                                    "page likely needs OCR (not yet implemented)."
                                ),
                            }
                        )
                        continue

                    parser = ValueLineV1Parser(text, page_words={1: words})
                    identity_info = parser.extract_identity()
                    if not _is_company_candidate(text, identity_info.ticker):
                        page_reports.append(
                            {
                                "page_number": page_num,
                                "status": "unsupported_template",
                                "parser_version": "v1",
                                "error_code": "unsupported_template",
                                "error_message": "Non-company page skipped (Value Line industry summary).",
                            }
                        )
                        continue

                    company_pages += 1
                    # A page is the smallest publishable Value Line unit.  If
                    # any downstream extraction, fact, or calculation step
                    # fails, none of that page's writes may survive merely
                    # because another page later succeeds.
                    page_savepoint = self.db.begin_nested()

                    try:
                        stock, needs_review, note = self.identity_service.resolve_stock(identity_info)
                    except ValueError:
                        page_savepoint.rollback()
                        page_savepoint = None
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
                    report_date = self._report_date_from_extractions(extractions)
                    if report_date is None:
                        raise ValueError("missing_commentary_date")
                    if doc.report_date is None:
                        doc.report_date = report_date
                    elif doc.report_date != report_date:
                        LOGGER.warning(
                            "Page %s report_date %s differs from document report_date %s "
                            "(document_id=%s); keeping the first-parsed date.",
                            page_num,
                            report_date,
                            doc.report_date,
                            doc.id,
                        )
                    page_json = build_value_line_page_json(
                        parser,
                        page_number=page_num,
                        results=extractions,
                    )

                    extraction_ids_by_key: dict[str, list[int]] = {}
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
                            value_line_parse_run_id=parse_run.id,
                        )
                        self.db.add(metric_record)
                        self.db.flush()
                        extraction_ids_by_key.setdefault(ext.field_key, []).append(
                            metric_record.id
                        )

                    facts, _, unmapped = self.mapping_spec.generate_facts(page_json)
                    owner_earnings_gate = reviewed_method_gate(
                        self.db,
                        stock_id=stock.id,
                        method_key="owner_earnings",
                        effective_as_of=report_date,
                    )
                    for path in sorted(unmapped):
                        LOGGER.warning(
                            "Unmapped page_json path: %s (document_id=%s page=%s)",
                            path,
                            doc.id,
                            page_num,
                        )
                    for fact in facts:
                        source_extraction_ids = self._mapping_source_extraction_ids(
                            fact,
                            extraction_ids_by_key=extraction_ids_by_key,
                        )
                        self._insert_metric_fact_from_mapping(
                            user_id=user_id,
                            stock_id=stock.id,
                            metric_key=fact["metric_key"],
                            value_numeric=fact.get("value_numeric"),
                            value_text=fact.get("value_text"),
                            value_json=fact.get("value_json"),
                            unit=fact.get("unit"),
                            currency=fact.get("currency"),
                            period_type=fact.get("period_type"),
                            period_end_date=fact.get("period_end_date"),
                            source_document_id=doc.id,
                            value_line_parse_run_id=parse_run.id,
                            source_extraction_ids=source_extraction_ids,
                        )

                    if owner_earnings_gate.status == "approved":
                        self._persist_owner_earnings_facts(
                            user_id=user_id,
                            stock_id=stock.id,
                            report_date=report_date,
                            value_line_parse_run_id=parse_run.id,
                            method_decision=owner_earnings_gate,
                        )

                    self._run_calculated_metrics(user_id=user_id, stock_id=stock.id)
                    page_savepoint.commit()
                    page_savepoint = None

                    parsed_company_pages += 1
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
                    if page_savepoint is not None and page_savepoint.is_active:
                        page_savepoint.rollback()
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

            if parsed_company_pages == 0:
                # No parseable company page at all AND at least one page was
                # too sparse to read natively → the honest status is OCR-needed.
                if company_pages == 0 and requires_ocr_pages > 0:
                    doc.parse_status = "requires_ocr"
                else:
                    doc.parse_status = "failed"
            elif parsed_company_pages < company_pages:
                doc.parse_status = "parsed_partial"
            else:
                doc.parse_status = "parsed"

            if parsed_company_pages == 1:
                self._archive_single_company_value_line_pdf(doc)

            self._finish_value_line_parse_run(
                parse_run,
                status="succeeded" if parsed_company_pages else "failed",
            )
            
            self.db.commit()
            self.db.refresh(doc)
            
        except Exception as e:
            # Handle failure
            self.db.rollback()
            doc = self.db.get(PdfDocument, doc.id)
            if doc is None:
                raise
            doc.parse_status = "failed"
            doc.notes = f"Extraction failed: {str(e)}"
            self.db.commit()
            raise e

        return doc, page_reports

    def _archive_single_company_value_line_pdf(self, doc: PdfDocument) -> Optional[dict]:
        if not doc.stock_id or not doc.report_date:
            return None

        stock = self.db.get(Stock, doc.stock_id)
        if stock is None:
            return None

        archived_path = self.storage.archive_value_line_pdf(
            self.storage.get_file_path(doc.file_storage_key),
            exchange=stock.exchange,
            ticker=stock.ticker,
            report_date=doc.report_date,
        )
        archived_path_str = str(archived_path)

        matching_docs = self.db.scalars(
            select(PdfDocument).where(
                PdfDocument.stock_id == stock.id,
                PdfDocument.report_date == doc.report_date,
                PdfDocument.source == "upload",
                PdfDocument.id != doc.id,
                PdfDocument.file_storage_key != archived_path_str,
            )
        ).all()
        archived_hash = self.storage.sha256_file(archived_path)
        backfilled_document_count = 0
        for matching_doc in matching_docs:
            existing_path = self.storage.get_file_path(matching_doc.file_storage_key)
            if existing_path.is_file() and self.storage.sha256_file(existing_path) != archived_hash:
                LOGGER.warning(
                    "Skipping canonical PDF backfill for document_id=%s because existing file content differs",
                    matching_doc.id,
                )
                continue
            matching_doc.file_storage_key = archived_path_str
            self.db.add(matching_doc)
            backfilled_document_count += 1

        doc.file_storage_key = archived_path_str
        self.db.add(doc)
        return {
            "file_storage_key": archived_path_str,
            "backfilled_document_count": backfilled_document_count,
        }

    def reparse_existing_document(
        self,
        *,
        user_id: int,
        document_id: int,
        reextract_pdf: bool = False,
    ) -> PdfDocument:
        """
        Append one immutable parse revision and publish it atomically.

        A failed reparse rolls its run, extraction, fact, document-cache, and
        currentness changes back together, leaving the prior current facts
        untouched.
        """
        doc = self.db.get(PdfDocument, document_id)
        if not doc or doc.user_id != user_id:
            raise ValueError("Document not found for user")

        self.db.execute(
            VALUE_LINE_REPARSE_LOCK_SQL,
            {"document_id": document_id},
        )
        self.db.refresh(doc)

        try:
            with self.db.begin_nested():
                doc = self._reparse_existing_document_revision(
                    user_id=user_id,
                    document_id=document_id,
                    reextract_pdf=reextract_pdf,
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.expire_all()
            raise
        self.db.refresh(doc)
        return doc

    def _reparse_existing_document_revision(
        self,
        *,
        user_id: int,
        document_id: int,
        reextract_pdf: bool,
    ) -> PdfDocument:
        doc = self.db.get(PdfDocument, document_id)
        if not doc or doc.user_id != user_id:
            raise ValueError("Document not found for user")
        prior_company_page_numbers = set(
            self.db.scalars(
                select(MetricExtraction.page_number).where(
                    MetricExtraction.document_id == doc.id
                )
            ).all()
        )

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
            pages_data = [(p.page_number, p.page_text or "", []) for p in doc.pages]
            pages_data = sorted(pages_data, key=lambda item: item[0])
            saved_path = self.storage.get_file_path(doc.file_storage_key)
            try:
                extracted_pages = PdfExtractor.extract_pages_with_words(saved_path)
            except FileNotFoundError:
                extracted_pages = []
            words_by_page = {page_num: words for page_num, _, words in extracted_pages}
            text_by_page = {page_num: text for page_num, text, _ in extracted_pages}
            if not pages_data:
                pages_data = extracted_pages
            else:
                pages_data = [
                    (
                        page_num,
                        text or text_by_page.get(page_num, ""),
                        words_by_page.get(page_num, []),
                    )
                    for page_num, text, _ in pages_data
                ]
            if not doc.raw_text:
                doc.raw_text = "\n".join([page_text or "" for _, page_text, _ in pages_data])

        if not pages_data:
            raise ValueError("reparse produced no source pages")

        parse_run = self._start_value_line_parse_run(
            user_id=user_id,
            document_id=doc.id,
        )
        prior_document_stock_id = doc.stock_id
        self._reset_document_parse_projection(doc)
        # Reconciliation may authorize the freshly rebuilt facts while the
        # owning transaction computes deterministic metrics.  The terminal
        # status is assigned below before commit.
        doc.parse_status = "parsing"

        is_multi_company_container = len(pages_data) > 1
        if is_multi_company_container:
            doc.stock_id = None
        doc.report_date = None

        company_pages = 0
        parsed_company_pages = 0
        parsed_stock_ids: set[int] = set()
        parsed_page_numbers: set[int] = set()

        for page_num, text, words in pages_data:
            if len((text or "").strip()) < MIN_PARSEABLE_PAGE_TEXT_CHARS:
                continue
            parser = ValueLineV1Parser(text, page_words={1: words} if words else {})
            identity_info = parser.extract_identity()
            if not _is_company_candidate(text, identity_info.ticker):
                continue
            company_pages += 1
            try:
                stock, needs_review, note = self.identity_service.resolve_stock(identity_info)
            except ValueError:
                continue

            if not is_multi_company_container:
                doc.stock_id = stock.id
                doc.identity_needs_review = needs_review

            if needs_review and note:
                doc.notes = (doc.notes or "") + f"\n[page {page_num}] {note}"

            extractions = parser.parse()
            report_date = self._report_date_from_extractions(extractions)
            if report_date is None:
                continue
            if doc.report_date is None:
                doc.report_date = report_date
            elif doc.report_date != report_date:
                LOGGER.warning(
                    "Page %s report_date %s differs from document report_date %s "
                    "(document_id=%s); keeping the first-parsed date.",
                    page_num,
                    report_date,
                    doc.report_date,
                    doc.id,
                )
            page_json = build_value_line_page_json(
                parser,
                page_number=page_num,
                results=extractions,
            )
            extraction_ids_by_key: dict[str, list[int]] = {}
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
                    value_line_parse_run_id=parse_run.id,
                )
                self.db.add(metric_record)
                self.db.flush()
                extraction_ids_by_key.setdefault(ext.field_key, []).append(
                    metric_record.id
                )

            facts, _, unmapped = self.mapping_spec.generate_facts(page_json)
            owner_earnings_gate = reviewed_method_gate(
                self.db,
                stock_id=stock.id,
                method_key="owner_earnings",
                effective_as_of=report_date,
            )
            for path in sorted(unmapped):
                LOGGER.warning(
                    "Unmapped page_json path: %s (document_id=%s page=%s)",
                    path,
                    doc.id,
                    page_num,
                )
            for fact in facts:
                source_extraction_ids = self._mapping_source_extraction_ids(
                    fact,
                    extraction_ids_by_key=extraction_ids_by_key,
                )
                self._insert_metric_fact_from_mapping(
                    user_id=user_id,
                    stock_id=stock.id,
                    metric_key=fact["metric_key"],
                    value_numeric=fact.get("value_numeric"),
                    value_text=fact.get("value_text"),
                    value_json=fact.get("value_json"),
                    unit=fact.get("unit"),
                    currency=fact.get("currency"),
                    period_type=fact.get("period_type"),
                    period_end_date=fact.get("period_end_date"),
                    source_document_id=doc.id,
                    value_line_parse_run_id=parse_run.id,
                    source_extraction_ids=source_extraction_ids,
                )

            if owner_earnings_gate.status == "approved":
                self._persist_owner_earnings_facts(
                    user_id=user_id,
                    stock_id=stock.id,
                    report_date=report_date,
                    value_line_parse_run_id=parse_run.id,
                    method_decision=owner_earnings_gate,
                )

            parsed_stock_ids.add(stock.id)
            parsed_page_numbers.add(page_num)
            parsed_company_pages += 1

        if parsed_company_pages == 0:
            raise ValueError("reparse produced no successful company pages")
        if (
            parsed_company_pages < company_pages
            or not prior_company_page_numbers.issubset(parsed_page_numbers)
        ):
            # A reparse publishes one atomic replacement revision.  A partial
            # page set cannot be interpreted as deletion of fields/pages that
            # were present in the prior successful revision.
            raise ValueError("reparse produced an incomplete company-page revision")
        doc.parse_status = "parsed"

        for stock_id in sorted(parsed_stock_ids):
            self._run_calculated_metrics(user_id=user_id, stock_id=stock_id)

        if (
            prior_document_stock_id is not None
            and doc.stock_id is not None
            and prior_document_stock_id != doc.stock_id
        ):
            # Identity changes are published only after every company page has
            # parsed successfully.  Old-stock rows cannot share an exact slot
            # with the replacement stock and therefore need this explicit,
            # document-scoped demotion.
            self.db.execute(
                update(MetricFact)
                .where(
                    MetricFact.source_document_id == doc.id,
                    MetricFact.source_type == "parsed",
                    MetricFact.stock_id == prior_document_stock_id,
                    MetricFact.is_current.is_(True),
                )
                .values(is_current=False)
            )
            self.db.flush()

        self._finish_value_line_parse_run(parse_run, status="succeeded")
        return doc

    def _reset_document_parse_projection(self, doc: PdfDocument) -> None:
        # Reparse never rewrites or deletes extraction/fact audit history.
        # Existing facts remain current until an exact replacement slot is
        # appended.  Missing output is not evidence that a prior fact vanished.
        doc.stock_id = None
        doc.report_date = None
        doc.identity_needs_review = False
        doc.notes = None
        self.db.add(doc)
        self.db.flush()

    def _run_calculated_metrics(self, *, user_id: int, stock_id: int) -> None:
        ValueLineRatioCalculator(self.db).calculate_for_stock(user_id=user_id, stock_id=stock_id)
        PiotroskiFScoreCalculator(self.db).calculate_for_stock(user_id=user_id, stock_id=stock_id)

    def _persist_owner_earnings_facts(
        self,
        *,
        user_id: int,
        stock_id: int,
        report_date: date,
        value_line_parse_run_id: int | None = None,
        method_decision: MethodGateDecision | None = None,
    ) -> list[MetricFact]:
        """Persist base-derived OEPS first, then its normalized snapshot.

        Production ingestion supplies the immutable parse-run ID, preventing a
        calculation from silently combining facts from different Value Line
        report revisions.  The optional form exists for canonical backfills and
        tests; duplicate slots still fail closed in the pure builder.
        """

        decision = method_decision or reviewed_method_gate(
            self.db,
            stock_id=stock_id,
            method_key="owner_earnings",
            effective_as_of=report_date,
        )
        if decision.status != "approved":
            return []
        method_snapshot = decision.as_dict()

        source_query = select(MetricFact).where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == stock_id,
            MetricFact.source_type == "parsed",
            MetricFact.is_current.is_(True),
            MetricFact.period_type == "FY",
            MetricFact.metric_key.in_(OE_INPUT_KEYS),
        )
        if value_line_parse_run_id is not None:
            source_query = source_query.where(
                MetricFact.value_line_parse_run_id == value_line_parse_run_id
            )
        source_facts = self.db.scalars(
            source_query.order_by(
                MetricFact.period_end_date.asc(),
                MetricFact.metric_key.asc(),
                MetricFact.id.asc(),
            )
        ).all()
        annual = []
        for payload in build_owners_earnings_facts(source_facts):
            payload["value_json"] = {
                **(payload.get("value_json") or {}),
                "analysis_method": method_snapshot,
            }
            annual.append(
                self._insert_calculated_fact(
                    user_id=user_id,
                    stock_id=stock_id,
                    payload=payload,
                )
            )
        normalized = build_normalized_owners_earnings_fact(
            annual,
            report_date=report_date,
        )
        if normalized is not None:
            normalized["value_json"] = {
                **(normalized.get("value_json") or {}),
                "analysis_method": method_snapshot,
            }
            annual.append(
                self._insert_calculated_fact(
                    user_id=user_id,
                    stock_id=stock_id,
                    payload=normalized,
                )
            )
        return annual

    def _insert_calculated_fact(
        self,
        *,
        user_id: int,
        stock_id: int,
        payload: dict,
    ) -> MetricFact:
        self.db.execute(
            update(MetricFact)
            .where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == payload["metric_key"],
                MetricFact.period_type == payload.get("period_type"),
                MetricFact.period_end_date == payload.get("period_end_date"),
                MetricFact.source_type == "calculated",
                MetricFact.is_current.is_(True),
            )
            .values(is_current=False)
        )
        fact = MetricFact(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=payload["metric_key"],
            value_numeric=payload.get("value_numeric"),
            value_text=payload.get("value_text"),
            value_json=payload.get("value_json"),
            unit=payload.get("unit"),
            currency=payload.get("currency"),
            period_type=payload.get("period_type"),
            period_end_date=payload.get("period_end_date"),
            source_type="calculated",
            source_ref_id=None,
            source_document_id=None,
            is_current=True,
            # ``func.now()`` is transaction-start time in PostgreSQL and can
            # precede the authority cutoff captured later in a long-lived
            # transaction.  This origin boundary needs the actual insert time.
            created_at=func.clock_timestamp(),
        )
        self.db.add(fact)
        self.db.flush()
        return fact

    def _start_value_line_parse_run(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> ValueLineParseRun:
        run = ValueLineParseRun(
            user_id=user_id,
            document_id=document_id,
            parser_version="value-line-v1",
            source_mapping_version=self.mapping_spec.source_mapping_version,
            status="running",
        )
        self.db.add(run)
        self.db.flush()
        return run

    def _finish_value_line_parse_run(
        self,
        run: ValueLineParseRun,
        *,
        status: str,
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError("invalid Value Line parse-run terminal status")
        run.status = status
        self.db.add(run)
        self.db.flush()

    @staticmethod
    def _report_date_from_extractions(extractions: list) -> Optional[date]:
        for ext in extractions:
            if ext.field_key != "report_date":
                continue
            if isinstance(ext.parsed_value_json, dict):
                iso = ext.parsed_value_json.get("iso_date")
                if iso:
                    try:
                        return date.fromisoformat(iso)
                    except ValueError:
                        pass
            if ext.raw_value_text:
                try:
                    return date.fromisoformat(ext.raw_value_text)
                except ValueError:
                    pass
        return None

    @staticmethod
    def _rating_event_dates(extractions: list) -> dict[str, Optional[date]]:
        event_dates: dict[str, Optional[date]] = {}
        for ext in extractions:
            if ext.field_key not in {"timeliness", "safety", "technical"}:
                continue
            if isinstance(ext.parsed_value_json, dict):
                event = ext.parsed_value_json.get("event")
                if isinstance(event, dict):
                    parsed = IngestionService._parse_date_value(event.get("date"))
                    if parsed:
                        event_dates[ext.field_key] = parsed
                        continue
                notes = ext.parsed_value_json.get("notes")
            else:
                notes = None
            search_text = notes or ext.original_text_snippet or ""
            match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2})", search_text)
            if not match:
                event_dates[ext.field_key] = None
                continue
            event_dates[ext.field_key] = date(
                2000 + int(match.group(3)),
                int(match.group(1)),
                int(match.group(2)),
            )
        return event_dates

    @staticmethod
    def _derived_period_end_date(
        metric_key: str,
        report_date: Optional[date],
        rating_event_dates: dict[str, Optional[date]],
    ) -> Optional[date]:
        if not report_date:
            return None

        header_keys = {
            "recent_price",
            "pe_ratio",
            "pe_ratio_trailing",
            "pe_ratio_median",
            "relative_pe_ratio",
            "dividend_yield",
        }
        quality_keys = {
            "company_financial_strength",
            "stock_price_stability",
            "price_growth_persistence",
            "earnings_predictability",
        }
        target_keys = {
            "target_18m_low",
            "target_18m_high",
            "target_18m_mid",
            "target_18m_upside_pct",
        }
        projection_keys = {
            "long_term_projection_year_range",
            "long_term_projection_high_price",
            "long_term_projection_high_price_gain_pct",
            "long_term_projection_high_total_return_pct",
            "long_term_projection_low_price",
            "long_term_projection_low_price_gain_pct",
            "long_term_projection_low_total_return_pct",
        }

        if metric_key in header_keys:
            return report_date
        if metric_key in rating_event_dates:
            return rating_event_dates.get(metric_key)
        if metric_key in quality_keys:
            return report_date
        if metric_key in target_keys:
            return report_date
        if metric_key in projection_keys:
            return report_date

        return None

    @staticmethod
    def _parse_date_value(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2})", value)
            if not match:
                return None
            return date(
                2000 + int(match.group(3)),
                int(match.group(1)),
                int(match.group(2)),
            )

    @staticmethod
    def _year_end_date(value: object) -> Optional[date]:
        if isinstance(value, int):
            return date(value, 12, 31)
        if isinstance(value, str):
            if value.isdigit() and len(value) == 4:
                return date(int(value), 12, 31)
            return IngestionService._parse_date_value(value)
        return None

    def _as_of_dates_from_extractions(self, extractions: list) -> dict[str, Optional[date]]:
        dates = {
            "capital_structure": None,
            "pension_assets": None,
            "market_cap": None,
            "common_stock": None,
        }
        for ext in extractions:
            if ext.field_key == "capital_structure_as_of":
                parsed = None
                if isinstance(ext.parsed_value_json, dict):
                    parsed = ext.parsed_value_json.get("iso_date")
                dates["capital_structure"] = self._parse_date_value(parsed or ext.raw_value_text)
            elif ext.field_key == "pension_assets_as_of":
                parsed = None
                if isinstance(ext.parsed_value_json, dict):
                    parsed = ext.parsed_value_json.get("iso_date")
                dates["pension_assets"] = self._parse_date_value(parsed or ext.raw_value_text)
            elif ext.field_key == "market_cap_as_of":
                parsed = None
                if isinstance(ext.parsed_value_json, dict):
                    parsed = ext.parsed_value_json.get("iso_date")
                dates["market_cap"] = self._parse_date_value(parsed or ext.raw_value_text)
            elif ext.field_key == "common_stock_shares_outstanding":
                if isinstance(ext.parsed_value_json, dict):
                    dates["common_stock"] = self._parse_date_value(ext.parsed_value_json.get("as_of"))
        return dates

    def _resolve_period_end_date(
        self,
        metric_key: str,
        parsed_value_json: object,
        report_date: Optional[date],
        rating_event_dates: dict[str, Optional[date]],
        as_of_dates: dict[str, Optional[date]],
    ) -> tuple[Optional[date], Optional[str], bool]:
        period_type = None
        period_end_date = None
        period_end_date_is_derived = False

        if isinstance(parsed_value_json, dict):
            period_type = parsed_value_json.get("period_type")
            period_end = parsed_value_json.get("period_end_date")
            if period_end:
                period_end_date = self._parse_date_value(period_end)

        if period_end_date is None:
            if metric_key in self.CAPITAL_STRUCTURE_AS_OF_KEYS:
                period_end_date = as_of_dates.get("capital_structure")
            elif metric_key == "pension_assets":
                period_end_date = as_of_dates.get("pension_assets")
            elif metric_key == "market_cap":
                period_end_date = as_of_dates.get("market_cap")
            elif metric_key == "capital_structure_as_of":
                period_end_date = as_of_dates.get("capital_structure")
            elif metric_key == "market_cap_as_of":
                period_end_date = as_of_dates.get("market_cap")
            elif metric_key == "pension_assets_as_of":
                period_end_date = as_of_dates.get("pension_assets")
            elif metric_key == "report_date":
                period_end_date = report_date
            elif metric_key in {"common_stock_shares_outstanding", "shares_outstanding"}:
                period_end_date = as_of_dates.get("common_stock")

        if period_end_date is None:
            period_end_date = self._derived_period_end_date(
                metric_key,
                report_date,
                rating_event_dates,
            )
            period_end_date_is_derived = period_end_date is not None

        if period_type is None:
            period_type = self._derived_period_type(
                metric_key,
                period_end_date,
                report_date,
                rating_event_dates,
            )

        if period_end_date is None and period_type == "AS_OF" and report_date:
            period_end_date = report_date
            period_end_date_is_derived = True

        return period_end_date, period_type, period_end_date_is_derived

    def _derived_period_type(
        self,
        metric_key: str,
        period_end_date: Optional[date],
        report_date: Optional[date],
        rating_event_dates: dict[str, Optional[date]],
    ) -> Optional[str]:
        if metric_key in rating_event_dates:
            return "EVENT"
        if metric_key in self.RANGE_KEYS:
            return "RANGE"

        header_keys = {
            "recent_price",
            "pe_ratio",
            "pe_ratio_trailing",
            "pe_ratio_median",
            "relative_pe_ratio",
            "dividend_yield",
            "beta",
        }
        quality_keys = {
            "company_financial_strength",
            "stock_price_stability",
            "price_growth_persistence",
            "earnings_predictability",
        }
        as_of_keys = {
            "report_date",
            "analyst_name",
            "analyst_commentary",
            "business_description",
            "capital_structure_as_of",
            "market_cap_as_of",
            "pension_assets_as_of",
            "price_semantics_and_returns",
            "institutional_decisions",
            "annual_rates_of_change",
        }
        if (
            metric_key in header_keys
            or metric_key in quality_keys
            or metric_key in as_of_keys
            or metric_key in self.CAPITAL_STRUCTURE_AS_OF_KEYS
            or metric_key in {"market_cap", "pension_assets", "common_stock_shares_outstanding", "shares_outstanding"}
        ):
            return "AS_OF"

        if report_date and period_end_date == report_date:
            return "AS_OF"

        return None

    @staticmethod
    def _infer_value_type(metric_key: str) -> str:
        if "yield" in metric_key or metric_key.endswith("_pct"):
            return "percent"
        if "ratio" in metric_key:
            return "ratio"
        if metric_key in {"beta", "relative_pe_ratio"}:
            return "ratio"
        if "_usd" in metric_key:
            return "currency"
        return "number"

    @staticmethod
    def _format_raw_value(value: float, value_type: str, scale_token: Optional[str]) -> str:
        if value_type == "percent":
            return f"{value}%"
        if scale_token:
            return f"{value} {scale_token}"
        return f"{value}"

    @staticmethod
    def _build_value_json(
        parsed_value_json: object,
        raw_value_text: Optional[str],
        norm_val: Optional[float],
        norm_unit: Optional[str],
    ) -> object:
        value_json: object = {"raw": raw_value_text, "normalized": norm_val, "unit": norm_unit}
        if parsed_value_json is not None:
            value_json = (
                dict(parsed_value_json)
                if isinstance(parsed_value_json, dict)
                else parsed_value_json
            )
            if isinstance(value_json, dict):
                if value_json.pop("is_estimate", None) is True:
                    value_json.setdefault("fact_nature", "estimate")
                elif "fact_nature" not in value_json and value_json.get("period_type") in {"FY", "Q"}:
                    value_json["fact_nature"] = "actual"
                if raw_value_text is not None:
                    value_json.setdefault("raw", raw_value_text)
                if norm_val is not None:
                    value_json.setdefault("normalized", norm_val)
                if norm_unit is not None:
                    value_json.setdefault("unit", norm_unit)
        return value_json

    def _insert_metric_fact(
        self,
        *,
        user_id: int,
        stock_id: int,
        metric_key: str,
        raw_value_text: Optional[str],
        parsed_value_json: object,
        period_type: Optional[str],
        period_end_date: Optional[date],
        period_end_date_is_derived: bool,
        source_ref_id: Optional[int],
        source_document_id: Optional[int],
        value_line_parse_run_id: Optional[int] = None,
        value_type_override: Optional[str] = None,
        force_numeric: bool = False,
    ) -> None:
        value_type = value_type_override or self._infer_value_type(metric_key)
        norm_val, norm_unit = (None, None)
        if raw_value_text is not None and (force_numeric or metric_key not in self.NON_NUMERIC_KEYS):
            norm_val, norm_unit = Scaler.normalize(raw_value_text, value_type)

        value_json = self._build_value_json(parsed_value_json, raw_value_text, norm_val, norm_unit)
        if value_line_parse_run_id is not None:
            value_json = dict(value_json or {})
            value_json.setdefault(
                "source_mapping_version", self.mapping_spec.source_mapping_version
            )
            value_json.setdefault("definition_basis", "adjusted")
            value_json.setdefault("dimensions_identity", "empty")
        value_text = raw_value_text if metric_key in self.NON_NUMERIC_KEYS else None

        self._demote_document_parsed_slot(
            stock_id=stock_id,
            metric_key=metric_key,
            period_type=period_type,
            period_end_date=period_end_date,
            source_document_id=source_document_id,
        )
        insert_stmt = insert(MetricFact).values(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            value_json=value_json,  # type: ignore[arg-type]
            value_numeric=norm_val,
            value_text=value_text,
            unit=norm_unit,
            period_type=period_type,
            period_end_date=period_end_date,
            source_type="parsed",
            source_ref_id=source_ref_id,
            source_document_id=source_document_id,
            value_line_parse_run_id=value_line_parse_run_id,
            is_current=True,
        )
        self.db.execute(insert_stmt)
        self.db.flush()
        self._reconcile_parsed_fact_current_slot(
            stock_id=stock_id,
            metric_key=metric_key,
            period_type=period_type,
            period_end_date=period_end_date,
        )

    def _insert_metric_fact_from_mapping(
        self,
        *,
        user_id: int,
        stock_id: int,
        metric_key: str,
        value_numeric: Optional[float],
        value_text: Optional[str],
        value_json: Optional[dict],
        unit: Optional[str],
        currency: Optional[str],
        period_type: Optional[str],
        period_end_date: Optional[date],
        source_document_id: Optional[int],
        value_line_parse_run_id: Optional[int] = None,
        source_extraction_ids: tuple[int, ...] = (),
    ) -> int:
        if value_line_parse_run_id is not None:
            value_json = dict(value_json or {})
            value_json.setdefault(
                "source_mapping_version", self.mapping_spec.source_mapping_version
            )
            value_json.setdefault("definition_basis", "adjusted")
            value_json.setdefault("dimensions_identity", "empty")
        self._demote_document_parsed_slot(
            stock_id=stock_id,
            metric_key=metric_key,
            period_type=period_type,
            period_end_date=period_end_date,
            source_document_id=source_document_id,
        )
        insert_stmt = insert(MetricFact).values(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            value_json=value_json,  # type: ignore[arg-type]
            value_numeric=value_numeric,
            value_text=value_text,
            unit=unit,
            currency=currency,
            period_type=period_type,
            period_end_date=period_end_date,
            source_type="parsed",
            source_ref_id=None,
            source_document_id=source_document_id,
            value_line_parse_run_id=value_line_parse_run_id,
            is_current=True,
        )
        fact_id = self.db.execute(
            insert_stmt.returning(MetricFact.id)
        ).scalar_one()
        if value_line_parse_run_id is not None and source_extraction_ids:
            role = "primary" if len(source_extraction_ids) == 1 else "supporting"
            self.db.add_all(
                [
                    ValueLineFactExtractionInput(
                        fact_id=fact_id,
                        extraction_id=extraction_id,
                        value_line_parse_run_id=value_line_parse_run_id,
                        input_role=role,
                        input_ordinal=ordinal,
                        created_txid=0,
                    )
                    for ordinal, extraction_id in enumerate(
                        source_extraction_ids,
                        start=1,
                    )
                ]
            )
        self.db.flush()
        self._reconcile_parsed_fact_current_slot(
            stock_id=stock_id,
            metric_key=metric_key,
            period_type=period_type,
            period_end_date=period_end_date,
        )
        return fact_id

    @staticmethod
    def _mapping_source_extraction_ids(
        fact: dict,
        *,
        extraction_ids_by_key: dict[str, list[int]],
    ) -> tuple[int, ...]:
        declared = fact.get("source_extraction_keys")
        if not isinstance(declared, (tuple, list)) or not declared:
            return ()
        if any(
            not isinstance(key, str) or key not in extraction_ids_by_key
            for key in declared
        ):
            return ()
        return tuple(
            extraction_id
            for key in declared
            for extraction_id in extraction_ids_by_key[key]
        )

    def _demote_document_parsed_slot(
        self,
        *,
        stock_id: int,
        metric_key: str,
        period_type: Optional[str],
        period_end_date: Optional[date],
        source_document_id: Optional[int],
    ) -> None:
        if source_document_id is None:
            return
        self.db.execute(
            update(MetricFact)
            .where(
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.period_type == period_type,
                MetricFact.period_end_date == period_end_date,
                MetricFact.source_document_id == source_document_id,
                MetricFact.source_type == "parsed",
                MetricFact.is_current.is_(True),
            )
            .values(is_current=False)
        )
        self.db.flush()

    def _reconcile_parsed_fact_current_slot(
        self,
        *,
        stock_id: int,
        metric_key: str,
        period_type: Optional[str],
        period_end_date: Optional[date],
    ) -> None:
        facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.source_type == "parsed",
                MetricFact.period_type == period_type,
                MetricFact.period_end_date == period_end_date,
            )
        ).all()
        if not facts:
            return

        doc_ids = sorted({fact.source_document_id for fact in facts if fact.source_document_id is not None})
        report_dates_by_doc: dict[int, Optional[date]] = {}
        if doc_ids:
            report_dates_by_doc = dict(
                self.db.execute(
                    select(PdfDocument.id, PdfDocument.report_date).where(PdfDocument.id.in_(doc_ids))
                ).all()
            )

        winner = max(
            facts,
            key=lambda fact: (
                report_dates_by_doc.get(fact.source_document_id or -1) or date.min,
                fact.source_document_id or -1,
                fact.id or -1,
            ),
        )

        for fact in facts:
            fact.is_current = fact.id == winner.id
            self.db.add(fact)
        self.db.flush()
