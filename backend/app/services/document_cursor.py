"""Persistent, tenant-bound snapshot protocol for document traversal."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
import secrets
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.artifacts import (
    DocumentListSnapshot,
    DocumentListSnapshotMember,
    PdfDocument,
)


CURSOR_VERSION = 2
MAX_DOCUMENT_CURSOR_LENGTH = 4096
MAX_DOCUMENT_SNAPSHOT_MEMBERS = 5000
DOCUMENT_SNAPSHOT_TTL_MINUTES = 15
INVALID_DOCUMENTS_CURSOR = "invalid_documents_cursor"


class InvalidDocumentsCursorError(ValueError):
    code = INVALID_DOCUMENTS_CURSOR

    def __init__(self) -> None:
        super().__init__("The documents cursor is invalid for this request.")


class DocumentsCursorExpiredError(ValueError):
    code = "documents_cursor_expired"

    def __init__(self) -> None:
        super().__init__("The document snapshot expired; restart traversal.")


class DocumentsSnapshotSourceUnavailableError(ValueError):
    code = "documents_snapshot_source_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "A retained document is no longer visible; restart traversal."
        )


class DocumentsSnapshotBoundExceededError(ValueError):
    code = "documents_snapshot_bound_exceeded"

    def __init__(self) -> None:
        super().__init__("The document collection exceeds the snapshot bound.")


@dataclass(frozen=True)
class DocumentCursor:
    user_id: int
    limit: int
    snapshot_id: str
    last_ordinal: int
    last_upload_time: datetime | None
    last_id: int


@dataclass(frozen=True)
class DocumentSnapshot:
    snapshot_id: str
    user_id: int
    limit: int
    snapshot_cutoff: datetime
    expires_at: datetime
    snapshot_max_id: int
    snapshot_total: int


@dataclass(frozen=True)
class DocumentSnapshotRow:
    ordinal: int
    document: PdfDocument
    upload_time: datetime | None


def create_document_snapshot(
    session: Session,
    *,
    user_id: int,
    limit: int,
) -> DocumentSnapshot:
    """Capture exact membership and immutable sort keys in one SQL statement."""

    session.execute(
        delete(DocumentListSnapshot).where(
            DocumentListSnapshot.expires_at <= text("clock_timestamp()")
        )
    )
    snapshot_id = secrets.token_urlsafe(32)
    row = session.execute(
        text(
            """
            WITH snapshot_clock AS MATERIALIZED (
              SELECT clock_timestamp() AS cutoff
            ), raw_candidates AS MATERIALIZED (
              SELECT d.id AS document_id,d.upload_time,d.source
              FROM pdf_documents d
              WHERE d.user_id=:user_id
              ORDER BY d.upload_time DESC NULLS LAST,d.id DESC
              LIMIT :candidate_limit
            ), candidates AS MATERIALIZED (
              SELECT row_number() OVER (
                       ORDER BY upload_time DESC NULLS LAST,document_id DESC
                     )::integer AS ordinal,
                     document_id,upload_time,source
              FROM raw_candidates
            ), candidate_stats AS MATERIALIZED (
              SELECT count(*)::integer AS candidate_count,
                     COALESCE(max(document_id),0)::bigint AS max_document_id
              FROM candidates
            ), new_snapshot AS (
              INSERT INTO document_list_snapshots
                (id,user_id,page_limit,total_count,max_document_id,
                 snapshot_cutoff,expires_at)
              SELECT :snapshot_id,:user_id,:page_limit,
                     LEAST(candidate_count,:max_members),max_document_id,
                     cutoff,cutoff + (:ttl_minutes * interval '1 minute')
              FROM snapshot_clock CROSS JOIN candidate_stats
              RETURNING id,user_id,page_limit,total_count,max_document_id,
                        snapshot_cutoff,expires_at
            ), inserted_members AS (
              INSERT INTO document_list_snapshot_members
                (snapshot_id,ordinal,document_id,upload_time,source)
              SELECT n.id,c.ordinal,c.document_id,c.upload_time,c.source
              FROM new_snapshot n CROSS JOIN candidates c
              CROSS JOIN candidate_stats s
              WHERE s.candidate_count <= :max_members
              RETURNING snapshot_id
            )
            SELECT n.*,s.candidate_count,
                   (SELECT count(*) FROM inserted_members) AS inserted_count
            FROM new_snapshot n CROSS JOIN candidate_stats s
            """
        ),
        {
            "candidate_limit": MAX_DOCUMENT_SNAPSHOT_MEMBERS + 1,
            "max_members": MAX_DOCUMENT_SNAPSHOT_MEMBERS,
            "page_limit": limit,
            "snapshot_id": snapshot_id,
            "ttl_minutes": DOCUMENT_SNAPSHOT_TTL_MINUTES,
            "user_id": user_id,
        },
    ).mappings().one()
    if row["candidate_count"] > MAX_DOCUMENT_SNAPSHOT_MEMBERS:
        session.rollback()
        raise DocumentsSnapshotBoundExceededError()
    if row["candidate_count"] != row["inserted_count"]:
        session.rollback()
        raise RuntimeError("document snapshot membership capture was incomplete")
    return _snapshot_from_mapping(row)


def load_document_snapshot(
    session: Session,
    *,
    cursor: DocumentCursor,
) -> DocumentSnapshot:
    row = session.scalar(
        select(DocumentListSnapshot).where(
            DocumentListSnapshot.id == cursor.snapshot_id,
            DocumentListSnapshot.user_id == cursor.user_id,
            DocumentListSnapshot.page_limit == cursor.limit,
        ).with_for_update()
    )
    now = session.scalar(select(text("clock_timestamp()")))
    if row is None or now is None:
        raise DocumentsCursorExpiredError()
    if row.expires_at <= now:
        session.delete(row)
        session.commit()
        raise DocumentsCursorExpiredError()
    retained_boundary = session.scalar(
        select(DocumentListSnapshotMember).where(
            DocumentListSnapshotMember.snapshot_id == cursor.snapshot_id,
            DocumentListSnapshotMember.ordinal == cursor.last_ordinal,
        )
    )
    if (
        retained_boundary is None
        or retained_boundary.document_id != cursor.last_id
        or retained_boundary.upload_time != cursor.last_upload_time
        or cursor.last_ordinal > row.total_count
    ):
        raise InvalidDocumentsCursorError()
    return DocumentSnapshot(
        snapshot_id=row.id,
        user_id=row.user_id,
        limit=row.page_limit,
        snapshot_cutoff=row.snapshot_cutoff,
        expires_at=row.expires_at,
        snapshot_max_id=row.max_document_id,
        snapshot_total=row.total_count,
    )


def load_document_snapshot_page(
    session: Session,
    *,
    snapshot: DocumentSnapshot,
    after_ordinal: int,
) -> tuple[list[DocumentSnapshotRow], bool]:
    member = DocumentListSnapshotMember
    retained_rows = session.scalars(
        select(member)
        .where(
            member.snapshot_id == snapshot.snapshot_id,
            member.ordinal > after_ordinal,
        )
        .order_by(member.ordinal)
        .limit(snapshot.limit + 1)
    ).all()
    documents = {
        document.id: document
        for document in session.scalars(
            select(PdfDocument)
            .where(
                PdfDocument.id.in_([row.document_id for row in retained_rows])
            )
            .with_for_update(of=PdfDocument, read=True)
        ).all()
    }
    visible: list[DocumentSnapshotRow] = []
    for retained in retained_rows:
        document = documents.get(retained.document_id)
        # Membership is historical, but authorization and ownership are current.
        # Any loss makes the traversal explicitly incomplete; never shrink it.
        if (
            document is None
            or document.user_id != snapshot.user_id
            or document.source != retained.source
        ):
            raise DocumentsSnapshotSourceUnavailableError()
        visible.append(
            DocumentSnapshotRow(
                ordinal=retained.ordinal,
                document=document,
                upload_time=retained.upload_time,
            )
        )
    return visible[: snapshot.limit], len(visible) > snapshot.limit


def encode_document_cursor(cursor: DocumentCursor) -> str:
    payload = {
        "last_id": cursor.last_id,
        "last_ordinal": cursor.last_ordinal,
        "last_upload_time": (
            cursor.last_upload_time.isoformat()
            if cursor.last_upload_time is not None
            else None
        ),
        "limit": cursor.limit,
        "snapshot_id": cursor.snapshot_id,
        "user_id": cursor.user_id,
        "version": CURSOR_VERSION,
    }
    encoded = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    signature = hmac.new(
        settings.SECRET_KEY.encode(), encoded.encode(), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64encode(signature)}"


def decode_document_cursor(token: str, *, user_id: int) -> DocumentCursor:
    try:
        if not token or len(token) > MAX_DOCUMENT_CURSOR_LENGTH:
            raise ValueError
        encoded, encoded_signature = token.split(".", 1)
        if not encoded or not encoded_signature:
            raise ValueError
        supplied_signature = _b64decode(encoded_signature)
        expected_signature = hmac.new(
            settings.SECRET_KEY.encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError
        payload = json.loads(_b64decode(encoded))
        if not isinstance(payload, dict) or set(payload) != {
            "last_id",
            "last_ordinal",
            "last_upload_time",
            "limit",
            "snapshot_id",
            "user_id",
            "version",
        }:
            raise ValueError
        if payload["version"] != CURSOR_VERSION:
            raise ValueError
        values = (
            payload["user_id"],
            payload["limit"],
            payload["last_ordinal"],
            payload["last_id"],
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError
        snapshot_id = payload["snapshot_id"]
        if (
            payload["user_id"] != user_id
            or not 1 <= payload["limit"] <= 500
            or payload["last_ordinal"] <= 0
            or payload["last_id"] <= 0
            or not isinstance(snapshot_id, str)
            or not 32 <= len(snapshot_id) <= 64
        ):
            raise ValueError
        raw_time = payload["last_upload_time"]
        if raw_time is None:
            last_upload_time = None
        elif isinstance(raw_time, str):
            last_upload_time = datetime.fromisoformat(raw_time)
            if last_upload_time.utcoffset() is None:
                raise ValueError
        else:
            raise ValueError
        return DocumentCursor(
            user_id=payload["user_id"],
            limit=payload["limit"],
            snapshot_id=snapshot_id,
            last_ordinal=payload["last_ordinal"],
            last_upload_time=last_upload_time,
            last_id=payload["last_id"],
        )
    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        raise InvalidDocumentsCursorError() from error


def _snapshot_from_mapping(row: Any) -> DocumentSnapshot:
    return DocumentSnapshot(
        snapshot_id=row["id"],
        user_id=row["user_id"],
        limit=row["page_limit"],
        snapshot_cutoff=row["snapshot_cutoff"],
        expires_at=row["expires_at"],
        snapshot_max_id=row["max_document_id"],
        snapshot_total=row["total_count"],
    )


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(
        f"{value}{padding}", altchars=b"-_", validate=True
    )
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded
