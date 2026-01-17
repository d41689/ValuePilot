from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Integer, Float, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.db import Base

if TYPE_CHECKING:
    from app.models.users import User

class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    exchange: Mapped[str] = mapped_column(String, index=True)
    company_name: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    prices: Mapped[list["StockPrice"]] = relationship(back_populates="stock")

class StockPrice(Base):
    __tablename__ = "stock_prices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    price_date: Mapped[date] = mapped_column(Date)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="prices")

class StockPool(Base):
    __tablename__ = "stock_pools"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    memberships: Mapped[list["PoolMembership"]] = relationship(back_populates="pool")
    user: Mapped["User"] = relationship("User")

class PoolMembership(Base):
    __tablename__ = "pool_memberships"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    pool_id: Mapped[int] = mapped_column(ForeignKey("stock_pools.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    inclusion_type: Mapped[str] = mapped_column(String) # manual / rule
    rule_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pool: Mapped["StockPool"] = relationship(back_populates="memberships")
    stock: Mapped["Stock"] = relationship("Stock")

class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    pool_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stock_pools.id"), nullable=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"))
    target_price: Mapped[float] = mapped_column(Float)
    tolerance_pct: Mapped[float] = mapped_column(Float)
    cooldown_hours: Mapped[int] = mapped_column(Integer)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    stock: Mapped["Stock"] = relationship("Stock")
    pool: Mapped[Optional["StockPool"]] = relationship("StockPool")
    user: Mapped["User"] = relationship("User")