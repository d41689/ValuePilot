from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Body
from sqlalchemy import select, func, update
import yaml
from app.models.artifacts import DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.api.deps import SessionDep, CurrentUser
from app.ingestion.normalization.scaler import Scaler
from app.ingestion.parsers.v1_value_line.evidence import parse_rating_event_notes
from app.ingestion.parsers.v1_value_line.page_json import (
    _build_annual_financials as _build_value_line_annual_financials,
    _build_annual_rates as _build_value_line_annual_rates,
    _build_capital_structure as _build_value_line_capital_structure,
    _build_current_position as _build_value_line_current_position,
    _build_quarterly_block as _build_value_line_quarterly_block,
    _build_quarterly_block_or_none as _build_value_line_quarterly_block_or_none,
    _build_quarterly_dividends_paid as _build_value_line_quarterly_dividends_paid,
    _build_total_return as _build_value_line_total_return,
    _quarter_month_order as _value_line_quarter_month_order,
)
from app.services.active_report_resolver import resolve_active_reports
from app.services.document_dedupe_service import DocumentDedupeService
from app.services.ingestion_service import IngestionService
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator
from app.models.artifacts import PdfDocument

router = APIRouter()
VALUE_LINE_TAXONOMY_PATH = next(
    (
        parent / "docs" / "value_line_field_taxonomy.yml"
        for parent in Path(__file__).resolve().parents
        if (parent / "docs" / "value_line_field_taxonomy.yml").exists()
    ),
    Path(__file__).resolve().parents[4] / "docs" / "value_line_field_taxonomy.yml",
)

DOCUMENT_REVIEW_GROUPS = [
    ("identity_header", "Identity & Header"),
    ("ratings_quality", "Ratings & Quality"),
    ("target_projection", "Target & Projection"),
    ("capital_structure", "Capital Structure"),
    ("annual_rates", "Annual Rates"),
    ("quarterly_tables", "Quarterly Tables"),
    ("annual_financials", "Annual Financials"),
    ("institutional_decisions", "Institutional Decisions"),
    ("narrative", "Narrative"),
]

DOCUMENT_REVIEW_LABELS = {
    "mkt.price": "Price",
    "mkt.market_cap": "Market Cap",
    "snapshot.pe": "P/E Ratio",
    "snapshot.relative_pe": "Relative P/E",
    "snapshot.dividend_yield": "Dividend Yield",
    "val.pe": "P/E Ratio",
    "val.pe_trailing": "P/E Trailing",
    "val.pe_median": "P/E Median",
    "val.relative_pe": "Relative P/E",
    "val.dividend_yield": "Dividend Yield",
    "rating.timeliness": "Timeliness",
    "rating.safety": "Safety",
    "rating.technical": "Technical",
    "rating.beta": "Beta",
}

DOCUMENT_REVIEW_SUMMARY_FIELDS = [
    ("recent_price", "mkt.price", "Recent Price"),
    ("pe_ratio", "val.pe", "P/E Ratio"),
    ("pe_trailing", "val.pe_trailing", "P/E Trailing"),
    ("pe_median", "val.pe_median", "P/E Median"),
    ("relative_pe_ratio", "val.relative_pe", "Relative P/E Ratio"),
    ("dividend_yield", "val.dividend_yield", "Div'd Yld"),
]

DOCUMENT_REVIEW_CAPITAL_STRUCTURE_FIELDS = {
    "capital_structure_as_of",
    "total_debt",
    "debt_due_in_5_years",
    "lt_debt",
    "lt_interest",
    "debt_percent_of_capital",
    "leases_uncapitalized_annual_rentals",
    "pension_assets",
    "pension_assets_as_of",
    "pension_obligations",
    "pension_plan",
    "preferred_stock",
    "preferred_dividend",
    "common_stock_shares_outstanding",
    "shares_outstanding",
    "market_cap",
    "market_cap_as_of",
}

DOCUMENT_REVIEW_CURRENT_POSITION_FIELDS = {
    "current_position_usd_millions",
}

DOCUMENT_REVIEW_FINANCIAL_POSITION_FIELDS = {
    "financial_position_usd_millions",
}

DOCUMENT_REVIEW_ANNUAL_FINANCIALS_FIELDS = {
    "tables_time_series",
}

DOCUMENT_REVIEW_ANNUAL_RATES_FIELDS = {
    "annual_rates_of_change",
}

DOCUMENT_REVIEW_QUARTERLY_TABLE_FIELDS = {
    "quarterly_sales_usd_millions",
    "earnings_per_share",
    "quarterly_dividends_paid_per_share",
}


