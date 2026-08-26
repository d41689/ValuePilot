from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.api_security import ApiRateLimitEvent
from app.models.notifications import NotificationDestination


def _consume_limit(
    db_session,
    *,
    user_id: int,
    operation: str,
    count: int,
    now: datetime | None = None,
) -> None:
    occurred_at = now or datetime.now(timezone.utc)
    db_session.add_all(
        [
            ApiRateLimitEvent(
                user_id=user_id,
                operation=operation,
                occurred_at=occurred_at - timedelta(seconds=index),
            )
            for index in range(count)
        ]
    )
    db_session.commit()


def test_expensive_operations_are_rate_limited_per_user_before_work_starts(
    client, db_session, user_factory, auth_headers
):
    limited = user_factory("limited-operations@example.com")
    other = user_factory("other-operations@example.com")
    _consume_limit(
        db_session,
        user_id=limited.id,
        operation="coverage_price_refresh",
        count=6,
    )

    denied = client.post(
        "/api/v1/coverage/refresh-prices?as_of=2026-07-17",
        headers=auth_headers(limited),
    )
    allowed = client.post(
        "/api/v1/coverage/refresh-prices?as_of=2026-07-17",
        headers=auth_headers(other),
    )

    assert denied.status_code == 429
    assert int(denied.headers["retry-after"]) > 0
    assert denied.json()["detail"]["code"] == "rate_limit_exceeded"
    assert allowed.status_code == 200, allowed.text


def test_pdf_upload_has_size_cap_and_durable_user_rate_limit(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("limited-upload@example.com")
    headers = auth_headers(user)

    with patch("app.api.v1.endpoints.documents.MAX_PDF_UPLOAD_BYTES", 16):
        oversized = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("large.pdf", b"%PDF" + b"x" * 20, "application/pdf")},
        )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "pdf_too_large"

    _consume_limit(
        db_session,
        user_id=user.id,
        operation="document_upload",
        count=20,
    )
    with patch("app.api.v1.endpoints.documents.IngestionService.process_upload") as ingest:
        denied = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("small.pdf", b"%PDF-1.4", "application/pdf")},
        )
    assert denied.status_code == 429
    ingest.assert_not_called()


def test_destination_verification_and_delivery_test_have_abuse_limits(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("limited-notifications@example.com")
    destination = NotificationDestination(
        user_id=user.id,
        channel="email",
        label="Private email",
        destination_hint="m***@example.com",
        secret_ciphertext="not-read-before-limit",
        key_version="v1",
        status="pending_verification",
        consented_at=datetime.now(timezone.utc),
    )
    db_session.add(destination)
    db_session.commit()

    _consume_limit(
        db_session,
        user_id=user.id,
        operation="destination_verification",
        count=10,
    )
    denied_verify = client.post(
        f"/api/v1/notifications/destinations/{destination.id}/verify-email",
        headers=auth_headers(user),
        json={"token": "a-valid-length-token"},
    )
    assert denied_verify.status_code == 429

    destination.channel = "slack"
    destination.status = "enabled"
    db_session.commit()
    _consume_limit(
        db_session,
        user_id=user.id,
        operation="destination_delivery_test",
        count=3,
    )
    denied_test = client.post(
        f"/api/v1/notifications/destinations/{destination.id}/test",
        headers=auth_headers(user),
        json={"confirm_send": True},
    )
    assert denied_test.status_code == 429
    assert "not-read-before-limit" not in denied_test.text
