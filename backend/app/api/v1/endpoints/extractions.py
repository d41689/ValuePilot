from typing import Any
from fastapi import APIRouter, HTTPException, Body
from sqlalchemy import func, select, update
from app.api.deps import SessionDep, CurrentUser
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.artifacts import PdfDocument
from app.ingestion.normalization.scaler import Scaler
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from app.services.financial_truth_locks import (
    acquire_active_account_mutation_lock,
    acquire_user_stock_fact_lock,
)

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
    Correct an extraction by appending a source-linked manual fact.

    The extraction is immutable audit evidence. A correction therefore never
    mutates it and is unavailable once the governing source is archived or
    erased.
    """
    if not acquire_active_account_mutation_lock(
        session, user_id=current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "account_erased",
                "message": "This account no longer accepts extraction corrections.",
            },
        )
    extraction_lookup = session.scalar(
        select(MetricExtraction)
        .where(
            MetricExtraction.id == extraction_id,
            MetricExtraction.user_id == current_user.id,
        )
    )
    if extraction_lookup is None:
        raise HTTPException(status_code=404, detail="Extraction not found")

    # All document/extraction writers lock in document -> extraction order.
    # Account erasure uses the same order, preventing a correction/erasure
    # deadlock while retaining row-level serialization.
    doc = session.scalar(
        select(PdfDocument)
        .where(
            PdfDocument.id == extraction_lookup.document_id,
            PdfDocument.user_id == current_user.id,
        )
        .with_for_update()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Extraction not found")
    extraction = session.scalar(
        select(MetricExtraction)
        .where(
            MetricExtraction.id == extraction_id,
            MetricExtraction.user_id == current_user.id,
            MetricExtraction.document_id == doc.id,
        )
        .with_for_update()
    )
    if extraction is None:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if doc.lifecycle_state != "active":
        reason = (
            "account_erasure"
            if doc.lifecycle_state == "erased"
            else "document_archived"
        )
        raise HTTPException(
            status_code=410,
            detail={
                "code": "source_unavailable",
                "reason": reason,
                "document_id": doc.id,
            },
        )
    target_stock_id = extraction.resolved_stock_id
    if target_stock_id is None or (
        doc.stock_id is not None and doc.stock_id != target_stock_id
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "extraction_stock_unresolved",
                "message": "Extraction is not bound to one reviewed stock.",
            },
        )
    acquire_user_stock_fact_lock(
        session, user_id=current_user.id, stock_id=target_stock_id
    )
    if extraction.parse_generation != doc.current_parse_generation:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "correction_target_not_current_generation",
                "document_id": doc.id,
                "extraction_id": extraction.id,
            },
        )

    canonical_facts = session.scalars(
        select(MetricFact).where(
            MetricFact.user_id == current_user.id,
            MetricFact.stock_id == target_stock_id,
            MetricFact.source_type == "parsed",
            MetricFact.source_document_id == doc.id,
            MetricFact.source_ref_id == extraction.id,
            MetricFact.parse_generation == doc.current_parse_generation,
            MetricFact.is_current.is_(True),
            func.parsed_metric_fact_has_exact_authority(MetricFact.id).is_(True),
        )
    ).all()
    if len(canonical_facts) != 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "correction_target_ambiguous",
                "document_id": doc.id,
                "extraction_id": extraction.id,
                "candidate_fact_count": len(canonical_facts),
                "next_action": "Correct a canonical fact from the document review surface.",
            },
        )
    canonical_fact = canonical_facts[0]

    # Normalize before making any state change.
    # The canonical fact, never the parser field name, owns metric and unit
    # semantics. Parser keys such as recent_price are not metric_facts keys.
    value_type = "number"
    metric_key = canonical_fact.metric_key.lower()
    unit = (canonical_fact.unit or "").lower()
    if "yield" in metric_key or "pct" in metric_key or "percent" in metric_key:
        value_type = "percent"
    elif unit == "ratio":
        value_type = "ratio"
    elif unit == "usd" or any(
        token in metric_key
        for token in ["price", "market_cap", "debt", "sales", "revenue", "cash", "income"]
    ):
        value_type = "currency"
    
    norm_val, norm_unit = Scaler.normalize(corrected_value, value_type)
    if norm_val is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "correction_value_invalid",
                "field_key": extraction.field_key,
            },
        )

    # Manual truth supersedes only the same user/stock/metric/period slot.
    session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == current_user.id,
            MetricFact.stock_id == target_stock_id,
            MetricFact.metric_key == canonical_fact.metric_key,
            MetricFact.period_type.is_not_distinct_from(canonical_fact.period_type),
            MetricFact.period_end_date.is_not_distinct_from(
                canonical_fact.period_end_date
            ),
            MetricFact.as_of_date.is_not_distinct_from(canonical_fact.as_of_date),
            MetricFact.source_type == "manual",
            MetricFact.is_current.is_(True),
        )
        .values(is_current=False)
    )

    fact = MetricFact(
        user_id=current_user.id,
        stock_id=target_stock_id,
        metric_key=canonical_fact.metric_key,
        value_json={
            "raw": corrected_value,
            "normalized": norm_val,
            "unit": norm_unit,
            "correction": True,
            "corrected_from_fact_id": canonical_fact.id,
            "corrected_from_extraction_id": extraction.id,
        },
        value_numeric=norm_val,
        unit=norm_unit,
        currency=canonical_fact.currency,
        period=canonical_fact.period,
        period_type=canonical_fact.period_type,
        period_end_date=canonical_fact.period_end_date,
        as_of_date=canonical_fact.as_of_date,
        source_document_id=doc.id,
        source_type="manual",
        source_ref_id=extraction.id,
        is_current=True,
    )
    session.add(fact)
    session.flush()
    ValueLineRatioCalculator(session).calculate_for_stock(
        user_id=current_user.id, stock_id=target_stock_id
    )
    PiotroskiFScoreCalculator(session).calculate_for_stock(
        user_id=current_user.id, stock_id=target_stock_id
    )
    session.commit()
    session.refresh(fact)
    
    return {"status": "success", "fact_id": fact.id, "normalized_value": norm_val}