@router.get("", response_model=list[dict])
def list_documents(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    List documents for the authenticated user with page counts and company summary.
    """
    user_id = current_user.id

    docs = session.scalars(
        select(PdfDocument)
        .where(PdfDocument.user_id == user_id)
        .order_by(PdfDocument.upload_time.desc())
    ).all()
    if not docs:
        return []

    doc_ids = [doc.id for doc in docs]

    page_counts = dict(
        session.execute(
            select(DocumentPage.document_id, func.count(DocumentPage.id))
            .where(DocumentPage.document_id.in_(doc_ids))
            .group_by(DocumentPage.document_id)
        ).all()
    )

    parsed_page_counts = dict(
        session.execute(
            select(
                MetricExtraction.document_id,
                func.count(func.distinct(MetricExtraction.page_number)),
            )
            .where(MetricExtraction.document_id.in_(doc_ids))
            .group_by(MetricExtraction.document_id)
        ).all()
    )

    parser_versions = dict(
        session.execute(
            select(MetricExtraction.document_id, func.max(MetricExtraction.parser_version))
            .where(MetricExtraction.document_id.in_(doc_ids))
            .group_by(MetricExtraction.document_id)
        ).all()
    )

    companies_map: dict[int, dict[int, dict[str, str]]] = {}
    company_rows = session.execute(
        select(MetricFact.source_document_id, Stock.id, Stock.ticker, Stock.company_name)
        .join(Stock, Stock.id == MetricFact.stock_id)
        .where(
            MetricFact.source_document_id.in_(doc_ids),
            MetricFact.source_type == "parsed",
        )
        .distinct()
    ).all()
    for doc_id, stock_id, ticker, company_name in company_rows:
        if doc_id is None:
            continue
        companies_map.setdefault(doc_id, {})[stock_id] = {
            "ticker": ticker,
            "company_name": company_name,
        }

    # Ensure single-stock docs still show company even if no parsed facts exist.
    stock_ids = [doc.stock_id for doc in docs if doc.stock_id]
    stock_lookup = {
        stock.id: stock
        for stock in session.scalars(select(Stock).where(Stock.id.in_(stock_ids))).all()
    }
    active_reports_by_stock = resolve_active_reports(session, document_ids=doc_ids)
    active_tickers_by_doc: dict[int, list[str]] = {}
    for stock_id, active in active_reports_by_stock.items():
        stock = stock_lookup.get(stock_id)
        if stock is None:
            stock = session.get(Stock, stock_id)
            if stock is None:
                continue
            stock_lookup[stock_id] = stock
        active_tickers_by_doc.setdefault(active.document_id, []).append(stock.ticker)

    output = []
    for doc in docs:
        companies_dict = companies_map.get(doc.id, {})
        if doc.stock_id and doc.stock_id in stock_lookup and doc.stock_id not in companies_dict:
            stock = stock_lookup[doc.stock_id]
            companies_dict[doc.stock_id] = {
                "ticker": stock.ticker,
                "company_name": stock.company_name,
            }

        parser_version = parser_versions.get(doc.id)
        if parser_version == "v1":
            template_label = "Value Line (v1)"
        elif doc.source:
            template_label = doc.source
        else:
            template_label = "Unknown"

        companies = sorted(companies_dict.values(), key=lambda c: c["ticker"])
        active_for_tickers = sorted(active_tickers_by_doc.get(doc.id, []))
        output.append(
            {
                "id": doc.id,
                "file_name": doc.file_name,
                "source": doc.source,
                "template_label": template_label,
                "parse_status": doc.parse_status,
                "upload_time": doc.upload_time.isoformat() if doc.upload_time else None,
                "report_date": doc.report_date.isoformat() if doc.report_date else None,
                "page_count": page_counts.get(doc.id, 0),
                "parsed_page_count": parsed_page_counts.get(doc.id, 0),
                "companies": companies,
                "company_count": len(companies),
                "is_active_report": bool(active_for_tickers),
                "active_for_tickers": active_for_tickers,
            }
        )

    return sorted(
        output,
        key=lambda item: (
            _document_sort_ticker(item),
            item["report_date"] or "",
            item["id"],
        ),
    )

@router.post("/upload", response_model=dict)
def upload_document(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """
    Upload a PDF document, save it, and extract text.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    user_id = current_user.id
    service = IngestionService(session)
    try:
        doc, page_reports = service.process_upload(user_id, file)
        return {
            "id": doc.id,
            "document_id": doc.id,
            "file_name": doc.file_name,
            "status": doc.parse_status,
            "page_count": len(doc.pages),
            "page_reports": page_reports,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@router.post("/{document_id}/reparse", response_model=dict)
def reparse_document(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    document_id: int,
    reextract_pdf: bool = Query(False, description="Re-extract text from stored PDF before parsing"),
) -> Any:
    """
    Re-run parsing for an existing document ID.
    Inserts new metric_extractions and new parsed metric_facts (previous parsed facts are deactivated).
    """
    user_id = current_user.id

    doc = session.get(PdfDocument, document_id)
    if not doc or doc.user_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found")

    service = IngestionService(session)
    try:
        doc = service.reparse_existing_document(user_id=user_id, document_id=document_id, reextract_pdf=reextract_pdf)
        return {"id": doc.id, "status": doc.parse_status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reparse failed: {str(e)}")


@router.delete("/{document_id}", response_model=dict)
def delete_document(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    document_id: int,
) -> Any:
    result = DocumentDedupeService(session).delete_document(
        user_id=current_user.id,
        document_id=document_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@router.get("/compare", response_model=dict)
def compare_documents(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    left_document_id: int = Query(..., description="Left-hand document id"),
    right_document_id: int = Query(..., description="Right-hand document id"),
) -> Any:
    user_id = current_user.id

    left_doc = session.get(PdfDocument, left_document_id)
    right_doc = session.get(PdfDocument, right_document_id)
    if not left_doc or left_doc.user_id != user_id:
        raise HTTPException(status_code=404, detail="Left document not found")
    if not right_doc or right_doc.user_id != user_id:
        raise HTTPException(status_code=404, detail="Right document not found")

    left_stock_ids = _document_stock_ids(session, left_doc)
    right_stock_ids = _document_stock_ids(session, right_doc)
    shared_stock_ids = sorted(left_stock_ids & right_stock_ids)
    if not shared_stock_ids:
        raise HTTPException(status_code=400, detail="Documents do not share a parsed company")

    stock_lookup = {
        stock.id: stock
        for stock in session.scalars(select(Stock).where(Stock.id.in_(shared_stock_ids))).all()
    }
    taxonomy = _load_value_line_taxonomy()

    left_fact_entries = _document_compare_fact_entries(session, left_doc.id, shared_stock_ids, stock_lookup)
    right_fact_entries = _document_compare_fact_entries(session, right_doc.id, shared_stock_ids, stock_lookup)
    left_evidence_entries = _document_compare_evidence_entries(session, left_doc, taxonomy)
    right_evidence_entries = _document_compare_evidence_entries(session, right_doc, taxonomy)

    sections = _build_document_compare_sections(
        left_fact_entries=left_fact_entries,
        right_fact_entries=right_fact_entries,
        left_evidence_entries=left_evidence_entries,
        right_evidence_entries=right_evidence_entries,
    )

    return {
        "left_document": {
            "id": left_doc.id,
            "file_name": left_doc.file_name,
            "report_date": _iso_date(left_doc.report_date),
        },
        "right_document": {
            "id": right_doc.id,
            "file_name": right_doc.file_name,
            "report_date": _iso_date(right_doc.report_date),
        },
        "shared_tickers": sorted(
            stock_lookup[stock_id].ticker
            for stock_id in shared_stock_ids
            if stock_id in stock_lookup
        ),
        "sections": sections,
    }


@router.get("/{document_id}/raw_text", response_model=dict)
def read_document_raw_text(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    document_id: int,
) -> Any:
    """
    Get raw text for a document. Falls back to concatenated page text if raw_text is empty.
    """
    user_id = current_user.id

    doc = session.get(PdfDocument, document_id)
    if not doc or doc.user_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found")

    raw_text = doc.raw_text
    if raw_text is None:
        pages = session.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == doc.id)
            .order_by(DocumentPage.page_number.asc())
        ).all()
        raw_text = "\n".join([p.page_text or "" for p in pages])

    return {"document_id": doc.id, "raw_text": raw_text or ""}


@router.get("/{document_id}/evidence", response_model=dict)
def read_document_evidence(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    document_id: int,
) -> Any:
    """
    Get evidence-only Value Line fields for a document from the audit-layer extractions.
    """
    user_id = current_user.id

    doc = session.get(PdfDocument, document_id)
    if not doc or doc.user_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found")

    taxonomy = _load_value_line_taxonomy()
    evidence_reads = taxonomy.get("evidence_reads", {})
    if not evidence_reads:
        return {"document_id": doc.id, "evidence": []}

    field_keys = sorted(
        {
            str(config["extraction_field_key"])
            for config in evidence_reads.values()
            if config.get("source") == "metric_extractions" and config.get("extraction_field_key")
        }
    )
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(field_keys),
        )
    ).all()
    latest_by_field = _latest_extractions_by_field(extractions)
    mapping_semantics = taxonomy.get("mapping_semantics", {})

    evidence: list[dict[str, Any]] = []
    for mapping_id, config in evidence_reads.items():
        field_key = config.get("extraction_field_key")
        if not isinstance(field_key, str):
            continue
        extraction = latest_by_field.get(field_key)
        if extraction is None:
            continue

        value_text, value_json = _resolve_evidence_value(config, extraction)
        if value_text is None and value_json is None:
            continue

        period_end_date = _resolve_evidence_period_end(config, doc, extraction, value_json)
        semantics = mapping_semantics.get(mapping_id, {})

        evidence.append(
            {
                "mapping_id": mapping_id,
                "metric_key": config.get("metric_key"),
                "fact_nature": semantics.get("fact_nature"),
                "storage_role": semantics.get("storage_role"),
                "source": config.get("source"),
                "field_key": extraction.field_key,
                "extraction_id": extraction.id,
                "page_number": extraction.page_number,
                "period_type": config.get("period_type"),
                "period_end_date": period_end_date,
                "value_text": value_text,
                "value_json": value_json,
                "original_text_snippet": extraction.original_text_snippet,
            }
        )

    return {"document_id": doc.id, "evidence": evidence}


