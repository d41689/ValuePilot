from __future__ import annotations

import os
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Iterable, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.stocks import Stock, StockPrice


ET = ZoneInfo("America/New_York")


class MarketDataProvider(Protocol):
    """
    Fetch daily (EOD) OHLCV for the given symbols and target trading date.
    Returns a dict keyed by symbol. Missing symbols simply don't appear in the result.
    """
    name: str

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, float]]:
        ...


class NullProvider:
    name = "unconfigured"

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, float]]:
        return {}


class YFinanceProvider:
    """
    Development-friendly provider. Uses the public Yahoo Finance chart endpoint (best-effort).
    Not exchange-authorized, may be rate-limited. Suitable for dev / fallback only.
    """
    name = "yfinance"

    def __init__(self, timeout_s: int = 10):
        self._timeout_s = timeout_s

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        # Yahoo chart API expects unix seconds. Request small window and pick bar matching target_date.
        start_dt = int(time.mktime(target_date.timetuple()))
        end_dt = start_dt + 60 * 60 * 24 * 2

        for sym in symbols:
            try:
                qsym = urllib.parse.quote(sym, safe="")
                url = (
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{qsym}"
                    f"?period1={start_dt}&period2={end_dt}&interval=1d"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))

                chart = (payload.get("chart") or {}).get("result") or []
                if not chart:
                    continue
                r0 = chart[0]
                timestamps = r0.get("timestamp") or []
                ind = ((r0.get("indicators") or {}).get("quote") or [])
                if not timestamps or not ind:
                    continue

                quote0 = ind[0]
                opens = quote0.get("open") or []
                highs = quote0.get("high") or []
                lows = quote0.get("low") or []
                closes = quote0.get("close") or []
                vols = quote0.get("volume") or []

                for i, ts in enumerate(timestamps):
                    d = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET).date()
                    if d != target_date:
                        continue
                    c = closes[i] if i < len(closes) else None
                    if c is None:
                        continue
                    o = opens[i] if i < len(opens) else c
                    h = highs[i] if i < len(highs) else c
                    l = lows[i] if i < len(lows) else c
                    v = vols[i] if i < len(vols) else 0
                    out[sym] = {
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c),
                        "volume": float(v),
                    }
                    break
            except Exception:
                # best-effort fallback: ignore per-symbol failures
                continue

        return out


class TwelveDataProvider:
    """
    API-key provider. Uses Twelve Data 'time_series' daily endpoint (best-effort).
    """
    name = "twelvedata"

    def __init__(self, api_key: str, timeout_s: int = 10):
        self._api_key = api_key
        self._timeout_s = timeout_s

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        if not symbols:
            return out

        # Request daily bars; pick row matching target_date.
        symbols_csv = ",".join(symbols)
        start = target_date.isoformat()
        end = target_date.isoformat()
        qsym = urllib.parse.quote(symbols_csv, safe=",")
        url = (
            "https://api.twelvedata.com/time_series"
            f"?symbol={qsym}&interval=1day&start_date={start}&end_date={end}"
            f"&apikey={urllib.parse.quote(self._api_key, safe='')}&format=JSON"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ValuePilot/1.0"})
        with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        def parse_one(sym: str, obj: dict) -> Optional[Dict[str, float]]:
            values = obj.get("values") or []
            for row in values:
                if row.get("datetime") == target_date.isoformat():
                    try:
                        return {
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row.get("volume") or 0),
                        }
                    except Exception:
                        return None
            return None

        if "values" in payload:
            # single symbol shape
            sym = payload.get("meta", {}).get("symbol") or (symbols[0] if symbols else "")
            one = parse_one(sym, payload)
            if one and sym:
                out[sym] = one
        else:
            # multi-symbol-ish shape
            container = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            for sym in symbols:
                obj = container.get(sym)
                if not isinstance(obj, dict):
                    continue
                one = parse_one(sym, obj)
                if one:
                    out[sym] = one

        return out


