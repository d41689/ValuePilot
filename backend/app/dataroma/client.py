"""Dataroma HTTP client with conservative rate limiting."""
import logging
import time
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MANAGERS_URL = "https://www.dataroma.com/m/managers.php"
HOLDINGS_URL = "https://www.dataroma.com/m/holdings.php"


def _parse_backoff(raw: str) -> list[float]:
    return [float(s.strip()) for s in raw.split(",") if s.strip()]


class DataromaClient:
    """Sync Dataroma HTTP client.

    Conservative: 1 request every DATAROMA_REQUEST_DELAY_S seconds.
    Raises on HTML parse failures so callers can alert and fall back to EDGAR.
    """

    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; ValuePilot/1.0; +https://valuepilot.com)"
                )
            },
            timeout=30,
            follow_redirects=True,
        )
        self._delay = settings.DATAROMA_REQUEST_DELAY_S
        self._backoff = _parse_backoff(settings.DATAROMA_RETRY_BACKOFF_S)
        self._last_request: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request = time.monotonic()

    def get(self, url: str) -> bytes:
        last_exc: Optional[Exception] = None
        for attempt in range(settings.DATAROMA_MAX_RETRIES + 1):
            if attempt > 0:
                delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]
                logger.warning("Dataroma retry %d/%d in %.0fs for %s", attempt, settings.DATAROMA_MAX_RETRIES, delay, url)
                time.sleep(delay)

            self._throttle()
            try:
                resp = self._client.get(url)
            except httpx.TransportError as exc:
                logger.warning("Dataroma transport error for %s: %s", url, exc)
                last_exc = exc
                continue

            if resp.status_code == 200:
                return resp.content

            logger.warning("Dataroma HTTP %d for %s", resp.status_code, url)
            last_exc = RuntimeError(f"HTTP {resp.status_code}")

        raise RuntimeError(
            f"Dataroma fetch failed after {settings.DATAROMA_MAX_RETRIES} retries for {url}"
        ) from last_exc

    def get_managers(self) -> bytes:
        return self.get(MANAGERS_URL)

    def get_holdings(self, dataroma_code: str) -> bytes:
        return self.get(f"{HOLDINGS_URL}?m={dataroma_code}")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DataromaClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
