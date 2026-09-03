from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Iterable, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.institutions import Filing13F, Holding13F, InstitutionManager
from app.models.stocks import Stock, StockPrice


ET = ZoneInfo("America/New_York")
PRICE_FRESHNESS_POLICY_VERSION = "eod-freshness-v1.0"
MARKET_CALENDAR_POLICY_VERSION = "us-equity-calendar-v1.0"
PRICE_SOURCE_POLICY_VERSION = "eod-source-authorization-v1.0"
DEFAULT_PRICE_SOURCE_PRIORITY = (
    "twelvedata",
    "licensed_fixture",
    "manual",
    "yfinance",
)
_US_EQUITY_EXCHANGES = {
    "AMEX",
    "ARCA",
    "BATS",
    "IEX",
    "NASDAQ",
    "NASD",
    "NDQ",
    "NYSE",
    "NYSEAMERICAN",
    "US",
    "XNAS",
    "XNYS",
}
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class MarketSessionResolution:
    calendar_code: str | None
    session_date: date | None
    policy_version: str
    reason_code: str | None = None


@dataclass(frozen=True)
class CanonicalEodPrice:
    stock_id: int
    price_id: int | None
    close: float | None
    price_date: date | None
    currency: str | None
    source: str | None
    observed_at: datetime | None
    freshness_state: str
    reason_code: str | None
    expected_session_date: date | None
    calendar_code: str | None
    status: str
    source_authorization_state: str
    as_of_date: date
    as_of_mode: str
    freshness_policy_version: str = PRICE_FRESHNESS_POLICY_VERSION
    calendar_policy_version: str = MARKET_CALENDAR_POLICY_VERSION
    source_policy_version: str = PRICE_SOURCE_POLICY_VERSION

    @property
    def current_value(self) -> float | None:
        """The comparison-safe current value, never merely a stored close."""
        return self.close if self.status == "available" else None


class MarketDataProvider(Protocol):
    """
    Fetch daily (EOD) OHLCV for the given symbols and target trading date.
    Returns a dict keyed by symbol. Missing symbols simply don't appear in the result.
    """
    name: str

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, Any]]:
        ...


class NullProvider:
    name = "unconfigured"

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, Any]]:
        return {}


class YFinanceProvider:
    """
    Development-friendly provider. Uses the public Yahoo Finance chart endpoint (best-effort).
    Not exchange-authorized, may be rate-limited. Suitable for dev / fallback only.
    """
    name = "yfinance"

    def __init__(self, timeout_s: int = 10):
        self._timeout_s = timeout_s

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
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
                currency = str((r0.get("meta") or {}).get("currency") or "").upper()
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
                        "currency": currency or None,
                        "source": self.name,
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

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
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

        def parse_one(sym: str, obj: dict) -> Optional[Dict[str, Any]]:
            currency = str((obj.get("meta") or {}).get("currency") or "").upper()
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
                            "currency": currency or None,
                            "source": self.name,
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

    def fetch_daily(self, symbols: List[str], target_date: date) -> Dict[str, Dict[str, Any]]:
        if not symbols:
            return {}
        data = self.primary.fetch_daily(symbols, target_date) or {}
        missing = [s for s in symbols if s not in data]
        if missing:
            data2 = self.secondary.fetch_daily(missing, target_date) or {}
            data.update(data2)
        return data


from app.core.config import settings

def _build_provider(kind: str) -> MarketDataProvider:
    k = (kind or "").strip().lower()
    if k in ("", "none", "null", "unconfigured"):
        return NullProvider()
    if k in ("yfinance", "yahoo"):
        if not settings.MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER:
            return NullProvider()
        return YFinanceProvider()
    if k in ("twelvedata", "twelve_data", "12data"):
        api_key = settings.TWELVE_DATA_API_KEY
        if not api_key or not settings.MARKET_DATA_COMMERCIAL_ENABLED:
            return NullProvider()
        return TwelveDataProvider(api_key=api_key.strip())
    return NullProvider()


