from datetime import datetime
from typing import Any, Optional
from sqlalchemy import BigInteger, String, DateTime, Boolean, ForeignKey, Integer, JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    # Valid bcrypt hash for "changeme" used when code paths construct users
    # without explicit password data (mainly legacy tests/fixtures).
    DEFAULT_PASSWORD_HASH = "$2b$12$LVEe4wavqLSPDBAY4uf9mO4HOBPJLmP4l2Kuf.8Kn6hS2lbBmRz6S"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False, default=DEFAULT_PASSWORD_HASH)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default="user")
    tier: Mapped[str] = mapped_column(String, nullable=False, server_default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    notification_settings: Mapped["NotificationSettings"] = relationship(back_populates="user", uselist=False)
    notification_events: Mapped[list["NotificationEvent"]] = relationship(back_populates="user")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_premium(self) -> bool:
        return self.tier == "premium"

class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    channel: Mapped[str] = mapped_column(String, default="email")
    frequency: Mapped[str] = mapped_column(String, default="daily_summary")
    send_time_local: Mapped[str] = mapped_column(String) # HH:MM
    timezone: Mapped[str] = mapped_column(String)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="notification_settings")

class NotificationEvent(Base):
    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String) # daily_summary / threshold_hit
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="notification_events")


class AccountErasureEvent(Base):
    """Append-only, non-content proof of a completed privacy transaction."""

    __tablename__ = "account_erasure_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )


class AccountErasureFileDeletion(Base):
    """Durable, retryable deletion of storage after the DB erasure commits."""

    __tablename__ = "account_erasure_file_deletions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("pdf_documents.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_class: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_txid: Mapped[int] = mapped_column(
        BigInteger, server_default=func.txid_current(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