class FallbackProvider:
    """
    Try primary provider first; for any missing symbols, try secondary.
    """
    name = "fallback"

    def __init__(self, primary: MarketDataProvider, secondary: MarketDataProvider):
        self.primary = primary
        self.secondary = secondary

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, float]]:
        if not symbols:
            return {}
        data = self.primary.fetch_daily(symbols, target_date) or {}
        missing = [s for s in symbols if s not in data]
        if missing:
            data2 = self.secondary.fetch_daily(missing, target_date) or {}
            data.update(data2)
        return data


def _build_provider(kind: str) -> MarketDataProvider:
    k = (kind or "").strip().lower()
    if k in ("", "none", "null", "unconfigured"):
        return NullProvider()
    if k in ("yfinance", "yahoo"):
        return YFinanceProvider()
    if k in ("twelvedata", "twelve_data", "12data"):
        api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
        if not api_key:
            return NullProvider()
        return TwelveDataProvider(api_key=api_key)
    return NullProvider()


def get_default_provider() -> MarketDataProvider:
    """
    Provider selection is config-driven.
    - MARKET_DATA_PRIMARY: twelvedata | yfinance | none
    - MARKET_DATA_SECONDARY: twelvedata | yfinance | none
    - TWELVE_DATA_API_KEY: required if using twelvedata
    Defaults:
      primary = twelvedata (if API key present else yfinance)
      secondary = yfinance
    """
    primary_kind = os.getenv("MARKET_DATA_PRIMARY", "").strip().lower()
    secondary_kind = os.getenv("MARKET_DATA_SECONDARY", "").strip().lower()

    if not primary_kind:
        primary_kind = "twelvedata" if os.getenv("TWELVE_DATA_API_KEY") else "yfinance"
    if not secondary_kind:
        secondary_kind = "yfinance"

    primary = _build_provider(primary_kind)
    secondary = _build_provider(secondary_kind)

    if getattr(primary, "name", "") == "unconfigured":
        return secondary
    if getattr(secondary, "name", "") == "unconfigured":
        return primary
    if getattr(primary, "name", "") == getattr(secondary, "name", ""):
        return primary

    return FallbackProvider(primary=primary, secondary=secondary)


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
    open_time: dt_time = dt_time(9, 30),
    close_buffer_time: dt_time = dt_time(16, 30),
) -> date:
    today = now_et.date()
    if today.weekday() >= 5:
        return _previous_business_day(today)
    if now_et.time() < close_buffer_time:
        return _previous_business_day(today)
    return today


class MarketDataService:
    def __init__(
        self,
        db: Session,
        *,
        provider: Optional[MarketDataProvider] = None,
        throttle_minutes: int = 10,
        open_time: dt_time = dt_time(9, 30),
        close_buffer_time: dt_time = dt_time(16, 30),
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

            data = {}
            if hasattr(self.provider, "fetch_daily"):
                data = self.provider.fetch_daily([stock.ticker], target_date) or {}
            elif hasattr(self.provider, "fetch_daily_bar"):
                bar = self.provider.fetch_daily_bar(
                    ticker=stock.ticker,
                    exchange=stock.exchange,
                    target_date=target_date,
                )
                if isinstance(bar, dict):
                    data = {stock.ticker: bar}
                elif bar is not None:
                    data = {
                        stock.ticker: {
                            "open": float(getattr(bar, "open", 0.0)),
                            "high": float(getattr(bar, "high", 0.0)),
                            "low": float(getattr(bar, "low", 0.0)),
                            "close": float(getattr(bar, "close", 0.0)),
                            "volume": float(getattr(bar, "volume", 0.0)),
                        }
                    }

            symbol_key = stock.ticker
            payload = data.get(symbol_key) or data.get(symbol_key.upper()) or data.get(symbol_key.lower())
            if not payload:
                results.append(
                    {
                        "stock_id": stock_id,
                        "status": "failed",
                        "reason": "provider_no_data",
                        "target_date": target_date.isoformat(),
                    }
                )
                continue

            self.db.add(
                StockPrice(
                    stock_id=stock.id,
                    price_date=target_date,
                    open=float(payload["open"]),
                    high=float(payload["high"]),
                    low=float(payload["low"]),
                    close=float(payload["close"]),
                    adj_close=float(payload["adj_close"]) if payload.get("adj_close") is not None else None,
                    volume=int(payload["volume"]) if payload.get("volume") is not None else None,
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
