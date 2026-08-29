import logging
import re
import uuid
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, update, select, text as sql_text
from sqlalchemy.dialects.postgresql import insert
from fastapi import UploadFile

from app.models.artifacts import PdfDocument, DocumentPage
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
from app.services.mapping_spec import MappingSpec
from app.services.owners_earnings import build_owners_earnings_facts
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator
from app.services.analysis_method_gate import evaluate_analysis_method
from app.services.financial_truth_locks import (
    acquire_active_account_mutation_lock,
    acquire_user_stock_fact_lock,
)


LOGGER = logging.getLogger(__name__)

# Image-only (scanned) pages yield an empty or near-empty native text layer,
# while genuine Value Line company pages carry thousands of characters. The
# threshold is deliberately minimal — it flags "effectively empty" pages (a
# text layer that cannot even hold one header line) as needing OCR, which is
# not yet implemented (see docs/BACKLOG.md).
MIN_PARSEABLE_PAGE_TEXT_CHARS = 20
VALUE_LINE_MAPPING_VERSION = "value-line-v2"


def _projection_json_value(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _canonical_projection_payload(fact: dict) -> dict:
    """Snapshot the exact approved fact shape before publication.

    This payload is immutable extraction lineage, not a product read model.  A
    database trigger compares every parsed ``metric_facts`` row to one of these
    entries so a source id alone cannot authorize a different stock, metric, or
    normalized value.
    """
    return {
        key: _projection_json_value(fact.get(key))
        for key in (
            "metric_key",
            "value_numeric",
            "value_text",
            "value_json",
            "unit",
            "currency",
            "period",
            "period_type",
            "period_end_date",
            "as_of_date",
        )
    }


def _projections_by_extraction_field(facts: list[dict]) -> dict[str, list[dict]]:
    projections: dict[str, list[dict]] = {}
    for fact in facts:
        field_key = fact.get("source_extraction_field_key")
        if not field_key:
            continue
        projections.setdefault(str(field_key), []).append(
            _canonical_projection_payload(fact)
        )
    return projections


def _canonicalize_page_facts(facts: list[dict]) -> list[dict]:
    """Choose one immutable publication per document-generation slot.

    Value Line can repeat a metric in a rounded summary and a more precise
    table.  The mapping specification's order remains the deterministic
    precedence, but a divergent earlier observation is carried in the chosen
    fact instead of being silently overwritten in the database.
    """
    selected: dict[tuple[object, ...], dict] = {}
    for raw_fact in facts:
        fact = dict(raw_fact)
        identity = (
            fact.get("metric_key"),
            fact.get("period_type"),
            fact.get("period_end_date"),
            fact.get("as_of_date"),
        )
        prior = selected.get(identity)
        if prior is not None:
            differing = any(
                prior.get(field) != fact.get(field)
                for field in (
                    "value_numeric",
                    "value_text",
                    "unit",
                )
            )
            if differing:
                selected_payload = fact.get("value_json")
                payload = (
                    dict(selected_payload)
                    if isinstance(selected_payload, dict)
                    else {"selected_value_json": selected_payload}
                )
                inherited = []
                prior_payload = prior.get("value_json")
                if isinstance(prior_payload, dict):
                    inherited = list(
                        prior_payload.get("mapping_conflicts") or []
                    )
                payload["mapping_conflicts"] = [
                    *inherited,
                    {
                        "source_extraction_field_key": prior.get(
                            "source_extraction_field_key"
                        ),
                        "value_numeric": prior.get("value_numeric"),
                        "value_text": prior.get("value_text"),
                        "unit": prior.get("unit"),
                        "resolution": "mapping_spec_later_path_precedence",
                    },
                ]
                fact["value_json"] = payload
                LOGGER.warning(
                    "Conflicting page observations for %s %s %s; "
                    "publishing later mapping path with conflict metadata",
                    fact.get("metric_key"),
                    fact.get("period_type"),
                    fact.get("period_end_date"),
                )
        selected[identity] = fact
    return list(selected.values())


def _approved_owner_earnings_facts(
    db: Session,
    *,
    stock_id: int,
    facts: list[dict],
    report_date: Optional[date],
) -> list[dict]:
    method = evaluate_analysis_method(
        db,
        stock_id=stock_id,
        analysis_kind="owner_earnings",
        cutoff=datetime.now(timezone.utc),
    )
    if method.state != "eligible" or method.method_id is None:
        LOGGER.info(
            "Owner Earnings not published for stock_id=%s: %s",
            stock_id,
            method.reason_code or method.state,
        )
        return []
    if not method.output_authorized:
        LOGGER.info(
            "Owner Earnings not published for stock_id=%s: approved evidence "
            "requirements do not yet authorize a canonical computation",
            stock_id,
        )
        return []
    evidence_keys = {
        "operating_cash_flow": "is.operating_cash_flow",
        "maintenance_capex": "owners_earnings.maintenance_capex_adjustment",
        "working_capital": "cf.change_in_working_capital",
        "stock_based_compensation": "is.stock_based_compensation",
        "acquisitions": "cf.acquisitions",
        "dilution": "equity.diluted_shares_outstanding",
    }
    present = {str(fact.get("metric_key") or "") for fact in facts}
    missing = [
        evidence
        for evidence in method.required_evidence
        if evidence_keys.get(evidence) not in present
    ]
    if missing:
        LOGGER.info(
            "Owner Earnings not published for stock_id=%s; missing evidence=%s",
            stock_id,
            ",".join(missing),
        )
        return []
    return build_owners_earnings_facts(
        facts,
        report_date=report_date,
        method_context={
            "policy_version": method.policy_version,
            "classification": method.classification,
            "classification_id": method.classification_id,
            "method_id": method.method_id,
            "required_evidence": list(method.required_evidence),
            "evidence_complete": True,
        },
    )


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
        self.mapping_spec = MappingSpec.load(
            Path(__file__).resolve().parents[2] / "docs" / "metric_facts_mapping_spec.yml"
        )
        if self.mapping_spec.spec.get("version") != 2:
            raise RuntimeError(
                "Value Line mapping spec version requires a database authority migration"
            )

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
        # Authentication may have loaded the user before an erasure committed.
        # Re-prove the account after taking the shared mutation lock, before a
        # private byte is written to the filesystem.
        if not acquire_active_account_mutation_lock(self.db, user_id=user_id):
            raise ValueError("Account is not active")

        # 1. Save file
        file_ext = Path(file.filename).suffix if file.filename else ".pdf"
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        saved_path: Optional[Path] = None
        try:
            saved_path_str = self.storage.save_upload_file(
                file, f"tmp/{unique_filename}"
            )
            saved_path = Path(saved_path_str)

            # 2. Register the blob while the active-account proof and lock are
            # still held. Once committed, account erasure owns any later
            # retirement/deletion of this document.
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
        except Exception:
            self.db.rollback()
            if saved_path is not None:
                try:
                    self.storage.discard_unregistered_upload(saved_path)
                except Exception:
                    LOGGER.exception(
                        "Failed to discard unregistered upload at %s", saved_path
                    )
            raise
        # The insert commit releases transaction-scoped locks. Reacquire before
        # parsing so an erasure that won the intervening race is observed.
        if not acquire_active_account_mutation_lock(self.db, user_id=user_id):
            raise ValueError("Account is not active")
        self.db.refresh(doc)
        if doc.lifecycle_state != "active":
            raise ValueError("Document became unavailable during account erasure")

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
                    text_extraction_method="native_text",
                    parse_generation=doc.current_parse_generation,
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

            company_pages = 0
            parsed_company_pages = 0
            requires_ocr_pages = 0

            for page_num, text, words in pages_data:
                # A page is the smallest publication unit.  Keep its identity,
                # extraction, canonical-fact, and calculated-fact writes in one
                # savepoint so a late mapping/calculation failure cannot expose
                # a half-published page through metric_facts.
                page_savepoint = self.db.begin_nested()
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
                        page_savepoint.rollback()
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
                        page_savepoint.rollback()
                        continue

                    company_pages += 1

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
                        page_savepoint.rollback()
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

                    facts, _, unmapped = self.mapping_spec.generate_facts(page_json)
                    facts.extend(
                        _approved_owner_earnings_facts(
                            self.db,
                            stock_id=stock.id,
                            facts=facts,
                            report_date=report_date,
                        )
                    )
                    facts = _canonicalize_page_facts(facts)
                    projections_by_field = _projections_by_extraction_field(facts)

                    extraction_ids_by_field: dict[str, int] = {}
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
                            parse_generation=doc.current_parse_generation,
                            resolved_stock_id=stock.id,
                            mapping_version=VALUE_LINE_MAPPING_VERSION,
                            canonical_projections_json=projections_by_field.get(
                                ext.field_key, []
                            ),
                        )
                        self.db.add(metric_record)
                        self.db.flush()
                        extraction_ids_by_field[ext.field_key] = metric_record.id

                    for path in sorted(unmapped):
                        LOGGER.warning(
                            "Unmapped page_json path: %s (document_id=%s page=%s)",
                            path,
                            doc.id,
                            page_num,
                        )
                    for fact in facts:
                        source_field_key = fact.get("source_extraction_field_key")
                        source_ref_id = extraction_ids_by_field.get(source_field_key)
                        if source_ref_id is None:
                            raise ValueError(
                                "mapped_fact_missing_exact_extraction_lineage:"
                                f"{fact['metric_key']}:{source_field_key or 'unknown'}"
                            )
                        self._insert_metric_fact_from_mapping(
                            user_id=user_id,
                            stock_id=stock.id,
                            metric_key=fact["metric_key"],
                            value_numeric=fact.get("value_numeric"),
                            value_text=fact.get("value_text"),
                            value_json=fact.get("value_json"),
                            unit=fact.get("unit"),
                            period_type=fact.get("period_type"),
                            period_end_date=fact.get("period_end_date"),
                            source_document_id=doc.id,
                            source_ref_id=source_ref_id,
                            parse_generation=doc.current_parse_generation,
                        )

                    self._run_calculated_metrics(user_id=user_id, stock_id=stock.id)
                    page_savepoint.commit()

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
                    if page_savepoint.is_active:
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
            
            self.db.commit()
            self.db.refresh(doc)
            
        except Exception as e:
            # Handle failure
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

        source_path = self.storage.get_file_path(doc.file_storage_key)
        resolved_source_path = source_path.resolve(strict=False)
        self.db.execute(
            sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"document-storage:{resolved_source_path}"},
        )
        source_hash = self.storage.sha256_file(source_path)
        canonical_path = self.storage.value_line_pdf_path(
            exchange=stock.exchange,
            ticker=stock.ticker,
            report_date=doc.report_date,
            content_hash=source_hash,
        )
        if canonical_path != resolved_source_path:
            self.db.execute(
                sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"document-storage:{canonical_path}"},
            )

        # Lock the entire candidate set in one globally ordered statement.
        # Account erasure locks document rows in the same id order, preventing
        # target/matching inverse-order deadlocks.
        candidate_docs = self.db.scalars(
            select(PdfDocument)
            .where(
                PdfDocument.lifecycle_state == "active",
                or_(
                    PdfDocument.id == doc.id,
                    and_(
                        PdfDocument.stock_id == stock.id,
                        PdfDocument.report_date == doc.report_date,
                        PdfDocument.source == "upload",
                    ),
                ),
            )
            .order_by(PdfDocument.id)
            .with_for_update()
        ).all()
        locked_doc = next((item for item in candidate_docs if item.id == doc.id), None)
        if locked_doc is None:
            return None
        doc = locked_doc

        archived_path = self.storage.archive_value_line_pdf(
            source_path,
            exchange=stock.exchange,
            ticker=stock.ticker,
            report_date=doc.report_date,
        )
        archived_path_str = str(archived_path)

        matching_docs = [
            item
            for item in candidate_docs
            if item.id != doc.id and item.file_storage_key != archived_path_str
        ]
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
        """Append one parse generation and switch the current projection atomically.

        Old pages, extractions, and parsed facts remain retained lineage. A
        failed reparse rolls back the candidate generation and leaves the
        previously current projection untouched.
        """
        self.db.execute(
            sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"account-erasure:{user_id}"},
        )
        doc = self.db.scalar(
            select(PdfDocument)
            .where(PdfDocument.id == document_id, PdfDocument.user_id == user_id)
            .with_for_update()
        )
        if not doc or doc.lifecycle_state != "active":
            raise ValueError("Document not found for user")

        next_generation = doc.current_parse_generation + 1
        saved_path = self.storage.get_file_path(doc.file_storage_key)
        try:
            extracted_pages = PdfExtractor.extract_pages_with_words(saved_path)
        except FileNotFoundError:
            extracted_pages = []

        if reextract_pdf:
            pages_data = extracted_pages
        else:
            cached_pages = self.db.scalars(
                select(DocumentPage)
                .where(
                    DocumentPage.document_id == doc.id,
                    DocumentPage.parse_generation == doc.current_parse_generation,
                )
                .order_by(DocumentPage.page_number)
            ).all()
            words_by_page = {
                page_num: words for page_num, _text, words in extracted_pages
            }
            text_by_page = {
                page_num: text for page_num, text, _words in extracted_pages
            }
            pages_data = [
                (
                    page.page_number,
                    page.page_text or text_by_page.get(page.page_number, ""),
                    words_by_page.get(page.page_number, []),
                )
                for page in cached_pages
            ]
            if not pages_data:
                pages_data = extracted_pages

        if not pages_data:
            self.db.rollback()
            raise ValueError("Reparse produced no available document pages")

        prior_facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.user_id == user_id,
                MetricFact.source_document_id == doc.id,
                MetricFact.source_type == "parsed",
                MetricFact.is_current.is_(True),
            )
        ).all()
        prior_manual_facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.user_id == user_id,
                MetricFact.source_document_id == doc.id,
                MetricFact.source_type == "manual",
                MetricFact.is_current.is_(True),
            )
        ).all()
        affected_slots = {
            (
                fact.stock_id,
                fact.metric_key,
                fact.period_type,
                fact.period_end_date,
                fact.as_of_date,
            )
            for fact in [*prior_facts, *prior_manual_facts]
        }

        is_multi_company_container = len(pages_data) > 1
        next_stock_id: Optional[int] = None
        next_report_date: Optional[date] = None
        next_identity_needs_review = False
        next_notes: list[str] = []
        company_pages = 0
        parsed_company_pages = 0
        affected_stock_ids: set[int] = {
            fact.stock_id for fact in [*prior_facts, *prior_manual_facts]
        }

        try:
            for page_num, page_text, _words in pages_data:
                self.db.add(
                    DocumentPage(
                        document_id=doc.id,
                        page_number=page_num,
                        page_text=page_text,
                        text_extraction_method="native_text",
                        parse_generation=next_generation,
                    )
                )
            self.db.flush()

            for page_num, page_text, words in pages_data:
                if len((page_text or "").strip()) < MIN_PARSEABLE_PAGE_TEXT_CHARS:
                    continue
                parser = ValueLineV1Parser(
                    page_text, page_words={1: words} if words else {}
                )
                identity_info = parser.extract_identity()
                if not _is_company_candidate(page_text, identity_info.ticker):
                    continue
                company_pages += 1
                try:
                    stock, needs_review, note = self.identity_service.resolve_stock(
                        identity_info
                    )
                except ValueError:
                    continue

                extractions = parser.parse()
                report_date = self._report_date_from_extractions(extractions)
                if report_date is None:
                    continue
                if next_report_date is None:
                    next_report_date = report_date
                elif next_report_date != report_date:
                    LOGGER.warning(
                        "Page %s report_date %s differs from document report_date %s "
                        "(document_id=%s); keeping the first-parsed date.",
                        page_num,
                        report_date,
                        next_report_date,
                        doc.id,
                    )
                if not is_multi_company_container:
                    next_stock_id = stock.id
                    next_identity_needs_review = needs_review
                if needs_review and note:
                    next_notes.append(f"[page {page_num}] {note}")

                page_json = build_value_line_page_json(
                    parser,
                    page_number=page_num,
                    results=extractions,
                )
                facts, _, unmapped = self.mapping_spec.generate_facts(page_json)
                facts.extend(
                    _approved_owner_earnings_facts(
                        self.db,
                        stock_id=stock.id,
                        facts=facts,
                        report_date=report_date,
                    )
                )
                facts = _canonicalize_page_facts(facts)
                projections_by_field = _projections_by_extraction_field(facts)
                extraction_ids_by_field: dict[str, int] = {}
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
                        parse_generation=next_generation,
                        resolved_stock_id=stock.id,
                        mapping_version=VALUE_LINE_MAPPING_VERSION,
                        canonical_projections_json=projections_by_field.get(
                            ext.field_key, []
                        ),
                    )
                    self.db.add(metric_record)
                    self.db.flush()
                    extraction_ids_by_field[ext.field_key] = metric_record.id

                for path in sorted(unmapped):
                    LOGGER.warning(
                        "Unmapped page_json path: %s (document_id=%s page=%s)",
                        path,
                        doc.id,
                        page_num,
                    )
                for fact in facts:
                    source_field_key = fact.get("source_extraction_field_key")
                    source_ref_id = extraction_ids_by_field.get(source_field_key)
                    if source_ref_id is None:
                        raise ValueError(
                            "mapped_fact_missing_exact_extraction_lineage:"
                            f"{fact['metric_key']}:{source_field_key or 'unknown'}"
                        )
                    self._insert_metric_fact_from_mapping(
                        user_id=user_id,
                        stock_id=stock.id,
                        metric_key=fact["metric_key"],
                        value_numeric=fact.get("value_numeric"),
                        value_text=fact.get("value_text"),
                        value_json=fact.get("value_json"),
                        unit=fact.get("unit"),
                        period_type=fact.get("period_type"),
                        period_end_date=fact.get("period_end_date"),
                        source_document_id=doc.id,
                        source_ref_id=source_ref_id,
                        parse_generation=next_generation,
                    )
                    affected_slots.add(
                        (
                            stock.id,
                            fact["metric_key"],
                            fact.get("period_type"),
                            fact.get("period_end_date"),
                            None,
                        )
                    )
                affected_stock_ids.add(stock.id)
                parsed_company_pages += 1

            if parsed_company_pages == 0:
                raise ValueError("Reparse produced no parseable company pages")

            doc.stock_id = None if is_multi_company_container else next_stock_id
            doc.report_date = next_report_date
            doc.identity_needs_review = next_identity_needs_review
            doc.notes = "\n".join(next_notes) or None
            doc.raw_text = "\n".join(page_text or "" for _, page_text, _ in pages_data)
            doc.current_parse_generation = next_generation
            doc.parse_status = (
                "parsed_partial"
                if parsed_company_pages < company_pages
                else "parsed"
            )
            self.db.add(doc)
            self.db.flush()

            self.db.execute(
                update(MetricFact)
                .where(
                    MetricFact.user_id == user_id,
                    MetricFact.source_document_id == doc.id,
                    MetricFact.source_type == "parsed",
                    MetricFact.parse_generation < next_generation,
                    MetricFact.is_current.is_(True),
                )
                .values(is_current=False)
            )
            # A manual correction is bound to the exact extraction generation
            # it reviewed.  Reparse retains it as audit lineage but requires a
            # new explicit user confirmation before it can override the new
            # parser generation (especially after an identity correction).
            self.db.execute(
                update(MetricFact)
                .where(
                    MetricFact.user_id == user_id,
                    MetricFact.source_document_id == doc.id,
                    MetricFact.source_type == "manual",
                    MetricFact.is_current.is_(True),
                )
                .values(is_current=False)
            )
            self.db.flush()

            for stock_id, metric_key, period_type, period_end_date, as_of_date in sorted(
                affected_slots,
                key=lambda slot: tuple("" if value is None else str(value) for value in slot),
            ):
                self._reconcile_parsed_fact_current_slot(
                    user_id=user_id,
                    stock_id=stock_id,
                    metric_key=metric_key,
                    period_type=period_type,
                    period_end_date=period_end_date,
                    as_of_date=as_of_date,
                )

            for stock_id in sorted(affected_stock_ids):
                self._run_calculated_metrics(user_id=user_id, stock_id=stock_id)

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        doc = self.db.get(PdfDocument, document_id)
        assert doc is not None
        return doc

    def _run_calculated_metrics(self, *, user_id: int, stock_id: int) -> None:
        ValueLineRatioCalculator(self.db).calculate_for_stock(user_id=user_id, stock_id=stock_id)
        PiotroskiFScoreCalculator(self.db).calculate_for_stock(user_id=user_id, stock_id=stock_id)

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
        parse_generation: int = 1,
        value_type_override: Optional[str] = None,
        force_numeric: bool = False,
    ) -> None:
        acquire_user_stock_fact_lock(
            self.db, user_id=user_id, stock_id=stock_id
        )
        value_type = value_type_override or self._infer_value_type(metric_key)
        norm_val, norm_unit = (None, None)
        if raw_value_text is not None and (force_numeric or metric_key not in self.NON_NUMERIC_KEYS):
            norm_val, norm_unit = Scaler.normalize(raw_value_text, value_type)

        value_json = self._build_value_json(parsed_value_json, raw_value_text, norm_val, norm_unit)
        value_text = raw_value_text if metric_key in self.NON_NUMERIC_KEYS else None

        values = dict(
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
            parse_generation=parse_generation,
            is_current=True,
        )
        self._insert_parsed_fact_idempotent(values)
        self.db.flush()
        self._reconcile_parsed_fact_current_slot(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            period_type=period_type,
            period_end_date=period_end_date,
            as_of_date=None,
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
        period_type: Optional[str],
        period_end_date: Optional[date],
        source_document_id: Optional[int],
        source_ref_id: int,
        parse_generation: int,
    ) -> None:
        acquire_user_stock_fact_lock(
            self.db, user_id=user_id, stock_id=stock_id
        )
        values = dict(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            value_json=value_json,  # type: ignore[arg-type]
            value_numeric=value_numeric,
            value_text=value_text,
            unit=unit,
            period_type=period_type,
            period_end_date=period_end_date,
            source_type="parsed",
            source_ref_id=source_ref_id,
            source_document_id=source_document_id,
            parse_generation=parse_generation,
            is_current=True,
        )
        self._insert_parsed_fact_idempotent(values)
        self.db.flush()
        self._reconcile_parsed_fact_current_slot(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            period_type=period_type,
            period_end_date=period_end_date,
            as_of_date=None,
        )

    def _insert_parsed_fact_idempotent(self, values: dict) -> None:
        """Insert an immutable parsed observation, or prove an exact retry.

        A uniqueness collision is never an update opportunity: the extraction
        and normalized value are retained lineage.  Exact retries are harmless;
        any divergent collision is an integrity failure that must start a new
        parse generation.
        """
        inserted_id = self.db.scalar(
            insert(MetricFact)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    "stock_id",
                    "metric_key",
                    "period_type",
                    "period_end_date",
                    "source_document_id",
                    "parse_generation",
                ],
                index_where=MetricFact.source_type == "parsed",
            )
            .returning(MetricFact.id)
        )
        if inserted_id is not None:
            return

        existing = self.db.scalar(
            select(MetricFact).where(
                MetricFact.stock_id == values["stock_id"],
                MetricFact.metric_key == values["metric_key"],
                MetricFact.period_type.is_not_distinct_from(
                    values["period_type"]
                ),
                MetricFact.period_end_date.is_not_distinct_from(
                    values["period_end_date"]
                ),
                MetricFact.source_document_id
                == values["source_document_id"],
                MetricFact.parse_generation == values["parse_generation"],
                MetricFact.source_type == "parsed",
            )
        )
        immutable_fields = (
            "user_id",
            "stock_id",
            "metric_key",
            "value_json",
            "value_numeric",
            "value_text",
            "unit",
            "period_type",
            "period_end_date",
            "source_type",
            "source_ref_id",
            "source_document_id",
            "parse_generation",
        )
        if existing is None or any(
            getattr(existing, field) != values.get(field)
            for field in immutable_fields
        ):
            raise ValueError(
                "parsed_fact_identity_conflict_requires_new_generation:"
                f"{values['metric_key']}:"
                f"existing_source_ref={getattr(existing, 'source_ref_id', None)}:"
                f"new_source_ref={values.get('source_ref_id')}:"
                f"existing_value={getattr(existing, 'value_numeric', None)}:"
                f"new_value={values.get('value_numeric')}"
            )

    def _reconcile_parsed_fact_current_slot(
        self,
        *,
        user_id: int,
        stock_id: int,
        metric_key: str,
        period_type: Optional[str],
        period_end_date: Optional[date],
        as_of_date: Optional[date],
    ) -> None:
        facts = self.db.scalars(
            select(MetricFact)
            .join(PdfDocument, PdfDocument.id == MetricFact.source_document_id)
            .where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.source_type == "parsed",
                MetricFact.period_type == period_type,
                MetricFact.period_end_date == period_end_date,
                MetricFact.as_of_date == as_of_date,
                MetricFact.parse_generation
                == PdfDocument.current_parse_generation,
                PdfDocument.lifecycle_state == "active",
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