def get_default_provider() -> MarketDataProvider:
    """
    Provider selection is config-driven.
    - MARKET_DATA_PRIMARY: twelvedata | yfinance | none
    - MARKET_DATA_SECONDARY: twelvedata | yfinance | none
    - TWELVE_DATA_API_KEY: required if using twelvedata
    Defaults fail closed. A provider must be named and separately authorized;
    merely finding a credential in an inherited environment is insufficient.
    """
    primary_kind = settings.MARKET_DATA_PRIMARY.strip().lower()
    secondary_kind = settings.MARKET_DATA_SECONDARY.strip().lower()

    if not primary_kind:
        primary_kind = "none"
    if not secondary_kind:
        secondary_kind = "none"

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


def _observed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    current = first_next - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    """Gregorian Easter (Anonymous Gregorian computus)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _us_equity_holidays(year: int) -> set[date]:
    holidays = {
        _observed_holiday(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # MLK Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_holiday(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_holiday(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed_holiday(date(year, 6, 19)))
    return holidays


def _is_us_equity_session(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    # New Year's observance can fall in the adjacent civil year.
    holidays = set().union(
        _us_equity_holidays(day.year - 1),
        _us_equity_holidays(day.year),
        _us_equity_holidays(day.year + 1),
    )
    return day not in holidays


def expected_session_on_or_before(
    exchange: str | None,
    day: date,
) -> MarketSessionResolution:
    normalized = str(exchange or "").upper().replace(" ", "")
    if normalized not in _US_EQUITY_EXCHANGES:
        return MarketSessionResolution(
            calendar_code=None,
            session_date=None,
            policy_version=MARKET_CALENDAR_POLICY_VERSION,
            reason_code="calendar_mapping_unavailable",
        )
    current = day
    while not _is_us_equity_session(current):
        current -= timedelta(days=1)
    return MarketSessionResolution(
        calendar_code="XNYS",
        session_date=current,
        policy_version=MARKET_CALENDAR_POLICY_VERSION,
    )


def _previous_business_day(day: date) -> date:
    resolution = expected_session_on_or_before("XNYS", day - timedelta(days=1))
    assert resolution.session_date is not None
    return resolution.session_date


def _business_day_on_or_before(day: date) -> date:
    resolution = expected_session_on_or_before("XNYS", day)
    assert resolution.session_date is not None
    return resolution.session_date


def compute_target_date(
    now_et: datetime,
    *,
    open_time: dt_time = dt_time(9, 30),
    close_buffer_time: dt_time = dt_time(16, 30),
) -> date:
    today = now_et.date()
    if now_et.time() < close_buffer_time:
        return _previous_business_day(today)
    resolution = expected_session_on_or_before("XNYS", today)
    assert resolution.session_date is not None
    return resolution.session_date


def _currency(value: Any) -> str | None:
    normalized = str(value or "").upper().strip()
    return normalized if _ISO_CURRENCY_RE.fullmatch(normalized) else None


def _source_rank(source: str, priorities: tuple[str, ...]) -> int:
    normalized = _normalized_source(source)
    try:
        return priorities.index(normalized)
    except ValueError:
        return len(priorities)


def _normalized_source(source: Any) -> str:
    normalized = str(source or "").strip().lower()
    return {
        "yahoo": "yfinance",
        "twelve_data": "twelvedata",
        "12data": "twelvedata",
    }.get(normalized, normalized)


def configured_price_source_priority() -> tuple[str, ...]:
    """Return only providers explicitly enabled by the deployment.

    A stored row does not retain display authority after the corresponding
    provider permission is removed. Credentials alone are also insufficient:
    the existing activation flags remain the operator's fail-closed decision.
    """
    configured: list[str] = []
    for raw_kind in (settings.MARKET_DATA_PRIMARY, settings.MARKET_DATA_SECONDARY):
        source = _normalized_source(raw_kind)
        if source == "twelvedata":
            permitted = bool(
                settings.MARKET_DATA_COMMERCIAL_ENABLED
                and str(settings.TWELVE_DATA_API_KEY or "").strip()
            )
        elif source == "yfinance":
            permitted = bool(settings.MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER)
        else:
            permitted = False
        if permitted and source not in configured:
            configured.append(source)
    return tuple(configured)


def serialize_canonical_eod_price(price: CanonicalEodPrice) -> dict[str, Any]:
    """One wire contract for every current-price product surface."""
    return {
        "status": price.status,
        "value": price.current_value,
        "observation_value": (
            price.close
            if price.source_authorization_state != "unauthorized"
            else None
        ),
        "price_id": price.price_id,
        "price_date": price.price_date.isoformat() if price.price_date else None,
        "currency": price.currency,
        "source": price.source,
        "observed_at": price.observed_at.isoformat() if price.observed_at else None,
        "freshness_state": price.freshness_state,
        "source_authorization_state": price.source_authorization_state,
        "reason_code": price.reason_code,
        "as_of_date": price.as_of_date.isoformat(),
        "as_of_mode": price.as_of_mode,
        "expected_session_date": (
            price.expected_session_date.isoformat()
            if price.expected_session_date
            else None
        ),
        "calendar_code": price.calendar_code,
        "freshness_policy_version": price.freshness_policy_version,
        "calendar_policy_version": price.calendar_policy_version,
        "source_policy_version": price.source_policy_version,
    }


def stock_price_evidence_matches(
    session: Session, *, price_id: int | None, stock_id: int
) -> bool:
    """Validate an explicitly cited price observation without selecting a quote."""
    if price_id is None:
        return False
    observation = session.get(StockPrice, price_id)
    return bool(observation and observation.stock_id == stock_id)


def read_canonical_eod_price(
    session: Session,
    *,
    stock: Stock,
    as_of: date,
    include_as_of_session: bool = False,
    source_priority: tuple[str, ...] | None = None,
) -> CanonicalEodPrice:
    """Read one deterministic, freshness-classified EOD observation.

    A date-only ``as_of`` is interpreted at the start of that civil day, so its
    own close is not yet knowable. Callers refreshing after close already know
    the explicit target session and do not use this ambiguity-prone shortcut.
    """
    authorized_sources = tuple(
        dict.fromkeys(
            _normalized_source(source)
            for source in (
                source_priority
                if source_priority is not None
                else configured_price_source_priority()
            )
            if _normalized_source(source)
        )
    )
    selection_priority = authorized_sources + tuple(
        source
        for source in DEFAULT_PRICE_SOURCE_PRIORITY
        if source not in authorized_sources
    )
    exchange = stock.listing_exchange or stock.exchange
    calendar = expected_session_on_or_before(
        exchange,
        as_of if include_as_of_session else as_of - timedelta(days=1),
    )
    max_date = calendar.session_date or as_of
    rows = (
        session.query(StockPrice)
        .filter(
            StockPrice.stock_id == stock.id,
            StockPrice.price_date <= max_date,
        )
        .all()
    )
    if not rows:
        return CanonicalEodPrice(
            stock_id=stock.id,
            price_id=None,
            close=None,
            price_date=None,
            currency=None,
            source=None,
            observed_at=None,
            freshness_state=(
                "unknown_freshness" if calendar.session_date is None else "missing"
            ),
            reason_code=calendar.reason_code or "price_missing",
            expected_session_date=calendar.session_date,
            calendar_code=calendar.calendar_code,
            status="unavailable",
            source_authorization_state="unavailable",
            as_of_date=as_of,
            as_of_mode=("through_session" if include_as_of_session else "start_of_day"),
        )

    latest_date = max(row.price_date for row in rows)
    same_date = [row for row in rows if row.price_date == latest_date]
    selected = min(
        same_date,
        key=lambda row: (
            _source_rank(row.source, selection_priority),
            -int((_ensure_utc(row.created_at).timestamp()) if row.created_at else 0),
            -int(row.id),
        ),
    )
    currency = _currency(selected.currency)
    normalized_source = _normalized_source(selected.source)
    source_authorization_state = (
        "authorized" if normalized_source in authorized_sources else "unauthorized"
    )
    if calendar.session_date is None:
        state = "unknown_freshness"
    elif currency is None:
        state = "unknown_freshness"
    elif selected.price_date == calendar.session_date:
        state = "fresh"
    else:
        state = "stale"

    close = float(selected.close)
    if not stock.is_active:
        status = "unavailable"
        reason = "stock_inactive"
    elif source_authorization_state != "authorized":
        status = "unavailable"
        reason = "source_unavailable"
    elif not math.isfinite(close) or close <= 0:
        status = "unavailable"
        reason = "price_value_invalid"
    elif currency is None:
        status = "unavailable"
        reason = "price_currency_unavailable"
    elif calendar.session_date is None:
        status = "unavailable"
        reason = calendar.reason_code
    elif state == "fresh":
        status = "available"
        reason = None
    else:
        status = "unavailable"
        reason = "price_older_than_expected_session"
    return CanonicalEodPrice(
        stock_id=stock.id,
        price_id=selected.id,
        close=close,
        price_date=selected.price_date,
        currency=currency,
        source=selected.source,
        observed_at=selected.created_at,
        freshness_state=state,
        reason_code=reason,
        expected_session_date=calendar.session_date,
        calendar_code=calendar.calendar_code,
        status=status,
        source_authorization_state=source_authorization_state,
        as_of_date=as_of,
        as_of_mode=("through_session" if include_as_of_session else "start_of_day"),
    )


def read_current_eod_price(
    session: Session,
    *,
    stock: Stock,
    evaluated_at: datetime | None = None,
    source_priority: tuple[str, ...] | None = None,
) -> CanonicalEodPrice:
    """Read the latest exchange session whose close should now be complete."""
    now_utc = _ensure_utc(evaluated_at or datetime.now(timezone.utc))
    now_et = now_utc.astimezone(ET)
    target_date = compute_target_date(now_et)
    result = read_canonical_eod_price(
        session,
        stock=stock,
        as_of=target_date,
        include_as_of_session=True,
        source_priority=source_priority,
    )
    return replace(
        result,
        as_of_date=now_et.date(),
        as_of_mode="latest_completed_session",
    )


def read_canonical_eod_series(
    session: Session,
    *,
    stock_ids: Iterable[int],
    through: date,
    from_date: date | None = None,
    source_priority: tuple[str, ...] = DEFAULT_PRICE_SOURCE_PRIORITY,
) -> dict[int, list[StockPrice]]:
    """Return at most one deterministic observation per stock/session.

    Historical context callers use this instead of independently choosing the
    newest duplicate row and accidentally disagreeing on provider priority.
    """
    ids = list(dict.fromkeys(int(stock_id) for stock_id in stock_ids))
    if not ids:
        return {}
    query = session.query(StockPrice).filter(
        StockPrice.stock_id.in_(ids),
        StockPrice.price_date <= through,
    )
    if from_date is not None:
        query = query.filter(StockPrice.price_date >= from_date)
    rows = query.all()
    selected: dict[tuple[int, date], StockPrice] = {}
    for row in rows:
        key = (int(row.stock_id), row.price_date)
        incumbent = selected.get(key)
        if incumbent is None or (
            _source_rank(row.source, source_priority),
            -int((_ensure_utc(row.created_at).timestamp()) if row.created_at else 0),
            -int(row.id),
        ) < (
            _source_rank(incumbent.source, source_priority),
            -int(
                (_ensure_utc(incumbent.created_at).timestamp())
                if incumbent.created_at
                else 0
            ),
            -int(incumbent.id),
        ):
            selected[key] = row
    result: dict[int, list[StockPrice]] = {stock_id: [] for stock_id in ids}
    for row in selected.values():
        result[int(row.stock_id)].append(row)
    for stock_rows in result.values():
        stock_rows.sort(key=lambda row: (row.price_date, row.id), reverse=True)
    return result


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

    def _fetch_daily_payloads(
        self,
        stocks: list[Stock],
        target_date: date,
    ) -> dict[str, dict[str, Any]]:
        data: dict[str, dict[str, Any]] = {}
        if hasattr(self.provider, "fetch_daily"):
            data = self.provider.fetch_daily(
                [stock.ticker for stock in stocks], target_date
            ) or {}
        elif hasattr(self.provider, "fetch_daily_bar"):
            # Compatibility for deterministic test/manual adapters with only a
            # per-symbol method. Production providers implement fetch_daily and
            # are called once per target-date batch.
            for stock in stocks:
                bar = self.provider.fetch_daily_bar(
                    ticker=stock.ticker,
                    exchange=stock.exchange,
                    target_date=target_date,
                )
                if isinstance(bar, dict):
                    data[stock.ticker] = bar
                elif bar is not None:
                    data[stock.ticker] = {
                        "open": float(getattr(bar, "open", 0.0)),
                        "high": float(getattr(bar, "high", 0.0)),
                        "low": float(getattr(bar, "low", 0.0)),
                        "close": float(getattr(bar, "close", 0.0)),
                        "volume": float(getattr(bar, "volume", 0.0)),
                        "currency": getattr(bar, "currency", None),
                        "source": getattr(bar, "source", None),
                    }
        return data

    def _fetch_daily_payload(self, stock: Stock, target_date: date) -> dict[str, Any] | None:
        data = self._fetch_daily_payloads([stock], target_date)
        symbol_key = stock.ticker
        return data.get(symbol_key) or data.get(symbol_key.upper()) or data.get(symbol_key.lower())

    @staticmethod
    def _validated_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        currency = _currency(payload.get("currency"))
        if currency is None:
            return None, "provider_currency_missing"
        try:
            normalized = {
                "open": float(payload["open"]),
                "high": float(payload["high"]),
                "low": float(payload["low"]),
                "close": float(payload["close"]),
                "adj_close": (
                    float(payload["adj_close"])
                    if payload.get("adj_close") is not None
                    else None
                ),
                "volume": (
                    int(payload["volume"])
                    if payload.get("volume") is not None
                    else None
                ),
                "currency": currency,
                "source": str(payload.get("source") or "").strip() or None,
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, "provider_payload_invalid"
        if (
            min(
                normalized["open"],
                normalized["high"],
                normalized["low"],
                normalized["close"],
            )
            <= 0
            or normalized["high"] < normalized["low"]
            or normalized["high"] < max(normalized["open"], normalized["close"])
            or normalized["low"] > min(normalized["open"], normalized["close"])
            or (normalized["volume"] is not None and normalized["volume"] < 0)
        ):
            return None, "provider_payload_invalid"
        return normalized, None

    def backfill_13f_linked_period_prices(
        self,
        *,
        periods: Iterable[date] | None = None,
        superinvestor_only: bool = True,
        reason: str = "13f_period_backfill",
        now: Optional[datetime] = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        now_utc = _ensure_utc(now or datetime.now(timezone.utc))
        requested_periods = list(periods or [])
        query = (
            self.db.query(Stock, Filing13F.period_of_report)
            .join(Holding13F, Holding13F.stock_id == Stock.id)
            .join(Filing13F, Filing13F.id == Holding13F.filing_id)
            .join(InstitutionManager, InstitutionManager.id == Filing13F.manager_id)
            .filter(Filing13F.is_latest_for_period.is_(True))
            .filter(InstitutionManager.match_status == "confirmed")
            .filter(InstitutionManager.cik.isnot(None))
            .filter(Holding13F.stock_id.isnot(None))
            .filter(Holding13F.put_call.is_(None))
        )
        if superinvestor_only:
            query = query.filter(InstitutionManager.is_superinvestor.is_(True))
        if requested_periods:
            query = query.filter(Filing13F.period_of_report.in_(requested_periods))

        seen: set[tuple[int, date]] = set()
        targets: list[tuple[Stock, date, date]] = []
        for stock, period_of_report in query.order_by(Filing13F.period_of_report.desc(), Stock.ticker.asc()).all():
            target_date = _business_day_on_or_before(period_of_report)
            key = (stock.id, target_date)
            if key in seen:
                continue
            seen.add(key)
            targets.append((stock, period_of_report, target_date))
            if limit is not None and len(targets) >= limit:
                break

        results: list[dict[str, Any]] = []
        for stock, period_of_report, target_date in targets:
            existing = self.db.scalars(
                select(StockPrice)
                .where(
                    StockPrice.stock_id == stock.id,
                    StockPrice.price_date == target_date,
                )
                .order_by(StockPrice.created_at.desc())
                .limit(1)
            ).first()
            if existing is not None:
                results.append(
                    {
                        "stock_id": stock.id,
                        "ticker": stock.ticker,
                        "status": "skipped",
                        "reason": "up_to_date",
                        "period_of_report": period_of_report.isoformat(),
                        "target_date": target_date.isoformat(),
                    }
                )
                continue

            payload = self._fetch_daily_payload(stock, target_date)
            if not payload:
                results.append(
                    {
                        "stock_id": stock.id,
                        "ticker": stock.ticker,
                        "status": "failed",
                        "reason": "provider_no_data",
                        "period_of_report": period_of_report.isoformat(),
                        "target_date": target_date.isoformat(),
                    }
                )
                continue

            normalized, validation_error = self._validated_payload(payload)
            if normalized is None:
                results.append(
                    {
                        "stock_id": stock.id,
                        "ticker": stock.ticker,
                        "status": "failed",
                        "reason": validation_error,
                        "period_of_report": period_of_report.isoformat(),
                        "target_date": target_date.isoformat(),
                    }
                )
                continue

            self.db.add(
                StockPrice(
                    stock_id=stock.id,
                    price_date=target_date,
                    open=normalized["open"],
                    high=normalized["high"],
                    low=normalized["low"],
                    close=normalized["close"],
                    adj_close=normalized["adj_close"],
                    volume=normalized["volume"],
                    currency=normalized["currency"],
                    source=(
                        normalized["source"]
                        or getattr(self.provider, "name", "provider")
                    ),
                    created_at=now_utc,
                )
            )
            results.append(
                {
                    "stock_id": stock.id,
                    "ticker": stock.ticker,
                    "status": "refreshed",
                    "reason": reason,
                    "period_of_report": period_of_report.isoformat(),
                    "target_date": target_date.isoformat(),
                }
            )

        self.db.commit()
        return results

    def refresh_stock_prices(
        self,
        stock_ids: Iterable[int],
        *,
        reason: str,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        unique_stock_ids = list(dict.fromkeys(int(stock_id) for stock_id in stock_ids))
        results_by_stock: dict[int, dict[str, Any]] = {}
        now_utc = _ensure_utc(now or datetime.now(timezone.utc))
        now_et = now_utc.astimezone(ET)
        default_target_date = compute_target_date(
            now_et,
            open_time=self.open_time,
            close_buffer_time=self.close_buffer_time,
        )
        pending_by_date: dict[date, list[Stock]] = {}

        for stock_id in unique_stock_ids:
            stock = self.db.get(Stock, stock_id)
            if not stock:
                results_by_stock[stock_id] = {
                    "stock_id": stock_id,
                    "status": "failed",
                    "reason": "stock_not_found",
                    "target_date": default_target_date.isoformat(),
                }
                continue
            if not stock.is_active:
                results_by_stock[stock_id] = {
                    "stock_id": stock_id,
                    "status": "blocked",
                    "reason": "stock_inactive",
                    "target_date": None,
                }
                continue
            if stock.market_country != "US":
                results_by_stock[stock_id] = {
                    "stock_id": stock_id,
                    "status": "blocked",
                    "reason": "unsupported_market_country",
                    "target_date": None,
                }
                continue
            calendar = expected_session_on_or_before(
                stock.listing_exchange or stock.exchange,
                default_target_date,
            )
            if calendar.session_date is None:
                results_by_stock[stock_id] = {
                    "stock_id": stock_id,
                    "status": "blocked",
                    "reason": calendar.reason_code,
                    "target_date": None,
                }
                continue
            target_date = calendar.session_date
            close_buffer_dt = datetime.combine(
                target_date, self.close_buffer_time, tzinfo=ET
            )

            latest_any = self.db.scalars(
                select(StockPrice)
                .where(StockPrice.stock_id == stock_id)
                .order_by(StockPrice.created_at.desc())
                .limit(1)
            ).first()
            if latest_any and latest_any.created_at:
                latest_any_utc = _ensure_utc(latest_any.created_at)
                if now_utc - latest_any_utc < timedelta(minutes=self.throttle_minutes):
                    results_by_stock[stock_id] = {
                        "stock_id": stock_id,
                        "status": "skipped",
                        "reason": "throttled",
                        "target_date": target_date.isoformat(),
                    }
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

            should_refresh = latest_target is None or _currency(latest_target.currency) is None
            if latest_target is not None:
                created_at = latest_target.created_at
                created_et = _ensure_utc(created_at).astimezone(ET) if created_at else None
                if _currency(latest_target.currency) is None:
                    should_refresh = True
                elif now_et >= close_buffer_dt and created_et and created_et < close_buffer_dt:
                    should_refresh = True
                else:
                    should_refresh = False

            if not should_refresh:
                results_by_stock[stock_id] = {
                    "stock_id": stock_id,
                    "status": "skipped",
                    "reason": "up_to_date",
                    "target_date": target_date.isoformat(),
                }
                continue
            pending_by_date.setdefault(target_date, []).append(stock)

        for target_date, stocks in sorted(pending_by_date.items()):
            payloads = self._fetch_daily_payloads(stocks, target_date)
            for stock in stocks:
                payload = (
                    payloads.get(stock.ticker)
                    or payloads.get(stock.ticker.upper())
                    or payloads.get(stock.ticker.lower())
                )
                if not payload:
                    results_by_stock[stock.id] = {
                        "stock_id": stock.id,
                        "status": "failed",
                        "reason": (
                            "provider_unconfigured"
                            if getattr(self.provider, "name", "") == "unconfigured"
                            else "provider_no_data"
                        ),
                        "target_date": target_date.isoformat(),
                    }
                    continue
                normalized, validation_error = self._validated_payload(payload)
                if normalized is None:
                    results_by_stock[stock.id] = {
                        "stock_id": stock.id,
                        "status": "failed",
                        "reason": validation_error,
                        "target_date": target_date.isoformat(),
                    }
                    continue
                self.db.add(
                    StockPrice(
                        stock_id=stock.id,
                        price_date=target_date,
                        open=normalized["open"],
                        high=normalized["high"],
                        low=normalized["low"],
                        close=normalized["close"],
                        adj_close=normalized["adj_close"],
                        volume=normalized["volume"],
                        currency=normalized["currency"],
                        source=(
                            normalized["source"]
                            or getattr(self.provider, "name", "provider")
                        ),
                        created_at=now_utc,
                    )
                )
                results_by_stock[stock.id] = {
                    "stock_id": stock.id,
                    "status": "refreshed",
                    "reason": reason,
                    "target_date": target_date.isoformat(),
                    "currency": normalized["currency"],
                }

        self.db.commit()
        return [results_by_stock[stock_id] for stock_id in unique_stock_ids]
