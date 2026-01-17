from datetime import datetime
from typing import Any
from sqlalchemy import String, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    notification_settings: Mapped["NotificationSettings"] = relationship(back_populates="user", uselist=False)
    notification_events: Mapped[list["NotificationEvent"]] = relationship(back_populates="user")
    
    # Other relationships will be added in their respective files or via back_populates strings
    # to avoid circular imports, but we can define the other side here if needed.
    # stocks (via ownership? No, stocks are global)
    # stock_pools: Mapped[list["StockPool"]] = relationship(back_populates="user")
    # pdf_documents: Mapped[list["PdfDocument"]] = relationship(back_populates="user")

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
