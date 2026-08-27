from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.api_security import ApiRateLimitEvent, RATE_LIMIT_OPERATIONS


@dataclass(frozen=True)
class OperationLimit:
    maximum: int
    window: timedelta


OPERATION_LIMITS = {
    "coverage_price_refresh": OperationLimit(6, timedelta(hours=1)),
    "document_upload": OperationLimit(20, timedelta(hours=1)),
    "destination_verification": OperationLimit(10, timedelta(minutes=10)),
    "destination_delivery_test": OperationLimit(3, timedelta(minutes=10)),
}


class RateLimitExceeded(Exception):
    def __init__(self, *, operation: str, retry_after_seconds: int):
        super().__init__(f"Rate limit exceeded for {operation}.")
        self.operation = operation
        self.retry_after_seconds = max(retry_after_seconds, 1)


def consume_user_operation(
    session: Session,
    *,
    user_id: int,
    operation: str,
    now: datetime | None = None,
) -> None:
    """Atomically consume one fixed-window user operation allowance.

    The minimal event is committed before expensive work begins, so failed
    validation/provider attempts cannot evade the limit through a rollback.
    A transaction advisory lock serializes concurrent requests for one user and
    operation across API workers.
    """
    if operation not in RATE_LIMIT_OPERATIONS or operation not in OPERATION_LIMITS:
        raise ValueError(f"Unsupported rate-limited operation: {operation}")
    observed_at = now or datetime.now(timezone.utc)
    limit = OPERATION_LIMITS[operation]
    cutoff = observed_at - limit.window
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"api-rate-limit:{user_id}:{operation}"},
    )
    count, oldest = (
        session.query(
            func.count(ApiRateLimitEvent.id),
            func.min(ApiRateLimitEvent.occurred_at),
        )
        .filter(
            ApiRateLimitEvent.user_id == user_id,
            ApiRateLimitEvent.operation == operation,
            ApiRateLimitEvent.occurred_at > cutoff,
        )
        .one()
    )
    if int(count or 0) >= limit.maximum:
        retry_at = (oldest or observed_at) + limit.window
        seconds = int((retry_at - observed_at).total_seconds()) + 1
        session.rollback()
        raise RateLimitExceeded(
            operation=operation,
            retry_after_seconds=seconds,
        )
    session.add(
        ApiRateLimitEvent(
            user_id=user_id,
            operation=operation,
            occurred_at=observed_at,
        )
    )
    session.commit()