@router.get("/{document_id}/review", response_model=dict)
def read_document_review(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    document_id: int,
) -> Any:
    """
    Return a Value Line report-oriented review payload for one document.
    """
    doc = session.get(PdfDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    facts = _document_review_selected_facts(session, doc)
    stock_ids = sorted({fact.stock_id for fact in facts if fact.stock_id is not None})
    if doc.stock_id:
        stock_ids.append(doc.stock_id)
    stock_lookup = {
        stock.id: stock
        for stock in session.scalars(select(Stock).where(Stock.id.in_(set(stock_ids)))).all()
    } if stock_ids else {}
    document_stock = stock_lookup.get(doc.stock_id) if doc.stock_id else None

    lineage_by_fact_id = _document_review_lineage_by_fact_id(session, doc, facts)

    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _label in DOCUMENT_REVIEW_GROUPS}
    for fact in facts:
        group_key = _document_review_group_key(fact)
        lineage = lineage_by_fact_id.get(fact.id)
        item = _document_review_item(fact, stock_lookup, lineage)
        grouped[group_key].append(item)

    groups = []
    for group_key, label in DOCUMENT_REVIEW_GROUPS:
        items = grouped[group_key]
        if not items:
            continue
        groups.append(
            {
                "key": group_key,
                "label": label,
                "items": sorted(
                    items,
                    key=lambda item: (
                        item.get("period_end_date") or item.get("as_of_date") or "",
                        item.get("metric_key") or "",
                        item.get("fact_id") or 0,
                    ),
                ),
            }
        )

    return {
        "document": {
            "id": doc.id,
            "file_name": doc.file_name,
            "ticker": document_stock.ticker if document_stock else None,
            "exchange": document_stock.exchange if document_stock else None,
            "company_name": document_stock.company_name if document_stock else None,
            "report_date": _iso_date(doc.report_date),
        },
        "summary": _document_review_summary(facts, document_stock.id if document_stock else None),
        "annual_rates": _document_review_annual_rates(session, doc),
        "quarterly_sales": _document_review_quarterly_sales(session, doc),
        "earnings_per_share": _document_review_earnings_per_share(session, doc),
        "quarterly_dividends_paid": _document_review_quarterly_dividends_paid(session, doc),
        "annual_financials": _document_review_annual_financials(session, doc),
        "total_return": _document_review_total_return(session, doc),
        "capital_structure": _document_review_capital_structure(session, doc),
        "current_position": _document_review_current_position(session, doc),
        "financial_position": _document_review_financial_position(session, doc),
        "groups": groups,
    }


