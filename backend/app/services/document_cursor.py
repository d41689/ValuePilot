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

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.artifacts import (
    DocumentListSnapshot,
    DocumentListSnapshotMember,
    PdfDocument,
)
from app.services.privacy_erasure import lock_user_privacy_write


CURSOR_VERSION = 2
MAX_DOCUMENT_CURSOR_LENGTH = 4096
MAX_DOCUMENT_SNAPSHOT_MEMBERS = 5000
DOCUMENT_SNAPSHOT_TTL_MINUTES = 15
MAX_ACTIVE_DOCUMENT_SNAPSHOTS_PER_USER = 8
DOCUMENT_SNAPSHOT_CLEANUP_BATCH = 16
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


class DocumentsSnapshotCapacityExceededError(ValueError):
    code = "documents_snapshot_capacity_exceeded"

    def __init__(self) -> None:
        super().__init__("Too many active document traversals; reuse a cursor or retry later.")


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
    visibility_snapshot: str


@dataclass(frozen=True)
class DocumentSnapshotRow:
    ordinal: int
    document: PdfDocument
    upload_time: datetime | None
    report_date: Any | None


def create_document_snapshot(
    session: Session,
    *,
    user_id: int,
    limit: int,
) -> DocumentSnapshot:
    """Capture exact membership and immutable sort keys in one SQL statement."""

    lock_user_privacy_write(session, user_id=user_id)
    # Serialize capacity/reuse decisions for this tenant in PostgreSQL.  The
    # key namespace is stable and deliberately distinct from other advisory
    # lock users in the application.
    session.execute(
        text("SELECT pg_advisory_xact_lock(1448097360,:user_id)"),
        {"user_id": user_id},
    )
    session.execute(
        text(
            "WITH doomed AS (SELECT id FROM document_list_snapshots "
            "WHERE user_id=:user_id AND expires_at<=clock_timestamp() "
            "ORDER BY expires_at,id LIMIT :cleanup_limit FOR UPDATE) "
            "DELETE FROM document_list_snapshots s USING doomed d WHERE s.id=d.id"
        ),
        {"user_id": user_id, "cleanup_limit": DOCUMENT_SNAPSHOT_CLEANUP_BATCH},
    )
    snapshot_id = secrets.token_urlsafe(32)
    row = session.execute(
        text(
            """
            WITH snapshot_clock AS MATERIALIZED (
              SELECT clock_timestamp() AS cutoff
            ), raw_candidates AS MATERIALIZED (
              SELECT d.id AS document_id,d.upload_time,d.source,
                     report_identity.report_date
              FROM pdf_documents d CROSS JOIN snapshot_clock sc
              LEFT JOIN LATERAL (
                SELECT r.report_date
                FROM value_line_document_report_identity_revisions r
                WHERE r.document_id=d.id AND r.known_at<=sc.cutoff
                ORDER BY r.known_at DESC,r.id DESC LIMIT 1
              ) report_identity ON true
              WHERE d.user_id=:user_id
              ORDER BY d.upload_time DESC NULLS LAST,d.id DESC
              LIMIT :candidate_limit
            ), candidates AS MATERIALIZED (
              SELECT row_number() OVER (
                       ORDER BY upload_time DESC NULLS LAST,document_id DESC
                     )::integer AS ordinal,
                     document_id,upload_time,source,report_date
              FROM raw_candidates
            ), candidate_stats AS MATERIALIZED (
              SELECT count(*)::integer AS candidate_count,
                     COALESCE(max(document_id),0)::bigint AS max_document_id,
                     md5(COALESCE(string_agg(
                       document_id::text || ':' || COALESCE(upload_time::text,'NULL') ||
                       ':' || source || ':' || COALESCE(report_date::text,'NULL'),
                       ',' ORDER BY ordinal
                     ),'')) AS membership_fingerprint
              FROM candidates
            ), reusable AS MATERIALIZED (
              SELECT s.*
              FROM document_list_snapshots s
              CROSS JOIN candidate_stats cs CROSS JOIN snapshot_clock sc
              WHERE s.user_id=:user_id
                AND s.page_limit=:page_limit
                AND s.expires_at>sc.cutoff
                AND s.membership_fingerprint=cs.membership_fingerprint
                AND s.total_count=LEAST(cs.candidate_count,:max_members)
              ORDER BY s.created_at DESC,s.id DESC LIMIT 1
            ), capacity AS MATERIALIZED (
              SELECT count(*)::integer AS active_count
              FROM document_list_snapshots s CROSS JOIN snapshot_clock sc
              WHERE s.user_id=:user_id AND s.expires_at>sc.cutoff
            ), new_snapshot AS (
              INSERT INTO document_list_snapshots
                (id,user_id,page_limit,total_count,max_document_id,
                 snapshot_cutoff,expires_at,membership_fingerprint)
              SELECT :snapshot_id,:user_id,:page_limit,
                     LEAST(candidate_count,:max_members),max_document_id,
                     cutoff,cutoff,membership_fingerprint
              FROM snapshot_clock CROSS JOIN candidate_stats CROSS JOIN capacity
              WHERE NOT EXISTS (SELECT 1 FROM reusable)
                AND capacity.active_count<:max_active_snapshots
              RETURNING id,user_id,page_limit,total_count,max_document_id,
                        snapshot_cutoff,expires_at,membership_fingerprint,
                        visibility_snapshot
            ), chosen AS MATERIALIZED (
              SELECT r.id,r.user_id,r.page_limit,r.total_count,r.max_document_id,
                     r.snapshot_cutoff,r.expires_at,r.visibility_snapshot,
                     false AS was_created
              FROM reusable r
              UNION ALL
              SELECT n.id,n.user_id,n.page_limit,n.total_count,n.max_document_id,
                     n.snapshot_cutoff,n.expires_at,n.visibility_snapshot,
                     true AS was_created
              FROM new_snapshot n
            ), inserted_members AS (
              INSERT INTO document_list_snapshot_members
                (snapshot_id,ordinal,document_id,upload_time,source,report_date)
              SELECT n.id,c.ordinal,c.document_id,c.upload_time,c.source,c.report_date
              FROM new_snapshot n CROSS JOIN candidates c
              CROSS JOIN candidate_stats s
              WHERE s.candidate_count <= :max_members
              RETURNING snapshot_id
            )
            SELECT c.*,s.candidate_count,capacity.active_count,
                   (SELECT count(*) FROM inserted_members) AS inserted_count
            FROM candidate_stats s CROSS JOIN capacity
            LEFT JOIN chosen c ON true
            """
        ),
        {
            "candidate_limit": MAX_DOCUMENT_SNAPSHOT_MEMBERS + 1,
            "max_members": MAX_DOCUMENT_SNAPSHOT_MEMBERS,
            "max_active_snapshots": MAX_ACTIVE_DOCUMENT_SNAPSHOTS_PER_USER,
            "page_limit": limit,
            "snapshot_id": snapshot_id,
            "user_id": user_id,
        },
    ).mappings().one()
    if row["candidate_count"] > MAX_DOCUMENT_SNAPSHOT_MEMBERS:
        session.rollback()
        raise DocumentsSnapshotBoundExceededError()
    if row["id"] is None:
        session.rollback()
        raise DocumentsSnapshotCapacityExceededError()
    if row["was_created"] and row["candidate_count"] != row["inserted_count"]:
        session.rollback()
        raise RuntimeError("document snapshot membership capture was incomplete")
    return _snapshot_from_mapping(row)


def load_document_snapshot(
    session: Session,
    *,
    cursor: DocumentCursor,
) -> DocumentSnapshot:
    lock_user_privacy_write(session, user_id=cursor.user_id)
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
        visibility_snapshot=row.visibility_snapshot,
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
                report_date=retained.report_date,
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
        visibility_snapshot=row["visibility_snapshot"],
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
