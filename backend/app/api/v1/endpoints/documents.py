from typing import Any
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from app.api.deps import SessionDep
from app.services.ingestion_service import IngestionService
from app.models.users import User

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
