from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from sqlalchemy import select, func
import yaml
from app.models.artifacts import DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.api.deps import SessionDep, CurrentUser
from app.ingestion.parsers.v1_value_line.evidence import parse_rating_event_notes
from app.services.active_report_resolver import resolve_active_reports
from app.services.ingestion_service import IngestionService
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

    return output

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