@router.post("/{document_id}/review/facts/{fact_id}/corrections", response_model=dict)
def correct_document_review_fact(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    document_id: int,
    fact_id: int,
    payload: dict = Body(...),
) -> Any:
    """
    Insert a manual current fact for a reviewed document value.
    """
    doc = session.get(PdfDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    fact = session.get(MetricFact, fact_id)
    if not fact or fact.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Fact not found")
    if not _document_review_fact_belongs_to_document(session, doc, fact):
        raise HTTPException(status_code=404, detail="Fact not found")

    raw_value = payload.get("value")
    if raw_value is None or str(raw_value).strip() == "":
        raise HTTPException(status_code=400, detail={"value": "Correction value is required"})
    raw_text = str(raw_value).strip()
    unit_hint = payload.get("unit")
    note = payload.get("note")

    value_numeric, normalized_unit, value_text = _normalize_review_correction(
        raw_text=raw_text,
        unit_hint=str(unit_hint).strip() if unit_hint else None,
        fact=fact,
    )
    if value_numeric is None and value_text is None:
        raise HTTPException(
            status_code=400,
            detail={
                "value": "Correction value could not be normalized",
                "metric_key": fact.metric_key,
            },
        )

    session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == current_user.id,
            MetricFact.stock_id == fact.stock_id,
            MetricFact.metric_key == fact.metric_key,
            MetricFact.period_type == fact.period_type,
            MetricFact.period_end_date == fact.period_end_date,
            MetricFact.as_of_date == fact.as_of_date,
            MetricFact.is_current.is_(True),
        )
        .values(is_current=False)
    )

    value_json = {
        "raw": raw_text,
        "correction": True,
        "corrected_from_fact_id": fact.id,
    }
    if note:
        value_json["note"] = str(note)

    manual_fact = MetricFact(
        user_id=current_user.id,
        stock_id=fact.stock_id,
        metric_key=fact.metric_key,
        value_json=value_json,
        value_numeric=value_numeric,
        value_text=value_text,
        unit=normalized_unit or fact.unit,
        currency=fact.currency,
        period=fact.period,
        period_type=fact.period_type,
        period_end_date=fact.period_end_date,
        as_of_date=fact.as_of_date,
        source_document_id=doc.id,
        source_type="manual",
        source_ref_id=fact.source_ref_id,
        is_current=True,
    )
    session.add(manual_fact)
    session.flush()
    ValueLineRatioCalculator(session).calculate_for_stock(user_id=current_user.id, stock_id=fact.stock_id)
    PiotroskiFScoreCalculator(session).calculate_for_stock(user_id=current_user.id, stock_id=fact.stock_id)
    session.commit()
    session.refresh(manual_fact)

    return {
        "status": "success",
        "fact_id": manual_fact.id,
        "normalized_value": manual_fact.value_numeric,
        "unit": manual_fact.unit,
    }


@lru_cache(maxsize=1)
def _load_value_line_taxonomy() -> dict[str, Any]:
    with VALUE_LINE_TAXONOMY_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _latest_extractions_by_field(
    extractions: list[MetricExtraction],
) -> dict[str, MetricExtraction]:
    latest: dict[str, MetricExtraction] = {}
    for extraction in extractions:
        current = latest.get(extraction.field_key)
        if current is None or _extraction_sort_key(extraction) > _extraction_sort_key(current):
            latest[extraction.field_key] = extraction
    return latest


def _extraction_sort_key(extraction: MetricExtraction) -> tuple[int, int]:
    return (_parser_version_rank(extraction.parser_version), extraction.id)


def _parser_version_rank(version: Optional[str]) -> int:
    if not version:
        return -1
    match = re.search(r"(\d+)$", version)
    return int(match.group(1)) if match else -1


def _resolve_evidence_value(
    config: dict[str, Any],
    extraction: MetricExtraction,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    value_mode = config.get("value_mode")
    if value_mode == "raw_text":
        return extraction.raw_value_text, None
    if value_mode == "rating_event":
        notes = None
        if isinstance(extraction.parsed_value_json, dict):
            notes = extraction.parsed_value_json.get("notes")
        event = parse_rating_event_notes(notes)
        if event is None:
            return None, None
        return event.get("type"), event
    return None, None


def _resolve_evidence_period_end(
    config: dict[str, Any],
    doc: PdfDocument,
    extraction: MetricExtraction,
    value_json: Optional[dict[str, Any]],
) -> Optional[str]:
    period_end_source = config.get("period_end_source")
    if period_end_source == "document_report_date":
        return _iso_date(doc.report_date or extraction.as_of_date or extraction.period_end_date)
    if period_end_source == "parsed_event_date" and isinstance(value_json, dict):
        return value_json.get("date")
    return _iso_date(extraction.period_end_date or extraction.as_of_date or doc.report_date)


def _iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _document_sort_ticker(document_row: dict[str, Any]) -> str:
    companies = document_row.get("companies")
    if isinstance(companies, list) and companies:
        first_company = companies[0]
        if isinstance(first_company, dict):
            ticker = first_company.get("ticker")
            if ticker:
                return str(ticker).upper()
    return "~"


def _document_review_selected_facts(
    session: SessionDep,
    doc: PdfDocument,
) -> list[MetricFact]:
    rows = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.user_id == doc.user_id,
            MetricFact.source_document_id == doc.id,
        )
        .order_by(MetricFact.id.asc())
    ).all()

    selected: dict[tuple[Any, ...], MetricFact] = {}
    for fact in rows:
        identity = _document_review_fact_identity(fact)
        current = selected.get(identity)
        if current is None or _document_review_fact_rank(fact) >= _document_review_fact_rank(current):
            selected[identity] = fact
    return list(selected.values())


