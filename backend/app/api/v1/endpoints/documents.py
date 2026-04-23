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
