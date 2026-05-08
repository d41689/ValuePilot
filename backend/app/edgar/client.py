"""EDGAR HTTP client with token-bucket rate limiting and retry."""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_GLOBAL_LOCK = threading.Lock()
_REQUEST_EVENTS: deque[dict[str, object]] = deque(maxlen=5000)
_REQUEST_EVENTS_LOCK = threading.Lock()
_GLOBAL_PAUSE_UNTIL: float | None = None


class _TokenBucket:
    """Thread-safe token bucket for rate limiting."""

    def __init__(self, rate: float, burst: int = 1) -> None:
        self._rate = rate
        self._tokens = float(burst)
        self._burst = burst
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                time.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


# Module-level singleton bucket (5 req/s default, configurable via EDGAR_REQUEST_DELAY_S)
def _make_bucket() -> _TokenBucket:
    rate = 1.0 / settings.EDGAR_REQUEST_DELAY_S if settings.EDGAR_REQUEST_DELAY_S > 0 else 5.0
    return _TokenBucket(rate=rate, burst=1)


_bucket: Optional[_TokenBucket] = None
_bucket_lock = threading.Lock()


def _get_bucket() -> _TokenBucket:
    global _bucket
    if _bucket is None:
        with _bucket_lock:
            if _bucket is None:
                _bucket = _make_bucket()
    return _bucket


def _parse_backoff(raw: str) -> list[float]:
    return [float(s.strip()) for s in raw.split(",") if s.strip()]


def _record_request(status_code: int | None, url: str) -> None:
    with _REQUEST_EVENTS_LOCK:
        _REQUEST_EVENTS.append(
            {
                "at": time.time(),
                "status_code": status_code,
                "url": url,
            }
        )


def edgar_rate_limit_status() -> dict[str, object]:
    window_seconds = settings.EDGAR_RATE_LIMIT_WINDOW_S
    now = time.time()
    cutoff = now - window_seconds
    with _REQUEST_EVENTS_LOCK:
        recent = [event for event in _REQUEST_EVENTS if float(event["at"]) >= cutoff]
    request_delay = settings.EDGAR_REQUEST_DELAY_S
    estimated_capacity = int(window_seconds / request_delay) if request_delay > 0 else window_seconds * 5
    remaining = max(estimated_capacity - len(recent), 0)
    pause_until = None
    if _GLOBAL_PAUSE_UNTIL and _GLOBAL_PAUSE_UNTIL > now:
        pause_until = datetime.fromtimestamp(_GLOBAL_PAUSE_UNTIL, tz=timezone.utc).isoformat()
    return {
        "mode": settings.EDGAR_FETCH_MODE,
        "request_delay_s": request_delay,
        "max_retries": settings.EDGAR_MAX_RETRIES,
        "window_seconds": window_seconds,
        "recent_request_count": len(recent),
        "estimated_capacity": estimated_capacity,
        "remaining_estimated_capacity": remaining,
        "global_pause_until": pause_until,
    }


class EdgarClient:
    """Sync EDGAR HTTP client.

    Enforces the configured token-bucket rate limit and retries on 429/5xx.
    On 429 or 503 the client pauses globally for 60 s before resuming at 1 req/s.
    On 403 it raises immediately (bad User-Agent or IP block).
    """

    BASE = "https://www.sec.gov"
    EFTS_BASE = "https://efts.sec.gov"
    DATA_BASE = "https://data.sec.gov"

    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": settings.EDGAR_USER_AGENT, "Accept-Encoding": "gzip"},
            timeout=30,
            follow_redirects=True,
        )
        self._backoff = _parse_backoff(settings.EDGAR_RETRY_BACKOFF_S)

    def _request(self, method: str, url: str) -> httpx.Response:
        """Execute a rate-limited request with retry on transient errors."""
        bucket = _get_bucket()
        last_exc: Optional[Exception] = None

        for attempt in range(settings.EDGAR_MAX_RETRIES + 1):
            if attempt > 0:
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]
                logger.warning("EDGAR retry %d/%d in %.0fs for %s", attempt, settings.EDGAR_MAX_RETRIES, delay, url)
                time.sleep(delay)

            bucket.acquire()
            try:
                resp = self._client.request(method, url)
            except httpx.TransportError as exc:
                logger.warning("EDGAR transport error for %s: %s", url, exc)
                _record_request(None, url)
                last_exc = exc
                continue

            _record_request(resp.status_code, url)
            if resp.status_code == 200:
                return resp

            if resp.status_code == 403:
                raise RuntimeError(
                    f"EDGAR 403 for {url} — check User-Agent header or IP block"
                )

            if resp.status_code in (429, 503):
                logger.error("EDGAR %d — global pause 60 s then resume at 1 req/s", resp.status_code)
                global _GLOBAL_PAUSE_UNTIL
                _GLOBAL_PAUSE_UNTIL = time.time() + 60
                time.sleep(60)
                global _bucket
                with _bucket_lock:
                    _bucket = _TokenBucket(rate=1.0, burst=1)
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue

            if resp.status_code >= 500:
                logger.warning("EDGAR %d for %s", resp.status_code, url)
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue

            resp.raise_for_status()

        raise RuntimeError(
            f"EDGAR fetch failed after {settings.EDGAR_MAX_RETRIES} retries for {url}"
        ) from last_exc

    def get(self, url: str) -> bytes:
        """Fetch URL body, rate-limited with retry."""
        return self._request("GET", url).content

    def head(self, url: str) -> None:
        """Probe URL existence without downloading the body, rate-limited with retry.

        Raises on any non-200 response (e.g. 404). Use this instead of get()
        when only checking whether a file exists.
        """
        self._request("HEAD", url)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
