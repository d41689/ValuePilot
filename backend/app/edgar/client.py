"""EDGAR HTTP client with token-bucket rate limiting and retry."""
import logging
import threading
import time
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_GLOBAL_LOCK = threading.Lock()


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

    def get(self, url: str) -> bytes:
        """Fetch URL, blocking until rate limit allows, with retry on transient errors."""
        bucket = _get_bucket()
        last_exc: Optional[Exception] = None

        for attempt in range(settings.EDGAR_MAX_RETRIES + 1):
            if attempt > 0:
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]
                logger.warning("EDGAR retry %d/%d in %.0fs for %s", attempt, settings.EDGAR_MAX_RETRIES, delay, url)
                time.sleep(delay)

            bucket.acquire()
            try:
                resp = self._client.get(url)
            except httpx.TransportError as exc:
                logger.warning("EDGAR transport error for %s: %s", url, exc)
                last_exc = exc
                continue

            if resp.status_code == 200:
                return resp.content

            if resp.status_code == 403:
                raise RuntimeError(
                    f"EDGAR 403 for {url} — check User-Agent header or IP block"
                )

            if resp.status_code in (429, 503):
                logger.error("EDGAR %d — global pause 60 s then resume at 1 req/s", resp.status_code)
                time.sleep(60)
                # Reset bucket to conservative 1 req/s
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

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
