from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base


RATE_LIMIT_OPERATIONS = (
    "coverage_price_refresh",
    "document_upload",
    "destination_verification",
    "destination_delivery_test",
)


class ApiRateLimitEvent(Base):
    """Minimal durable audit used to enforce user-scoped expensive-operation limits."""

    __tablename__ = "api_rate_limit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "operation IN ("
            "'coverage_price_refresh', 'document_upload', "
            "'destination_verification', 'destination_delivery_test'"
            ")",
            name="ck_api_rate_limit_events_operation",
        ),
        Index(
            "ix_api_rate_limit_events_user_operation_time",
            "user_id",
            "operation",
            "occurred_at",
        ),
    )