def _document_review_fact_identity(fact: MetricFact) -> tuple[Any, ...]:
    return (
        fact.user_id,
        fact.stock_id,
        fact.metric_key,
        fact.period_type,
        fact.period_end_date,
        fact.as_of_date,
    )


def _document_review_fact_rank(fact: MetricFact) -> tuple[int, int, int]:
    manual_rank = 1 if fact.source_type == "manual" else 0
    current_rank = 1 if fact.is_current else 0
    return (manual_rank, current_rank, fact.id)


def _document_review_lineage_by_fact_id(
    session: SessionDep,
    doc: PdfDocument,
    facts: list[MetricFact],
) -> dict[int, MetricExtraction]:
    source_ref_ids = sorted({fact.source_ref_id for fact in facts if fact.source_ref_id is not None})
    by_extraction_id = {}
    if source_ref_ids:
        extractions = session.scalars(
            select(MetricExtraction).where(
                MetricExtraction.user_id == doc.user_id,
                MetricExtraction.document_id == doc.id,
                MetricExtraction.id.in_(source_ref_ids),
            )
        ).all()
        by_extraction_id = {extraction.id: extraction for extraction in extractions}

    document_extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
        )
        .order_by(MetricExtraction.id.desc())
    ).all()

    lineage: dict[int, MetricExtraction] = {}
    for fact in facts:
        if fact.source_ref_id in by_extraction_id:
            lineage[fact.id] = by_extraction_id[fact.source_ref_id]
            continue
        fallback = _document_review_find_lineage_fallback(fact, document_extractions)
        if fallback is not None:
            lineage[fact.id] = fallback
    return lineage


def _document_review_find_lineage_fallback(
    fact: MetricFact,
    extractions: list[MetricExtraction],
) -> Optional[MetricExtraction]:
    metric_leaf = (fact.metric_key or "").split(".")[-1]
    for extraction in extractions:
        if extraction.field_key not in {fact.metric_key, metric_leaf}:
            continue
        if fact.period_type and extraction.period_type and fact.period_type != extraction.period_type:
            continue
        if fact.period_end_date and extraction.period_end_date and fact.period_end_date != extraction.period_end_date:
            continue
        if fact.as_of_date and extraction.as_of_date and fact.as_of_date != extraction.as_of_date:
            continue
        return extraction
    return None


def _document_review_item(
    fact: MetricFact,
    stock_lookup: dict[int, Stock],
    lineage: Optional[MetricExtraction],
) -> dict[str, Any]:
    display_value = _document_review_display_value(fact)
    stock = stock_lookup.get(fact.stock_id)
    return {
        "metric_key": fact.metric_key,
        "label": _document_review_label(fact.metric_key),
        "fact_id": fact.id,
        "stock_ticker": stock.ticker if stock else None,
        "display_value": display_value,
        "value_numeric": fact.value_numeric,
        "value_text": fact.value_text,
        "unit": fact.unit,
        "period": fact.period,
        "period_type": fact.period_type,
        "period_end_date": _iso_date(fact.period_end_date),
        "as_of_date": _iso_date(fact.as_of_date),
        "source_type": fact.source_type,
        "is_current": fact.is_current,
        "lineage_available": lineage is not None,
        "lineage": _document_review_lineage(lineage),
        "editable": True,
    }


def _document_review_lineage(extraction: Optional[MetricExtraction]) -> Optional[dict[str, Any]]:
    if extraction is None:
        return None
    return {
        "extraction_id": extraction.id,
        "document_id": extraction.document_id,
        "page_number": extraction.page_number,
        "original_text_snippet": extraction.original_text_snippet,
    }


def _document_review_value_label(fact: MetricFact) -> Optional[str]:
    if fact.value_text:
        return fact.value_text
    if fact.value_numeric is not None:
        if fact.unit == "ratio" and "yield" in (fact.metric_key or ""):
            return f"{fact.value_numeric * 100:g}%"
        return f"{fact.value_numeric:g}"
    return None


def _document_review_display_value(fact: MetricFact) -> Optional[str]:
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    raw_value = value_json.get("raw")
    if raw_value is not None:
        return str(raw_value)
    return _document_review_value_label(fact)


def _document_review_label(metric_key: str) -> str:
    if metric_key in DOCUMENT_REVIEW_LABELS:
        return DOCUMENT_REVIEW_LABELS[metric_key]
    leaf = (metric_key or "Unknown").split(".")[-1]
    return leaf.replace("_", " ").title()


