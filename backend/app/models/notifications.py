from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base


class ManagerFollow(Base):
    __tablename__ = "manager_follows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    manager_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("institution_managers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "manager_id", name="uq_manager_follows_user_manager"),
        Index("ix_manager_follows_user_created", "user_id", "created_at"),
    )


class NotificationDestination(Base):
    __tablename__ = "notification_destinations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    destination_hint: Mapped[str] = mapped_column(String(240), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="disabled")
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error_class: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    verification_challenges: Mapped[list["NotificationEmailChallenge"]] = relationship(
        back_populates="destination", order_by="NotificationEmailChallenge.created_at.desc()"
    )

    __table_args__ = (
        CheckConstraint("channel IN ('slack', 'email')", name="ck_notification_destinations_channel"),
        CheckConstraint(
            "status IN ('pending_verification', 'enabled', 'disabled', "
            "'configuration_blocked', 'revoked')",
            name="ck_notification_destinations_status",
        ),
        Index("ix_notification_destinations_user_status", "user_id", "status", "channel"),
    )


class NotificationEmailChallenge(Base):
    __tablename__ = "notification_email_challenges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    destination_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notification_destinations.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    destination: Mapped[NotificationDestination] = relationship(
        back_populates="verification_challenges"
    )


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_family: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("notification_destinations.id", ondelete="CASCADE")
    )
    frequency: Mapped[str] = mapped_column(String(24), nullable=False, default="immediate")
    legacy_frequency_before_in_app_normalization: Mapped[Optional[str]] = mapped_column(
        String(24)
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    quiet_start_local: Mapped[Optional[str]] = mapped_column(String(5))
    quiet_end_local: Mapped[Optional[str]] = mapped_column(String(5))
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    threshold_ratio: Mapped[Optional[float]] = mapped_column(Numeric(8, 6))
    hysteresis_ratio: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, default=0.02
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    destination: Mapped[Optional[NotificationDestination]] = relationship()

    __table_args__ = (
        CheckConstraint(
            "frequency IN ('immediate', 'daily_digest', 'weekly_digest')",
            name="ck_notification_subscriptions_frequency",
        ),
        CheckConstraint(
            "destination_id IS NOT NULL OR frequency = 'immediate'",
            name="ck_notification_subscriptions_in_app_immediate",
        ),
        CheckConstraint(
            "cooldown_minutes BETWEEN 0 AND 43200",
            name="ck_notification_subscriptions_cooldown",
        ),
        CheckConstraint(
            "threshold_ratio IS NULL OR threshold_ratio BETWEEN 0 AND 0.95",
            name="ck_notification_subscriptions_threshold_ratio",
        ),
        CheckConstraint(
            "hysteresis_ratio BETWEEN 0 AND 0.25",
            name="ck_notification_subscriptions_hysteresis_ratio",
        ),
        Index(
            "uq_notification_subscriptions_in_app",
            "user_id",
            "event_family",
            unique=True,
            postgresql_where=text("destination_id IS NULL"),
        ),
        Index(
            "uq_notification_subscriptions_destination",
            "user_id",
            "event_family",
            "destination_id",
            unique=True,
            postgresql_where=text("destination_id IS NOT NULL"),
        ),
    )


class LogicalNotification(Base):
    __tablename__ = "logical_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_family: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(240), nullable=False)
    logical_key: Mapped[str] = mapped_column(String(360), nullable=False)
    source_version: Mapped[str] = mapped_column(String(240), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    correction_type: Mapped[str] = mapped_column(String(24), nullable=False, default="original")
    supersedes_notification_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("logical_notifications.id", ondelete="RESTRICT")
    )
    case_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_cases.id", ondelete="SET NULL")
    )
    stock_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("stocks.id", ondelete="SET NULL")
    )
    manager_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("institution_managers.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_route: Mapped[str] = mapped_column(String(500), nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "logical_key", "source_version",
            name="uq_logical_notifications_source",
        ),
        CheckConstraint(
            "correction_type IN ('original', 'correction')",
            name="ck_logical_notifications_correction_type",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_logical_notifications_severity",
        ),
        Index("ix_logical_notifications_user_created", "user_id", "created_at"),
        Index("ix_logical_notifications_subject", "event_family", "subject_key", "created_at"),
    )


class NotificationInboxState(Base):
    __tablename__ = "notification_inbox_states"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    logical_notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("logical_notifications.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "logical_notification_id",
            name="uq_notification_inbox_states_notification",
        ),
        Index(
            "ix_notification_inbox_states_user_read",
            "user_id",
            "read_at",
            "dismissed_at",
        ),
    )


class NotificationDeliveryAttempt(Base):
    __tablename__ = "notification_delivery_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    logical_notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("logical_notifications.id", ondelete="CASCADE"), nullable=False
    )
    destination_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notification_destinations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    provider_response_class: Mapped[Optional[str]] = mapped_column(String(100))
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    succeeded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    destination: Mapped[NotificationDestination] = relationship()
    notification: Mapped[LogicalNotification] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "logical_notification_id", "destination_id", "content_version",
            name="uq_notification_delivery_idempotency",
        ),
        CheckConstraint(
            "status IN ('queued', 'leased', 'retry_scheduled', 'succeeded', "
            "'permanent_failure', 'configuration_blocked')",
            name="ck_notification_delivery_attempts_status",
        ),
        Index("ix_notification_delivery_due", "status", "next_attempt_at"),
    )


class NotificationDeliveryEvent(Base):
    __tablename__ = "notification_delivery_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notification_delivery_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    response_class: Mapped[Optional[str]] = mapped_column(String(100))
    payload_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_notification_delivery_events_attempt_created", "attempt_id", "created_at"),
    )


class NotificationPriceAlertState(Base):
    __tablename__ = "notification_price_alert_states"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False
    )
    last_price_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("stock_prices.id", ondelete="SET NULL")
    )
    last_valuation_fact_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("metric_facts.id", ondelete="SET NULL")
    )
    last_research_revision_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("research_case_revisions.id", ondelete="SET NULL")
    )
    last_threshold_ratio: Mapped[Optional[float]] = mapped_column(Numeric(8, 6))
    last_hysteresis_ratio: Mapped[Optional[float]] = mapped_column(Numeric(8, 6))
    last_side: Mapped[Optional[str]] = mapped_column(String(16))
    consecutive_fresh_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "stock_id", name="uq_notification_price_alert_states_user_stock"),
        CheckConstraint(
            "last_side IS NULL OR last_side IN ('above', 'below')",
            name="ck_notification_price_alert_states_side",
        ),
    )
