from typing import Any
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from app.api.deps import SessionDep
from app.services.ingestion_service import IngestionService
from app.models.users import User
from app.models.artifacts import PdfDocument

router = APIRouter()

@router.post("/upload", response_model=dict)
def upload_document(
    *,
    session: SessionDep,
    file: UploadFile = File(...),
    user_id: int = Query(..., description="ID of the user uploading the document")
) -> Any:
    """
    Upload a PDF document, save it, and extract text.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Validate user exists
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    service = IngestionService(session)
    try:
        doc = service.process_upload(user_id, file)
        return {
            "id": doc.id,
            "file_name": doc.file_name,
            "status": doc.parse_status,
            "page_count": len(doc.pages)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@router.post("/{document_id}/reparse", response_model=dict)
def reparse_document(
    *,
    session: SessionDep,
    document_id: int,
    user_id: int = Query(..., description="ID of the user who owns the document"),
    reextract_pdf: bool = Query(False, description="Re-extract text from stored PDF before parsing"),
) -> Any:
    """
    Re-run parsing for an existing document ID.
    Inserts new metric_extractions and new parsed metric_facts (previous parsed facts are deactivated).
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    doc = session.get(PdfDocument, document_id)
    if not doc or doc.user_id != user_id:
        raise HTTPException(status_code=404, detail="Document not found for user")

    service = IngestionService(session)
    try:
        doc = service.reparse_existing_document(user_id=user_id, document_id=document_id, reextract_pdf=reextract_pdf)
        return {"id": doc.id, "status": doc.parse_status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reparse failed: {str(e)}")
