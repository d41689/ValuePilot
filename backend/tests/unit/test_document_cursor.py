from datetime import datetime, timezone

import pytest

from app.services.document_cursor import (
    DocumentCursor,
    InvalidDocumentsCursorError,
    decode_document_cursor,
    encode_document_cursor,
)


def test_document_cursor_round_trips_null_upload_time() -> None:
    cursor = DocumentCursor(
        user_id=17,
        limit=25,
        snapshot_id="snapshot-id-with-at-least-thirty-two-characters",
        last_ordinal=11,
        last_upload_time=None,
        last_id=12,
    )

    assert decode_document_cursor(
        encode_document_cursor(cursor),
        user_id=17,
    ) == cursor


def test_document_cursor_rejects_noncanonical_signature_encoding() -> None:
    cursor = DocumentCursor(
        user_id=17,
        limit=25,
        snapshot_id="snapshot-id-with-at-least-thirty-two-characters",
        last_ordinal=11,
        last_upload_time=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        last_id=12,
    )
    token = encode_document_cursor(cursor)
    payload, signature = token.split(".")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    index = alphabet.index(signature[-1])
    # The final base64url character for a 32-byte HMAC has two unused bits.
    # Changing only one of those bits decodes to the same signature bytes, but
    # must not provide a second accepted spelling of a signed cursor.
    alternate = alphabet[index ^ 1]
    noncanonical = f"{payload}.{signature[:-1]}{alternate}"

    with pytest.raises(InvalidDocumentsCursorError):
        decode_document_cursor(noncanonical, user_id=17)


def test_document_cursor_rejects_oversized_input() -> None:
    with pytest.raises(InvalidDocumentsCursorError):
        decode_document_cursor("A" * 4097, user_id=17)
