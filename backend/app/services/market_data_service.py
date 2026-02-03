from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Iterable, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.stocks import Stock, StockPrice


ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DailyBar:
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None
    adj_close: Optional[float] = None


class MarketDataProvider:
    name = "unconfigured"

    def fetch_daily_bar(
        self,
        *,
        ticker: str,
        exchange: str,
        target_date: date,
    ) -> Optional[DailyBar]:
        return None


def get_default_provider() -> MarketDataProvider:
    return MarketDataProvider()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _previous_business_day(day: date) -> date:
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def compute_target_date(
    now_et: datetime,
    *,
    open_time: time = time(9, 30),
    close_buffer_time: time = time(16, 30),
) -> date:
    today = now_et.date()
    if today.weekday() >= 5:
        return _previous_business_day(today)
    if now_et.time() < close_buffer_time:
        return _previous_business_day(today)
    if today.weekday() == 0 and now_et.time() < open_time:
        return _previous_business_day(today)
    return today


class MarketDataService:
    def __init__(
        self,
        db: Session,
        *,
        provider: Optional[MarketDataProvider] = None,
        throttle_minutes: int = 10,
        open_time: time = time(9, 30),
        close_buffer_time: time = time(16, 30),
    ) -> None:
        self.db = db
        self.provider = provider or get_default_provider()
        self.throttle_minutes = throttle_minutes
        self.open_time = open_time
        self.close_buffer_time = close_buffer_time

    def refresh_stock_prices(
        self,
        stock_ids: Iterable[int],
        *,
        reason: str,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        now_utc = _ensure_utc(now or datetime.now(timezone.utc))
        now_et = now_utc.astimezone(ET)
        target_date = compute_target_date(
            now_et,
            open_time=self.open_time,
            close_buffer_time=self.close_buffer_time,
        )
        close_buffer_dt = datetime.combine(target_date, self.close_buffer_time, tzinfo=ET)

        for stock_id in stock_ids:
            stock = self.db.get(Stock, stock_id)
            if not stock:
                results.append(
                    {
                        "stock_id": stock_id,
                        "status": "failed",
                        "reason": "stock_not_found",
                        "target_date": target_date.isoformat(),
                    }
                )
                continue

            latest_any = self.db.scalars(
                select(StockPrice)
                .where(StockPrice.stock_id == stock_id)
                .order_by(StockPrice.created_at.desc())
                .limit(1)
            ).first()
            if latest_any and latest_any.created_at:
                latest_any_utc = _ensure_utc(latest_any.created_at)
                if now_utc - latest_any_utc < timedelta(minutes=self.throttle_minutes):
                    results.append(
                        {
                            "stock_id": stock_id,
                            "status": "skipped",
                            "reason": "throttled",
                            "target_date": target_date.isoformat(),
                        }
                    )
                    continue

            latest_target = self.db.scalars(
                select(StockPrice)
                .where(
                    StockPrice.stock_id == stock_id,
                    StockPrice.price_date == target_date,
                )
                .order_by(StockPrice.created_at.desc())
                .limit(1)
            ).first()

            should_refresh = latest_target is None
            if latest_target is not None:
                created_at = latest_target.created_at
                created_et = _ensure_utc(created_at).astimezone(ET) if created_at else None
                if now_et >= close_buffer_dt and created_et and created_et < close_buffer_dt:
                    should_refresh = True
                else:
                    should_refresh = False

            if not should_refresh:
                results.append(
                    {
                        "stock_id": stock_id,
                        "status": "skipped",
                        "reason": "up_to_date",
                        "target_date": target_date.isoformat(),
                    }
                )
                continue

            bar = self.provider.fetch_daily_bar(
                ticker=stock.ticker,
                exchange=stock.exchange,
                target_date=target_date,
            )
            if bar is None:
                results.append(
                    {
                        "stock_id": stock_id,
                        "status": "failed",
                        "reason": "provider_no_data",
                        "target_date": target_date.isoformat(),
                    }
                )
                continue

            bar_obj = bar
            if isinstance(bar, dict):
                bar_obj = DailyBar(
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    volume=int(bar["volume"]) if bar.get("volume") is not None else None,
                    adj_close=float(bar["adj_close"]) if bar.get("adj_close") is not None else None,
                )

            self.db.add(
                StockPrice(
                    stock_id=stock.id,
                    price_date=target_date,
                    open=bar_obj.open,
                    high=bar_obj.high,
                    low=bar_obj.low,
                    close=bar_obj.close,
                    adj_close=bar_obj.adj_close,
                    volume=bar_obj.volume,
                    source=getattr(self.provider, "name", "provider"),
                    created_at=now_utc,
                )
            )
            results.append(
                {
                    "stock_id": stock_id,
                    "status": "refreshed",
                    "reason": reason,
                    "target_date": target_date.isoformat(),
                }
            )

        self.db.commit()
        return results
