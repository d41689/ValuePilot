import uuid
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from fastapi import UploadFile

from app.models.artifacts import PdfDocument, DocumentPage
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.services.file_storage import FileStorageService
from app.services.identity_service import IdentityService
from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.normalization.scaler import Scaler

class IngestionService:
    def __init__(self, db: Session):
        self.db = db
        self.storage = FileStorageService()
        self.identity_service = IdentityService(db)

    def process_upload(self, user_id: int, file: UploadFile) -> PdfDocument:
        """
        Handles the full upload and ingestion process:
        1. Save file to storage.
        2. Create PdfDocument record.
        3. Extract text (Phase 1 of extraction).
        4. Save DocumentPage records.
        5. Run Identity Resolution.
        6. Run Metric Parsing.
        7. Run Normalization & Fact Creation.
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
            parse_status="pending",
            upload_time=datetime.now()
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        try:
            # 3. Extract text
            # For V1 we assume native text extraction is primary
            pages_data = PdfExtractor.extract_pages(saved_path)
            
            full_text_parts = []
            
            # 4. Save DocumentPage records
            for page_num, text in pages_data:
                full_text_parts.append(text)
                page_record = DocumentPage(
                    document_id=doc.id,
                    page_number=page_num,
                    page_text=text,
                    text_extraction_method="native_text"
                )
                self.db.add(page_record)
            
            # Update main document with cached raw text
            doc.raw_text = "\n".join(full_text_parts)
            
            # 5. Identity Resolution
            # Use V1 parser to extract identity info
            parser = ValueLineV1Parser(doc.raw_text)
            identity_info = parser.extract_identity()
            
            self.identity_service.resolve_stock_identity(doc, identity_info)

            # 6. Metric Parsing
            # Extract metrics using the same parser instance (or new one)
            extractions = parser.parse()
            
            for ext in extractions:
                # Create Extraction record
                metric_record = MetricExtraction(
                    user_id=user_id,
                    document_id=doc.id,
                    page_number=ext.page_number,
                    field_key=ext.field_key,
                    raw_value_text=ext.raw_value_text,
                    original_text_snippet=ext.original_text_snippet,
                    parsed_value_json=ext.parsed_value_json,
                    confidence_score=ext.confidence_score,
                    bbox_json=ext.bbox_json,
                    parser_template_id=None,
                    parser_version="v1"
                )
                self.db.add(metric_record)
                self.db.flush() # flush to get ID
                
                # 7. Normalization & Fact Creation
                # Only if we have a resolved stock (usually yes, even if auto-created)
                if doc.stock_id:
                    # Infer value type (simple heuristic for V1)
                    value_type = "number"
                    if "yield" in ext.field_key or "pct" in ext.field_key:
                        value_type = "percent"
                    elif "ratio" in ext.field_key:
                        value_type = "ratio"
                        
                    norm_val, norm_unit = Scaler.normalize(ext.raw_value_text, value_type)
                    
                    fact = MetricFact(
                        user_id=user_id,
                        stock_id=doc.stock_id,
                        metric_key=ext.field_key, # Map to canonical if different
                        value_json={"raw": ext.raw_value_text, "normalized": norm_val, "unit": norm_unit},
                        value_numeric=norm_val,
                        unit=norm_unit,
                        source_type="parsed",
                        source_ref_id=metric_record.id,
                        is_current=True # Simplified logic: latest parse is current
                    )
                    
                    # Mark previous facts as not current? (TODO for robustness)
                    self.db.add(fact)
            
            doc.parse_status = "parsed" 
            
            self.db.commit()
            self.db.refresh(doc)
            
        except Exception as e:
            # Handle failure
            doc.parse_status = "failed"
            doc.notes = f"Extraction failed: {str(e)}"
            self.db.commit()
            raise e

        return doc
