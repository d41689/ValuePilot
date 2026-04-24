"""Raw document fetch → raw_source_documents table + local file store.

Default behaviour (EDGAR_FETCH_MODE=live): fetch from network and save.
Replay mode (EDGAR_FETCH_MODE=replay): read from existing raw_source_documents.
"""
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.edgar.client import EdgarClient
from app.models.institutions import RawSourceDocument

logger = logging.getLogger(__name__)


def _storage_path(source_system: str, raw_sha256: str, ext: str = "bin") -> Path:
    """Deterministic storage path: <root>/<source_system>/<sha256[:2]>/<sha256>.<ext>"""
    root = Path(settings.EDGAR_RAW_STORAGE_DIR)
    return root / source_system / raw_sha256[:2] / f"{raw_sha256}.{ext}"


def _ext_for_document_type(document_type: str) -> str:
    if "xml" in document_type:
        return "xml"
    if "json" in document_type:
        return "json"
    if "html" in document_type:
        return "html"
    if "idx" in document_type:
        return "txt"
    return "bin"


def fetch_and_store(
    db: Session,
    *,
    source_system: str,
    document_type: str,
    source_url: str,
    cik: Optional[str] = None,
    accession_no: Optional[str] = None,
    client: Optional[EdgarClient] = None,
    force_refresh: bool = False,
) -> RawSourceDocument:
    """Fetch URL and persist raw bytes; return the RawSourceDocument record.

    MVP default: skip if record already exists (unless force_refresh=True).
    In replay mode the URL is not fetched; existing record is required.
    """
    existing = (
        db.query(RawSourceDocument)
        .filter_by(source_system=source_system, source_url=source_url)
        .one_or_none()
    )

    if settings.EDGAR_FETCH_MODE == "replay":
        if existing is None:
            raise RuntimeError(
                f"Replay mode: no raw record for {source_url}"
            )
        return existing

    if existing is not None and not force_refresh:
        return existing

    # --- live fetch ---
    own_client = client is None
    if own_client:
        client = EdgarClient()
    try:
        body = client.get(source_url)
    finally:
        if own_client:
            client.close()

    raw_sha256 = hashlib.sha256(body).hexdigest()
    ext = _ext_for_document_type(document_type)
    path = _storage_path(source_system, raw_sha256, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)

    now = datetime.now(timezone.utc)

    if existing is not None and force_refresh:
        existing.http_status = 200
        existing.fetched_at = now
        existing.raw_sha256 = raw_sha256
        existing.body_path = str(path)
        existing.parse_status = "pending"
        existing.parsed_at = None
        existing.error_message = None
        db.flush()
        return existing

    doc = RawSourceDocument(
        source_system=source_system,
        document_type=document_type,
        cik=cik,
        accession_no=accession_no,
        source_url=source_url,
        http_status=200,
        fetched_at=now,
        raw_sha256=raw_sha256,
        body_path=str(path),
        parse_status="pending",
    )
    db.add(doc)
    try:
        # Use a savepoint so a conflict on (source_system, source_url) doesn't
        # abort the outer transaction — just re-fetch the already-committed row.
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        existing = (
            db.query(RawSourceDocument)
            .filter_by(source_system=source_system, source_url=source_url)
            .one()
        )
        return existing
    return doc


def load_body(doc: RawSourceDocument) -> bytes:
    """Load raw bytes from storage for a RawSourceDocument record."""
    return Path(doc.body_path).read_bytes()