def _document_review_summary(
    facts: list[MetricFact],
    preferred_stock_id: Optional[int],
) -> dict[str, Optional[dict[str, Any]]]:
    candidate_stock_id = preferred_stock_id
    if candidate_stock_id is None:
        candidate_stock_id = next((fact.stock_id for fact in facts if fact.stock_id is not None), None)

    facts_by_key: dict[str, MetricFact] = {}
    for fact in facts:
        if not fact.metric_key:
            continue
        if candidate_stock_id is not None and fact.stock_id != candidate_stock_id:
            continue
        key = fact.metric_key
        current = facts_by_key.get(key)
        if current is None:
            facts_by_key[key] = fact
        elif fact.period_type == "AS_OF" and current.period_type != "AS_OF":
            # Prefer snapshot (AS_OF) over historical (FY) for summary display
            facts_by_key[key] = fact
        elif fact.period_type == current.period_type and _document_review_fact_rank(fact) >= _document_review_fact_rank(current):
            facts_by_key[key] = fact

    summary: dict[str, Optional[dict[str, Any]]] = {}
    for summary_key, metric_key, label in DOCUMENT_REVIEW_SUMMARY_FIELDS:
        fact = facts_by_key.get(metric_key)
        summary[summary_key] = _document_review_summary_item(fact, label)
    return summary


def _document_review_summary_item(
    fact: Optional[MetricFact],
    label: str,
) -> Optional[dict[str, Any]]:
    if fact is None:
        return None
    return {
        "metric_key": fact.metric_key,
        "label": label,
        "display_value": _document_review_display_value(fact),
        "value_numeric": fact.value_numeric,
        "unit": fact.unit,
    }


def _document_review_capital_structure(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(DOCUMENT_REVIEW_CAPITAL_STRUCTURE_FIELDS),
        )
        .order_by(MetricExtraction.id.asc())
    ).all()
    if not extractions:
        return None

    by_key = _latest_extractions_by_field(extractions)
    insurance_layout = bool(
        doc.raw_text
        and re.search(r'P/CPremiumsEarned|UnderwritingMargin|LossToPrem|InvInc/TotalInv', doc.raw_text, re.IGNORECASE)
    )
    capital_structure = _build_value_line_capital_structure(
        by_key,
        insurance_layout=insurance_layout,
        adr_layout=False,
        ads_layout=False,
    )
    return capital_structure or None


def _document_review_annual_financials(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(DOCUMENT_REVIEW_ANNUAL_FINANCIALS_FIELDS),
        )
        .order_by(MetricExtraction.id.asc())
    ).all()
    if not extractions:
        return None

    by_key = _latest_extractions_by_field(extractions)
    ts = by_key.get("tables_time_series")
    insurance_layout = False
    if ts and ts.parsed_value_json:
        annual = ts.parsed_value_json.get(
            "annual_financials_and_ratios_2015_2026_with_projection_2028_2030", {}
        )
        per_share = annual.get("per_share", {})
        insurance_keys = (
            "pc_prem_earned_per_share_usd",
            "investment_income_per_share_usd",
            "underwriting_income_per_share_usd",
        )
        insurance_layout = any(
            isinstance(per_share.get(k), list) and any(v is not None for v in per_share.get(k, []))
            for k in insurance_keys
        )
    annual_financials = _build_value_line_annual_financials(
        by_key,
        report_date=_iso_date(doc.report_date),
        insurance_layout=insurance_layout,
        adr_layout=False,
        ads_layout=False,
        text=doc.raw_text,
    )
    return annual_financials or None


def _document_review_total_return(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key == "price_semantics_and_returns",
        )
        .order_by(MetricExtraction.id.asc())
    ).all()
    if not extractions:
        return None

    total_return = _build_value_line_total_return(_latest_extractions_by_field(extractions))
    series = total_return.get("series") if isinstance(total_return, dict) else None
    if not isinstance(series, list) or not any(item.get("value_pct") is not None for item in series):
        return None
    total_return["fact_nature"] = "snapshot"
    return total_return


def _document_review_annual_rates(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(DOCUMENT_REVIEW_ANNUAL_RATES_FIELDS),
        )
        .order_by(MetricExtraction.id.asc())
    ).all()
    if not extractions:
        return None

    by_key = _latest_extractions_by_field(extractions)
    ar = by_key.get("annual_rates_of_change")
    insurance_layout = bool(
        ar
        and ar.parsed_value_json
        and (ar.parsed_value_json.get("premium_income") or ar.parsed_value_json.get("investment_income"))
    )
    annual_rates = _build_value_line_annual_rates(
        doc.raw_text or "",
        by_key,
        insurance_layout=insurance_layout,
        adr_layout=False,
        ads_layout=False,
    )
    return annual_rates or None


def _document_review_quarterly_extractions(
    session: SessionDep,
    doc: PdfDocument,
) -> dict[str, MetricExtraction]:
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(DOCUMENT_REVIEW_QUARTERLY_TABLE_FIELDS),
        )
        .order_by(MetricExtraction.id.asc())
    ).all()
    return _latest_extractions_by_field(extractions)


