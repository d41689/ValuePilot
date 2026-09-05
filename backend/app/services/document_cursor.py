"""Signed, tenant-bound keyset cursor for a stable document-list snapshot."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
import re

from app.core.config import settings


CURSOR_VERSION = 1
MAX_DOCUMENT_CURSOR_LENGTH = 4096
INVALID_DOCUMENTS_CURSOR = "invalid_documents_cursor"


class InvalidDocumentsCursorError(ValueError):
    code = INVALID_DOCUMENTS_CURSOR

    def __init__(self) -> None:
        super().__init__("The documents cursor is invalid for this request.")


@dataclass(frozen=True)
class DocumentCursor:
    user_id: int
    limit: int
    snapshot_cutoff: datetime
    snapshot_visibility: str
    snapshot_max_id: int
    snapshot_total: int
    last_upload_time: datetime | None
    last_id: int


def encode_document_cursor(cursor: DocumentCursor) -> str:
    payload = {
        "last_id": cursor.last_id,
        "last_upload_time": (
            cursor.last_upload_time.isoformat()
            if cursor.last_upload_time is not None
            else None
        ),
        "limit": cursor.limit,
        "snapshot_cutoff": cursor.snapshot_cutoff.isoformat(),
        "snapshot_visibility": cursor.snapshot_visibility,
        "snapshot_max_id": cursor.snapshot_max_id,
        "snapshot_total": cursor.snapshot_total,
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
            "last_upload_time",
            "limit",
            "snapshot_cutoff",
            "snapshot_visibility",
            "snapshot_max_id",
            "snapshot_total",
            "user_id",
            "version",
        }:
            raise ValueError
        if payload["version"] != CURSOR_VERSION:
            raise ValueError
        values = (
            payload["user_id"],
            payload["limit"],
            payload["snapshot_max_id"],
            payload["snapshot_total"],
            payload["last_id"],
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError
        if (
            payload["user_id"] != user_id
            or not 1 <= payload["limit"] <= 500
            or payload["snapshot_max_id"] < 0
            or payload["snapshot_total"] < 0
            or payload["last_id"] <= 0
            or payload["last_id"] > payload["snapshot_max_id"]
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
        raw_cutoff = payload["snapshot_cutoff"]
        if not isinstance(raw_cutoff, str):
            raise ValueError
        snapshot_cutoff = datetime.fromisoformat(raw_cutoff)
        if snapshot_cutoff.utcoffset() is None:
            raise ValueError
        snapshot_visibility = payload["snapshot_visibility"]
        if (
            not isinstance(snapshot_visibility, str)
            or len(snapshot_visibility) > 2048
            or re.fullmatch(
                r"[0-9]+:[0-9]+:(?:[0-9]+(?:,[0-9]+)*)?",
                snapshot_visibility,
            )
            is None
        ):
            raise ValueError
        return DocumentCursor(
            user_id=payload["user_id"],
            limit=payload["limit"],
            snapshot_cutoff=snapshot_cutoff,
            snapshot_visibility=snapshot_visibility,
            snapshot_max_id=payload["snapshot_max_id"],
            snapshot_total=payload["snapshot_total"],
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
