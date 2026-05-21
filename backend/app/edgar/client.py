"""EDGAR client — a thin pass-through to the Rate Guard egress service.

Rate limiting, retry, and the 429/503 global pause are owned by Rate Guard
(the shared single-process limiter — see
``docs/tasks/2026-05-20_rate-guard-design.md``). EdgarClient forwards each
GET/HEAD to Rate Guard's ``POST /v1/fetch`` and unwraps the response. The
public API (``get`` / ``head`` / ``close`` / context manager / the ``BASE``
constants) is unchanged, so existing call sites need no edits.
"""
import base64
import logging
import threading
import time
from collections import deque

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Per-process record of EDGAR fetches — feeds the admin rate-limit panel and
# the 13F 403/429 block alerting. Rate Guard holds the authoritative
# cross-process view at ``GET /v1/metrics``; the admin panel moves onto that in
# Rate Guard PR 4/4.
_REQUEST_EVENTS: deque[dict[str, object]] = deque(maxlen=5000)
_REQUEST_EVENTS_LOCK = threading.Lock()

# A single /v1/fetch can block while Rate Guard works through its own retry +
# 429/503 global pause; the client timeout must comfortably exceed that.
_RATE_GUARD_TIMEOUT_S = 1800.0


class EdgarFetchError(RuntimeError):
    """An EDGAR fetch via Rate Guard failed.

    ``status_code`` is the upstream EDGAR HTTP status when Rate Guard reported
    one (e.g. 404, 403); ``None`` when the failure was Rate Guard itself
    (unreachable, malformed response, or not configured). Subclasses
    ``RuntimeError`` so existing broad ``except`` call sites are unaffected.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _record_request(status_code: int | None, url: str) -> None:
    with _REQUEST_EVENTS_LOCK:
        _REQUEST_EVENTS.append(
            {"at": time.time(), "status_code": status_code, "url": url}
        )


def edgar_rate_limit_status() -> dict[str, object]:
    """Per-process EDGAR fetch summary for the admin panel and 13F alerting.

    Rate Guard owns the real rate limiter and the 429/503 global pause now, so
    ``global_pause_until`` is always ``None`` here — the admin panel moves onto
    Rate Guard's ``/v1/metrics`` in Rate Guard PR 4/4.
    """
    window_seconds = settings.EDGAR_RATE_LIMIT_WINDOW_S
    cutoff = time.time() - window_seconds
    with _REQUEST_EVENTS_LOCK:
        recent = [e for e in _REQUEST_EVENTS if float(e["at"]) >= cutoff]
    request_rate = settings.EDGAR_REQUESTS_PER_SECOND
    if request_rate <= 0 and settings.EDGAR_REQUEST_DELAY_S > 0:
        request_rate = 1.0 / settings.EDGAR_REQUEST_DELAY_S
    if request_rate <= 0:
        request_rate = 10.0
    estimated_capacity = int(window_seconds * request_rate)
    recent_403 = sum(1 for e in recent if e["status_code"] == 403)
    recent_429 = sum(1 for e in recent if e["status_code"] == 429)
    return {
        "mode": settings.EDGAR_FETCH_MODE,
        "request_delay_s": 1.0 / request_rate,
        "requests_per_second": request_rate,
        "max_retries": settings.EDGAR_MAX_RETRIES,
        "window_seconds": window_seconds,
        "recent_request_count": len(recent),
        "recent_403_count": recent_403,
        "recent_429_count": recent_429,
        "edgar_block_alert": recent_403 > 0 or recent_429 > 0,
        "estimated_capacity": estimated_capacity,
        "remaining_estimated_capacity": max(estimated_capacity - len(recent), 0),
        "global_pause_until": None,
    }


def _rate_guard_error_detail(resp: httpx.Response) -> dict:
    """Unwrap the structured error from a Rate Guard 502 response body."""
    try:
        body = resp.json()
    except ValueError:
        return {"detail": resp.text}
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return detail if isinstance(detail, dict) else {"detail": detail}


class EdgarClient:
    """Fetches EDGAR URLs through the Rate Guard egress service."""

    BASE = "https://www.sec.gov"
    EFTS_BASE = "https://efts.sec.gov"
    DATA_BASE = "https://data.sec.gov"

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=_RATE_GUARD_TIMEOUT_S)

    def _fetch_endpoint(self) -> str:
        base = (settings.RATE_GUARD_URL or "").strip()
        if not base:
            raise EdgarFetchError(
                "RATE_GUARD_URL is not configured — EDGAR fetches must route "
                "through Rate Guard. Set RATE_GUARD_URL (see rate-guard/README.md)."
            )
        return f"{base.rstrip('/')}/v1/fetch"

    def _fetch(self, method: str, url: str) -> bytes:
        endpoint = self._fetch_endpoint()
        try:
            resp = self._client.request(
                "POST",
                endpoint,
                json={"upstream": "edgar", "method": method, "url": url},
            )
        except httpx.HTTPError as exc:
            _record_request(None, url)
            logger.warning("Rate Guard unreachable for %s: %s", url, exc)
            raise EdgarFetchError(f"Rate Guard unreachable for {url}: {exc}") from exc

        if resp.status_code != 200:
            if resp.status_code == 502:
                # Rate Guard reached (or refused to reach) EDGAR and could not
                # return a usable response — a 403, or retries exhausted.
                detail = _rate_guard_error_detail(resp)
                raw_status = detail.get("upstream_status")
                upstream_status = raw_status if isinstance(raw_status, int) else None
                _record_request(upstream_status, url)
                raise EdgarFetchError(
                    f"EDGAR fetch failed via Rate Guard for {url}: "
                    f"{detail.get('detail', detail)}",
                    status_code=upstream_status,
                )
            _record_request(None, url)
            raise EdgarFetchError(
                f"Rate Guard returned HTTP {resp.status_code} for {url}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            _record_request(None, url)
            raise EdgarFetchError(
                f"Rate Guard returned a malformed response for {url}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            _record_request(None, url)
            raise EdgarFetchError(f"Rate Guard returned a malformed response for {url}")
        try:
            upstream_status = int(payload.get("status", 0))
        except (ValueError, TypeError) as exc:
            _record_request(None, url)
            raise EdgarFetchError(
                f"Rate Guard returned a malformed response for {url}: {exc}"
            ) from exc
        _record_request(upstream_status, url)
        if upstream_status != 200:
            raise EdgarFetchError(
                f"EDGAR returned HTTP {upstream_status} for {url}",
                status_code=upstream_status,
            )
        try:
            return base64.b64decode(payload.get("body_b64") or "")
        except (ValueError, TypeError) as exc:
            raise EdgarFetchError(
                f"Rate Guard returned an undecodable body for {url}: {exc}"
            ) from exc

    def get(self, url: str) -> bytes:
        """Fetch URL body via Rate Guard. Raises on any non-200."""
        return self._fetch("GET", url)

    def head(self, url: str) -> None:
        """Probe URL existence via Rate Guard. Raises on any non-200 (e.g. 404)."""
        self._fetch("HEAD", url)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