def _document_review_quarterly_sales(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    by_key = _document_review_quarterly_extractions(session, doc)
    if "quarterly_sales_usd_millions" not in by_key:
        return None
    quarterly_sales = _build_value_line_quarterly_block(
        by_key.get("quarterly_sales_usd_millions"),
        unit="USD_millions",
        report_date=_iso_date(doc.report_date),
        month_order=_value_line_quarter_month_order(doc.raw_text or ""),
    )
    return quarterly_sales or None


def _document_review_earnings_per_share(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    by_key = _document_review_quarterly_extractions(session, doc)
    if "earnings_per_share" not in by_key:
        return None
    earnings = _build_value_line_quarterly_block_or_none(
        by_key.get("earnings_per_share"),
        unit="USD_per_share",
        report_date=_iso_date(doc.report_date),
        month_order=_value_line_quarter_month_order(doc.raw_text or ""),
    )
    return earnings or None


def _document_review_quarterly_dividends_paid(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    by_key = _document_review_quarterly_extractions(session, doc)
    if "quarterly_dividends_paid_per_share" not in by_key:
        return None
    dividends = _build_value_line_quarterly_dividends_paid(
        doc.raw_text or "",
        by_key.get("quarterly_dividends_paid_per_share"),
        unit="USD_per_share",
        report_date=_iso_date(doc.report_date),
        adr_layout=False,
    )
    return dividends or None


def _document_review_current_position(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(DOCUMENT_REVIEW_CURRENT_POSITION_FIELDS),
        )
        .order_by(MetricExtraction.id.asc())
    ).all()
    if not extractions:
        return None

    by_key = _latest_extractions_by_field(extractions)
    current_position = _build_value_line_current_position(by_key)
    return current_position or None


def _document_review_financial_position(
    session: SessionDep,
    doc: PdfDocument,
) -> Optional[dict[str, Any]]:
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.user_id == doc.user_id,
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(DOCUMENT_REVIEW_FINANCIAL_POSITION_FIELDS),
        )
        .order_by(MetricExtraction.id.asc())
    ).all()
    if not extractions:
        return None
    by_key = _latest_extractions_by_field(extractions)
    fp = by_key.get("financial_position_usd_millions")
    return fp.parsed_value_json if fp and fp.parsed_value_json else None


def _document_review_group_key(fact: MetricFact) -> str:
    metric_key = (fact.metric_key or "").lower()
    period_type = (fact.period_type or "").upper()

    if any(token in metric_key for token in ["business", "commentary", "narrative", "description"]):
        return "narrative"
    if any(token in metric_key for token in ["institution", "to_buy", "to_sell", "holding"]):
        return "institutional_decisions"
    if period_type == "Q" or any(token in metric_key for token in ["quarter", "qtr"]):
        return "quarterly_tables"
    if any(token in metric_key for token in ["target", "projection", "return", "gain"]):
        return "target_projection"
    if any(
        token in metric_key
        for token in ["rating", "timeliness", "safety", "technical", "beta", "strength", "stability", "predictability"]
    ):
        return "ratings_quality"
    if any(
        token in metric_key
        for token in ["debt", "capital", "lease", "pension", "share", "market_cap", "interest"]
    ):
        return "capital_structure"
    if any(token in metric_key for token in ["cagr", "growth_rate", "annual_rate"]):
        return "annual_rates"
    if period_type == "FY":
        return "annual_financials"
    return "identity_header"


def _document_review_fact_belongs_to_document(
    session: SessionDep,
    doc: PdfDocument,
    fact: MetricFact,
) -> bool:
    if fact.source_document_id == doc.id:
        return True
    if fact.source_ref_id is None:
        return False
    extraction = session.get(MetricExtraction, fact.source_ref_id)
    return bool(
        extraction
        and extraction.user_id == doc.user_id
        and extraction.document_id == doc.id
    )


def _normalize_review_correction(
    *,
    raw_text: str,
    unit_hint: Optional[str],
    fact: MetricFact,
) -> tuple[Optional[float], Optional[str], Optional[str]]:
    value_type = _document_review_value_type(fact)
    if value_type == "text":
        return None, fact.unit, raw_text

    normalization_input = raw_text
    if unit_hint and unit_hint.lower() not in raw_text.lower():
        normalization_input = f"{raw_text} {unit_hint}"
    value_numeric, normalized_unit = Scaler.normalize(normalization_input, value_type)
    return value_numeric, normalized_unit, None


def _document_review_value_type(fact: MetricFact) -> str:
    metric_key = (fact.metric_key or "").lower()
    unit = (fact.unit or "").lower()
    if fact.value_numeric is None and unit not in {"usd", "ratio", "number", "shares"}:
        return "text"
    if unit == "usd" or any(
        token in metric_key
        for token in ["price", "market_cap", "debt", "sales", "revenue", "cash", "earnings", "income", "dividend"]
    ):
        return "currency"
    if unit == "ratio":
        if "%" in str(fact.value_json or "") or any(
            token in metric_key for token in ["yield", "pct", "percent", "margin", "cagr", "rate"]
        ):
            return "percent"
        return "ratio"
    if any(token in metric_key for token in ["yield", "pct", "percent", "margin", "cagr"]):
        return "percent"
    return "number"


def _document_stock_ids(session: SessionDep, doc: PdfDocument) -> set[int]:
    stock_ids = set(
        session.scalars(
            select(MetricFact.stock_id)
            .where(
                MetricFact.source_document_id == doc.id,
                MetricFact.source_type == "parsed",
            )
            .distinct()
        ).all()
    )
    if doc.stock_id:
        stock_ids.add(doc.stock_id)
    return {stock_id for stock_id in stock_ids if stock_id is not None}


def _document_compare_fact_entries(
    session: SessionDep,
    document_id: int,
    stock_ids: list[int],
    stock_lookup: dict[int, Stock],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    rows = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.source_document_id == document_id,
            MetricFact.source_type == "parsed",
            MetricFact.stock_id.in_(stock_ids),
        )
        .order_by(MetricFact.id.asc())
    ).all()

    entries: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fact in rows:
        value_json = fact.value_json or {}
        fact_nature = value_json.get("fact_nature")
        if fact_nature not in {"actual", "estimate", "snapshot", "opinion"}:
            continue
        key = _document_compare_fact_key(fact_nature, fact)
        entries[key] = {
            "fact_nature": fact_nature,
            "stock_ticker": stock_lookup.get(fact.stock_id).ticker if fact.stock_id in stock_lookup else None,
            "metric_key": fact.metric_key,
            "mapping_id": None,
            "period_type": fact.period_type,
            "period_end_date": _iso_date(fact.period_end_date or fact.as_of_date),
            "value": _document_compare_value_label(
                value_numeric=fact.value_numeric,
                value_text=fact.value_text,
                value_json=value_json,
            ),
        }
    return entries


