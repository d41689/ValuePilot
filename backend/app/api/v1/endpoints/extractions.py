from typing import Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Body
from sqlalchemy import select
from app.api.deps import SessionDep, CurrentUser
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.artifacts import PdfDocument
from app.ingestion.normalization.scaler import Scaler

router = APIRouter()

@router.get("/document/{document_id}", response_model=list[dict])
def read_document_extractions(
    document_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Get all extractions for a specific document (Traceability View).
    """
    doc = session.get(PdfDocument, document_id)
    if not doc or doc.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    stmt = select(MetricExtraction).where(MetricExtraction.document_id == document_id)
    extractions = session.scalars(stmt).all()
    
    return [
        {
            "id": e.id,
            "field_key": e.field_key,
            "raw_value_text": e.raw_value_text,
            "original_text_snippet": e.original_text_snippet,
            "confidence_score": e.confidence_score,
            "page_number": e.page_number,
            "bbox_json": e.bbox_json,
            "corrected_by_user": e.corrected_by_user
        }
        for e in extractions
    ]

@router.post("/{extraction_id}/correct", response_model=dict)
def correct_extraction(
    extraction_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    corrected_value: str = Body(..., embed=True),
) -> Any:
    """
    Correct an extraction value.
    Creates a new manual MetricFact and marks the extraction as corrected.
    """
    extraction = session.get(MetricExtraction, extraction_id)
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    # 1. Update Extraction
    extraction.corrected_by_user = True
    extraction.corrected_at = datetime.now()
    session.add(extraction)
    
    # 2. Normalize new value
    # Heuristic for value type based on field key (reusing logic from ingestion - ideally centralized)
    value_type = "number"
    if "yield" in extraction.field_key or "pct" in extraction.field_key:
        value_type = "percent"
    elif "ratio" in extraction.field_key:
        value_type = "ratio"
    
    norm_val, norm_unit = Scaler.normalize(corrected_value, value_type)
    
    # 3. Create Manual Fact
    # Need to resolve stock_id from document
    doc = session.get(PdfDocument, extraction.document_id)
    if not doc or not doc.stock_id:
         raise HTTPException(status_code=400, detail="Document not linked to a stock, cannot create fact.")

    fact = MetricFact(
        user_id=extraction.user_id,
        stock_id=doc.stock_id,
        metric_key=extraction.field_key,
        value_json={"raw": corrected_value, "normalized": norm_val, "unit": norm_unit, "correction": True},
        value_numeric=norm_val,
        unit=norm_unit,
        source_type="manual",
        source_ref_id=extraction.id,
        is_current=True
    )
    session.add(fact)
    
    # TODO: Mark old facts as not current?
    # For V1 simple logic: We assume the latest manual fact is the truth. 
    # Real implementation would query existing current fact and set is_current=False.
    
    session.commit()
    session.refresh(fact)
    
    return {"status": "success", "fact_id": fact.id, "normalized_value": norm_val}
