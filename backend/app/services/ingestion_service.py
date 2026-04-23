import logging
import re
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from fastapi import UploadFile

from app.models.artifacts import PdfDocument, DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.services.file_storage import FileStorageService
from app.services.identity_service import IdentityService
from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.v1_value_line.page_json import build_value_line_page_json
from app.ingestion.parsers.v1_value_line.semantics import (
    is_estimated_year,
    quarter_end_date_for_fiscal_year,
)
from app.ingestion.normalization.scaler import Scaler
from app.services.mapping_spec import MappingSpec
from app.services.owners_earnings import build_owners_earnings_facts


LOGGER = logging.getLogger(__name__)

class IngestionService:
    NON_NUMERIC_KEYS = {
        "report_date",
        "analyst_name",
        "analyst_commentary",
        "business_description",
        "annual_rates_of_change",
        "current_position_usd_millions",
        "financial_position_usd_millions",
        "quarterly_sales_usd_millions",
        "earnings_per_share",
        "quarterly_dividends_paid_per_share",
        "institutional_decisions",
        "company_financial_strength",
        "capital_structure_as_of",
        "market_cap_as_of",
        "pension_assets_as_of",
        "price_semantics_and_returns",
        "tables_time_series",
        "long_term_projection_year_range",
    }
    SKIP_FACT_KEYS = {
        "current_position_usd_millions",
        "financial_position_usd_millions",
        "quarterly_sales_usd_millions",
        "earnings_per_share",
        "quarterly_dividends_paid_per_share",
        "tables_time_series",
    }
    ANNUAL_TABLE_METRIC_KEYS = {
        "capital_spending_per_share_usd",
        "avg_annual_dividend_yield_pct",
        "depreciation_usd_millions",
        "net_profit_usd_millions",
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

            is_multi_company_container = len(pages_data) > 1
            if is_multi_company_container:
                doc.stock_id = None

            def is_company_page(text: str) -> bool:
                upper = (text or "").upper()
                return re.search(r"\bRECENT\s+(?:PRICE\s+)?\d", upper) is not None

            company_pages = 0
            parsed_company_pages = 0

            for page_num, text, words in pages_data:
                try:
                    parser = ValueLineV1Parser(text, page_words={1: words})
                    identity_info = parser.extract_identity()
                    is_company_candidate = bool(identity_info.ticker) or is_company_page(text)
                    if not is_company_candidate:
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
                    report_date = self._report_date_from_extractions(extractions)
                    if report_date is None:
                        raise ValueError("missing_commentary_date")
                    doc.report_date = report_date
                    page_json = build_value_line_page_json(
                        parser,
                        page_number=page_num,
                        results=extractions,
                    )

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

                    facts, _, unmapped = self.mapping_spec.generate_facts(page_json)
                    facts.extend(
                        build_owners_earnings_facts(
                            facts,
                            report_date=report_date,
                        )
                    )
                    for path in sorted(unmapped):
                        LOGGER.warning(
                            "Unmapped page_json path: %s (document_id=%s page=%s)",
                            path,
                            doc.id,
                            page_num,
                        )
                    for fact in facts:
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
                        )

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
                doc.parse_status = "failed"
            elif parsed_company_pages < company_pages:
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
            doc.parse_status = "failed"
            self.db.commit()
            self.db.refresh(doc)
            return doc

        is_multi_company_container = len(pages_data) > 1
        if is_multi_company_container:
            doc.stock_id = None
        doc.report_date = None

        def is_company_page(text: str) -> bool:
            upper = (text or "").upper()
            return re.search(r"\bRECENT\s+(?:PRICE\s+)?\d", upper) is not None

        company_pages = 0
        parsed_company_pages = 0

        for page_num, text, words in pages_data:
            parser = ValueLineV1Parser(text, page_words={1: words} if words else {})
            identity_info = parser.extract_identity()
            is_company_candidate = bool(identity_info.ticker) or is_company_page(text)
            if not is_company_candidate:
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
            doc.report_date = report_date
            page_json = build_value_line_page_json(
                parser,
                page_number=page_num,
                results=extractions,
            )
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

            facts, _, unmapped = self.mapping_spec.generate_facts(page_json)
            facts.extend(
                build_owners_earnings_facts(
                    facts,
                    report_date=report_date,
                )
            )
            for path in sorted(unmapped):
                LOGGER.warning(
                    "Unmapped page_json path: %s (document_id=%s page=%s)",
                    path,
                    doc.id,
                    page_num,
                )
            for fact in facts:
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
                )

            parsed_company_pages += 1

        if parsed_company_pages == 0:
            doc.parse_status = "failed"
        elif parsed_company_pages < company_pages:
            doc.parse_status = "parsed_partial"
        else:
            doc.parse_status = "parsed"

        self.db.commit()
        self.db.refresh(doc)
        return doc

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
        value_type_override: Optional[str] = None,
        force_numeric: bool = False,
    ) -> None:
        value_type = value_type_override or self._infer_value_type(metric_key)
        norm_val, norm_unit = (None, None)
        if raw_value_text is not None and (force_numeric or metric_key not in self.NON_NUMERIC_KEYS):
            norm_val, norm_unit = Scaler.normalize(raw_value_text, value_type)

        value_json = self._build_value_json(parsed_value_json, raw_value_text, norm_val, norm_unit)
        value_text = raw_value_text if metric_key in self.NON_NUMERIC_KEYS else None

        update_stmt = (
            update(MetricFact)
            .where(
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.source_type == "parsed",
                MetricFact.is_current.is_(True),
            )
            .values(is_current=False)
        )
        if period_type:
            update_stmt = update_stmt.where(
                (MetricFact.period_type == period_type) | (MetricFact.period_type.is_(None))
            )
        if period_end_date and not period_end_date_is_derived:
            update_stmt = update_stmt.where(MetricFact.period_end_date == period_end_date)
        self.db.execute(update_stmt)

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
            is_current=True,
        )
        insert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[
                "stock_id",
                "metric_key",
                "period_type",
                "period_end_date",
                "source_document_id",
            ],
            set_={
                "value_json": value_json,
                "value_numeric": norm_val,
                "value_text": value_text,
                "unit": norm_unit,
                "period_type": period_type,
                "period_end_date": period_end_date,
                "source_ref_id": source_ref_id,
                "is_current": True,
            },
        )
        self.db.execute(insert_stmt)
        self.db.flush()

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
    ) -> None:
        update_stmt = (
            update(MetricFact)
            .where(
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.source_type == "parsed",
                MetricFact.is_current.is_(True),
            )
            .values(is_current=False)
        )
        if period_type:
            update_stmt = update_stmt.where(MetricFact.period_type == period_type)
        if period_end_date:
            update_stmt = update_stmt.where(MetricFact.period_end_date == period_end_date)
        self.db.execute(update_stmt)

        insert_stmt = insert(MetricFact).values(
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
            source_ref_id=None,
            source_document_id=source_document_id,
            is_current=True,
        )
        insert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[
                "stock_id",
                "metric_key",
                "period_type",
                "period_end_date",
                "source_document_id",
            ],
            set_={
                "value_json": value_json,
                "value_numeric": value_numeric,
                "value_text": value_text,
                "unit": unit,
                "period_type": period_type,
                "period_end_date": period_end_date,
                "is_current": True,
            },
        )
        self.db.execute(insert_stmt)
        self.db.flush()

    def _expand_time_series_facts(self, ext, report_date: Optional[date]) -> list[dict]:
        if ext.parsed_value_json is None:
            return []
        if ext.field_key == "quarterly_sales_usd_millions":
            return self._expand_quarterly_series(
                ext.parsed_value_json,
                metric_key="quarterly_sales_usd_millions",
                report_date=report_date,
                value_type="currency",
                scale_token="mill",
            )
        if ext.field_key == "earnings_per_share":
            return self._expand_quarterly_series(
                ext.parsed_value_json,
                metric_key="earnings_per_share",
                report_date=report_date,
                value_type="currency",
                scale_token=None,
            )
        if ext.field_key == "quarterly_dividends_paid_per_share":
            return self._expand_quarterly_series(
                ext.parsed_value_json,
                metric_key="quarterly_dividends_paid_per_share",
                report_date=report_date,
                value_type="currency",
                scale_token=None,
            )
        if ext.field_key == "current_position_usd_millions":
            return self._expand_current_position_facts(ext.parsed_value_json)
        if ext.field_key == "financial_position_usd_millions":
            return self._expand_financial_position_facts(ext.parsed_value_json)
        if ext.field_key == "tables_time_series":
            return self._expand_annual_financials_facts(ext.parsed_value_json, report_date)
        return []

    def _expand_quarterly_series(
        self,
        rows: object,
        *,
        metric_key: str,
        report_date: Optional[date],
        value_type: str,
        scale_token: Optional[str],
    ) -> list[dict]:
        if not isinstance(rows, list):
            return []
        month_order = None
        fiscal_year_end_month = None
        if rows and isinstance(rows[0], dict):
            month_order = rows[0].get("quarter_month_order")
            fiscal_year_end_month = rows[0].get("fiscal_year_end_month")
        facts: list[dict] = []
        quarter_map = (("q1", 1), ("q2", 2), ("q3", 3), ("q4", 4))
        for row in rows:
            year = row.get("calendar_year")
            if not year:
                continue
            is_estimate = is_estimated_year(
                int(year),
                report_date.isoformat() if report_date else None,
                fiscal_year_end_month if isinstance(fiscal_year_end_month, int) else None,
            )
            fact_nature = "estimate" if is_estimate else "actual"
            for key, quarter_num in quarter_map:
                value = row.get(key)
                if value is None:
                    continue
                raw_value_text = self._format_raw_value(value, value_type, scale_token)
                period_end = quarter_end_date_for_fiscal_year(int(year), quarter_num, month_order)
                if not period_end:
                    continue
                facts.append(
                    {
                        "metric_key": metric_key,
                        "raw_value_text": raw_value_text,
                        "parsed_value_json": {"fact_nature": fact_nature},
                        "period_type": "Q",
                        "period_end_date": date.fromisoformat(period_end),
                        "value_type": value_type,
                    }
                )
            full_year = row.get("full_year")
            if full_year is None:
                continue
            parsed_value_json = {"fact_nature": fact_nature}
            raw_value_text = self._format_raw_value(full_year, value_type, scale_token)
            facts.append(
                {
                    "metric_key": metric_key,
                    "raw_value_text": raw_value_text,
                    "parsed_value_json": parsed_value_json,
                    "period_type": "FY",
                    "period_end_date": date(int(year), 12, 31),
                    "value_type": value_type,
                }
            )
        return facts

    def _expand_current_position_facts(self, parsed: object) -> list[dict]:
        if not isinstance(parsed, dict):
            return []
        years = parsed.get("years", [])
        if not isinstance(years, list):
            return []
        assets_map = {
            "cash_assets": "cash_assets",
            "receivables": "receivables",
            "inventory_lifo": "inventory_lifo",
            "other_current_assets": "other_current_assets",
            "current_assets_total": "total_current_assets",
        }
        liab_map = {
            "accounts_payable": "accounts_payable",
            "debt_due": "debt_due",
            "other_current_liabilities": "other_current_liabilities",
            "current_liabilities_total": "total_current_liabilities",
        }
        facts: list[dict] = []
        for idx, label in enumerate(years):
            period_end_date = self._year_end_date(label)
            period_type = (
                "FY"
                if isinstance(label, int) or (isinstance(label, str) and label.isdigit())
                else "AS_OF"
            )
            if period_end_date is None:
                continue
            for key, suffix in assets_map.items():
                series = parsed.get(key)
                if not isinstance(series, list) or idx >= len(series):
                    continue
                value = series[idx]
                if value is None:
                    continue
                facts.append(
                    {
                        "metric_key": f"current_position_{suffix}_usd_millions",
                        "raw_value_text": self._format_raw_value(value, "currency", "mill"),
                        "parsed_value_json": None,
                        "period_type": period_type,
                        "period_end_date": period_end_date,
                        "value_type": "currency",
                    }
                )
            for key, suffix in liab_map.items():
                series = parsed.get(key)
                if not isinstance(series, list) or idx >= len(series):
                    continue
                value = series[idx]
                if value is None:
                    continue
                facts.append(
                    {
                        "metric_key": f"current_position_{suffix}_usd_millions",
                        "raw_value_text": self._format_raw_value(value, "currency", "mill"),
                        "parsed_value_json": None,
                        "period_type": period_type,
                        "period_end_date": period_end_date,
                        "value_type": "currency",
                    }
                )
        return facts

    def _expand_financial_position_facts(self, parsed: object) -> list[dict]:
        if not isinstance(parsed, dict):
            return []
        years = parsed.get("years", [])
        if not isinstance(years, list):
            return []
        assets = parsed.get("assets", {}) if isinstance(parsed.get("assets"), dict) else {}
        liabilities = parsed.get("liabilities", {}) if isinstance(parsed.get("liabilities"), dict) else {}
        assets_map = {
            "bonds": "assets_bonds",
            "stocks": "assets_stocks",
            "other": "assets_other",
            "total_assets": "assets_total",
        }
        liabilities_map = {
            "unearned_premiums": "liabilities_unearned_premiums",
            "reserves": "liabilities_reserves",
            "other": "liabilities_other",
            "total_liabilities": "liabilities_total",
        }
        facts: list[dict] = []
        for idx, label in enumerate(years):
            period_end_date = self._year_end_date(label)
            period_type = (
                "FY"
                if isinstance(label, int) or (isinstance(label, str) and label.isdigit())
                else "AS_OF"
            )
            if period_end_date is None:
                continue
            for key, suffix in assets_map.items():
                series = assets.get(key)
                if not isinstance(series, list) or idx >= len(series):
                    continue
                value = series[idx]
                if value is None:
                    continue
                facts.append(
                    {
                        "metric_key": f"financial_position_{suffix}_usd_millions",
                        "raw_value_text": self._format_raw_value(value, "currency", "mill"),
                        "parsed_value_json": None,
                        "period_type": period_type,
                        "period_end_date": period_end_date,
                        "value_type": "currency",
                    }
                )
            for key, suffix in liabilities_map.items():
                series = liabilities.get(key)
                if not isinstance(series, list) or idx >= len(series):
                    continue
                value = series[idx]
                if value is None:
                    continue
                facts.append(
                    {
                        "metric_key": f"financial_position_{suffix}_usd_millions",
                        "raw_value_text": self._format_raw_value(value, "currency", "mill"),
                        "parsed_value_json": None,
                        "period_type": period_type,
                        "period_end_date": period_end_date,
                        "value_type": "currency",
                    }
                )
        return facts

    def _expand_annual_financials_facts(self, parsed: object, report_date: Optional[date]) -> list[dict]:
        if not isinstance(parsed, dict):
            return []
        annual = parsed.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030", {})
        if not isinstance(annual, dict):
            return []
        years = annual.get("years", [])
        if not isinstance(years, list) or not years:
            return []

        per_share = annual.get("per_share", {}) if isinstance(annual.get("per_share"), dict) else {}
        valuation = annual.get("valuation", {}) if isinstance(annual.get("valuation"), dict) else {}
        income_statement = annual.get("income_statement_usd_millions", {}) if isinstance(
            annual.get("income_statement_usd_millions"), dict
        ) else {}
        balance_sheet = annual.get("balance_sheet_and_returns_usd_millions", {}) if isinstance(
            annual.get("balance_sheet_and_returns_usd_millions"), dict
        ) else {}

        insurance_layout = (
            "pc_prem_earned_per_share_usd" in per_share or "pc_premiums_earned" in income_statement
        )
        ratio_keys = {
            "loss_to_prem_earned_pct",
            "expense_to_prem_written",
            "underwriting_margin_pct",
            "income_tax_rate_pct",
            "inv_inc_to_total_investments_pct",
            "return_on_shareholders_equity_pct",
            "retained_to_common_equity_pct",
            "all_dividends_to_net_profit_pct",
        }
        percent_like = {"expense_to_prem_written"}

        estimate_years = {
            int(year)
            for year in annual.get("estimate_years", [])
            if isinstance(year, int) or (isinstance(year, str) and str(year).isdigit())
        }
        if not estimate_years and years:
            estimate_years = {int(years[-1])}
        facts: list[dict] = []

        def append_fact(
            *,
            metric_key: str,
            value: float,
            value_type: str,
            scale_token: Optional[str],
            year: int,
            is_estimate: bool,
        ) -> None:
            if value is None:
                return
            parsed_value_json = {"fact_nature": "estimate" if is_estimate else "actual"}
            raw_value_text = self._format_raw_value(value, value_type, scale_token)
            facts.append(
                {
                    "metric_key": metric_key,
                    "raw_value_text": raw_value_text,
                    "parsed_value_json": parsed_value_json,
                    "period_type": "FY",
                    "period_end_date": date(int(year), 12, 31),
                    "value_type": value_type,
                }
            )

        def metric_key_with_millions(key: str) -> str:
            if key.endswith("_usd_millions") or key.endswith("_usd"):
                return key
            return f"{key}_usd_millions"

        def percent_value_type(key: str) -> str:
            if insurance_layout and key in ratio_keys:
                return "ratio"
            return "percent"

        for key, values in per_share.items():
            if key == "notes" or not isinstance(values, list):
                continue
            for idx, year in enumerate(years):
                if idx >= len(values):
                    continue
                value = values[idx]
                if value is None:
                    continue
                if key == "common_shares_outstanding_millions":
                    append_fact(
                        metric_key=key,
                        value=value,
                        value_type="number",
                        scale_token="mill",
                        year=year,
                        is_estimate=year in estimate_years,
                    )
                else:
                    append_fact(
                        metric_key=key,
                        value=value,
                        value_type="currency",
                        scale_token=None,
                        year=year,
                        is_estimate=year in estimate_years,
                    )

        for key, values in valuation.items():
            if not isinstance(values, list):
                continue
            for idx, year in enumerate(years):
                if idx >= len(values):
                    continue
                value = values[idx]
                if value is None:
                    continue
                value_type = (
                    "ratio"
                    if key in ratio_keys
                    else percent_value_type(key) if key.endswith("_pct") else "ratio"
                )
                append_fact(
                    metric_key=key,
                    value=value,
                    value_type=value_type,
                    scale_token=None,
                    year=year,
                    is_estimate=year in estimate_years,
                )

        for key, values in income_statement.items():
            if not isinstance(values, list):
                continue
            for idx, year in enumerate(years):
                if idx >= len(values):
                    continue
                value = values[idx]
                if value is None:
                    continue
                if key.endswith("_pct") or key in percent_like:
                    value_type = percent_value_type(key)
                    metric_key = key
                    scale_token = None
                else:
                    value_type = "currency"
                    metric_key = metric_key_with_millions(key)
                    scale_token = "mill"
                append_fact(
                    metric_key=metric_key,
                    value=value,
                    value_type=value_type,
                    scale_token=scale_token,
                    year=year,
                    is_estimate=year in estimate_years,
                )

        for key, values in balance_sheet.items():
            if not isinstance(values, list):
                continue
            for idx, year in enumerate(years):
                if idx >= len(values):
                    continue
                value = values[idx]
                if value is None:
                    continue
                if key.endswith("_pct") or key in percent_like:
                    value_type = percent_value_type(key)
                    metric_key = key
                    scale_token = None
                else:
                    value_type = "currency"
                    metric_key = metric_key_with_millions(key)
                    scale_token = "mill"
                append_fact(
                    metric_key=metric_key,
                    value=value,
                    value_type=value_type,
                    scale_token=scale_token,
                    year=year,
                    is_estimate=year in estimate_years,
                )

        return facts