def _document_compare_fact_key(fact_nature: str, fact: MetricFact) -> tuple[Any, ...]:
    if fact_nature in {"actual", "estimate"}:
        return (
            "fact",
            fact_nature,
            fact.stock_id,
            fact.metric_key,
            fact.period_type,
            fact.period_end_date,
        )
    return (
        "fact",
        fact_nature,
        fact.stock_id,
        fact.metric_key,
    )


def _document_compare_evidence_entries(
    session: SessionDep,
    doc: PdfDocument,
    taxonomy: dict[str, Any],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    evidence_reads = taxonomy.get("evidence_reads", {})
    if not evidence_reads:
        return {}

    field_keys = sorted(
        {
            str(config["extraction_field_key"])
            for config in evidence_reads.values()
            if config.get("source") == "metric_extractions" and config.get("extraction_field_key")
        }
    )
    extractions = session.scalars(
        select(MetricExtraction)
        .where(
            MetricExtraction.document_id == doc.id,
            MetricExtraction.field_key.in_(field_keys),
        )
    ).all()
    latest_by_field = _latest_extractions_by_field(extractions)
    mapping_semantics = taxonomy.get("mapping_semantics", {})

    entries: dict[tuple[Any, ...], dict[str, Any]] = {}
    for mapping_id, config in evidence_reads.items():
        extraction_field_key = config.get("extraction_field_key")
        if not isinstance(extraction_field_key, str):
            continue
        extraction = latest_by_field.get(extraction_field_key)
        if extraction is None:
            continue

        value_text, _value_json = _resolve_evidence_value(config, extraction)
        if value_text is None:
            continue
        semantics = mapping_semantics.get(mapping_id, {})
        fact_nature = semantics.get("fact_nature")
        if fact_nature not in {"actual", "estimate", "snapshot", "opinion"}:
            continue
        period_end_date = _resolve_evidence_period_end(config, doc, extraction, None)
        key = ("evidence", fact_nature, mapping_id)
        entries[key] = {
            "fact_nature": fact_nature,
            "stock_ticker": None,
            "metric_key": config.get("metric_key"),
            "mapping_id": mapping_id,
            "period_type": config.get("period_type"),
            "period_end_date": period_end_date,
            "value": value_text,
        }
    return entries


def _build_document_compare_sections(
    *,
    left_fact_entries: dict[tuple[Any, ...], dict[str, Any]],
    right_fact_entries: dict[tuple[Any, ...], dict[str, Any]],
    left_evidence_entries: dict[tuple[Any, ...], dict[str, Any]],
    right_evidence_entries: dict[tuple[Any, ...], dict[str, Any]],
) -> list[dict[str, Any]]:
    left_entries = {}
    left_entries.update(left_fact_entries)
    left_entries.update(left_evidence_entries)
    right_entries = {}
    right_entries.update(right_fact_entries)
    right_entries.update(right_evidence_entries)

    grouped_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_keys = set(left_entries) | set(right_entries)
    for key in all_keys:
        left = left_entries.get(key)
        right = right_entries.get(key)
        fact_nature = (left or right or {}).get("fact_nature")
        if fact_nature not in {"actual", "estimate", "snapshot", "opinion"}:
            continue

        left_value = left.get("value") if left else None
        right_value = right.get("value") if right else None
        if left_value == right_value:
            continue

        grouped_items[fact_nature].append(
            {
                "stock_ticker": (left or right).get("stock_ticker"),
                "metric_key": (left or right).get("metric_key"),
                "mapping_id": (left or right).get("mapping_id"),
                "period_type": (left or right).get("period_type"),
                "period_end_date": (left or right).get("period_end_date"),
                "label": _document_compare_label(left or right),
                "change_type": _document_compare_change_type(left_value, right_value),
                "left_value": left_value,
                "right_value": right_value,
            }
        )

    sections = []
    for fact_nature in ["actual", "estimate", "snapshot", "opinion"]:
        items = sorted(
            grouped_items.get(fact_nature, []),
            key=lambda item: (
                item["stock_ticker"] or "",
                item["metric_key"] or "",
                item["mapping_id"] or "",
                item["period_end_date"] or "",
            ),
        )
        sections.append(
            {
                "fact_nature": fact_nature,
                "title": fact_nature.capitalize(),
                "items": items,
            }
        )
    return sections


def _document_compare_label(entry: dict[str, Any]) -> str:
    if entry.get("stock_ticker") and entry.get("metric_key"):
        return f"{entry['stock_ticker']} · {entry['metric_key']}"
    if entry.get("mapping_id"):
        return str(entry["mapping_id"])
    return str(entry.get("metric_key") or "Unknown")


def _document_compare_change_type(left_value: Optional[str], right_value: Optional[str]) -> str:
    if left_value is None:
        return "right_only"
    if right_value is None:
        return "left_only"
    return "changed"


def _document_compare_value_label(
    *,
    value_numeric: Optional[float],
    value_text: Optional[str],
    value_json: dict[str, Any],
) -> Optional[str]:
    if value_numeric is not None:
        return f"{value_numeric:g}"
    if value_text:
        return value_text
    raw = value_json.get("raw")
    return str(raw) if raw is not None else None
