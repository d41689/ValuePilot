from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Body
from sqlalchemy import select
from app.api.deps import SessionDep, CurrentUser
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.artifacts import PdfDocument, ValueLineMappingPolicy, ValueLineParseRun
from app.services.manual_metric_correction import (
    ManualMetricCorrectionError,
    create_manual_metric_correction,
)

router = APIRouter()


@dataclass(frozen=True)
class ExtractionCorrectionIdentityError(ValueError):
    code: str
    message: str

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
    Correct an extraction only when it resolves to one canonical parsed fact.
    """
    extraction = session.get(MetricExtraction, extraction_id)
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")
    if extraction.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    try:
        source_fact = _resolve_canonical_fact_for_extraction(
            session,
            extraction=extraction,
            user_id=current_user.id,
        )
        fact = create_manual_metric_correction(
            session,
            user_id=current_user.id,
            source_fact=source_fact,
            raw_value=corrected_value,
        )
    except ExtractionCorrectionIdentityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except ManualMetricCorrectionError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    session.commit()
    session.refresh(fact)

    return {
        "status": "success",
        "fact_id": fact.id,
        "normalized_value": fact.value_numeric,
        "unit": fact.unit,
    }


def _resolve_canonical_fact_for_extraction(
    session: SessionDep,
    *,
    extraction: MetricExtraction,
    user_id: int,
) -> MetricFact:
    document = session.get(PdfDocument, extraction.document_id)
    if (
        extraction.user_id != user_id
        or extraction.value_line_parse_run_id is None
        or extraction.value_line_legacy_revision
        or document is None
        or document.user_id != user_id
        or document.stock_id is None
        or document.identity_needs_review
    ):
        raise ExtractionCorrectionIdentityError(
            code="extraction_correction_identity_unavailable",
            message="This extraction has no authoritative parse-run identity; select a canonical fact for review.",
        )

    candidates = session.scalars(
        select(MetricFact)
        .join(
            ValueLineParseRun,
            ValueLineParseRun.id == MetricFact.value_line_parse_run_id,
        )
        .join(
            ValueLineMappingPolicy,
            ValueLineMappingPolicy.id == ValueLineParseRun.source_mapping_version,
        )
        .where(
            MetricFact.user_id == user_id,
            MetricFact.source_type == "parsed",
            MetricFact.stock_id == document.stock_id,
            MetricFact.source_document_id == extraction.document_id,
            MetricFact.source_ref_id == extraction.id,
            MetricFact.value_line_parse_run_id == extraction.value_line_parse_run_id,
            ValueLineParseRun.user_id == user_id,
            ValueLineParseRun.document_id == extraction.document_id,
            ValueLineParseRun.status == "succeeded",
            ValueLineMappingPolicy.status.in_(("approved", "superseded")),
        )
        .order_by(MetricFact.id)
        .limit(2)
    ).all()
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ExtractionCorrectionIdentityError(
            code="extraction_correction_identity_unavailable",
            message="No canonical parsed fact is bound to this extraction and parse run.",
        )
    raise ExtractionCorrectionIdentityError(
        code="extraction_correction_ambiguous",
        message="This extraction maps to multiple canonical facts; select the exact fact and fiscal period for review.",
    )
