"""Shared client for the Rate Guard egress service.

Rate Guard (see ``docs/tasks/2026-05-20_rate-guard-design.md``) is the single
shared rate limiter / retrier for ValuePilot's external upstreams. The
per-upstream clients (``OpenFigiClient``, ``DataromaClient``; ``EdgarClient``
to follow) route their fetches through it — this module is the common
``POST /v1/fetch`` plumbing: build the request, unwrap the response envelope,
and surface every failure as a typed ``RateGuardFetchError``.
"""
import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# A single /v1/fetch can block while Rate Guard works through its own retry +
# 429/503 global pause; the client timeout must comfortably exceed that.
_RATE_GUARD_TIMEOUT_S = 1800.0


class RateGuardFetchError(RuntimeError):
    """A fetch via Rate Guard failed.

    ``status_code`` is the upstream HTTP status when Rate Guard reported one
    (e.g. 404, 403); ``None`` when the failure was Rate Guard itself
    (unreachable, malformed response, or not configured). Subclasses
    ``RuntimeError`` so existing broad ``except`` call sites are unaffected.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _error_detail(resp: httpx.Response) -> dict:
    """Unwrap the structured error from a Rate Guard 502 response body."""
    try:
        body = resp.json()
    except ValueError:
        return {"detail": resp.text}
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return detail if isinstance(detail, dict) else {"detail": detail}


class RateGuardClient:
    """Routes one external fetch through the Rate Guard egress service.

    Each per-upstream client owns a ``RateGuardClient``. ``http_client`` is
    injectable so tests can drive it with an ``httpx.MockTransport``.
    """

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=_RATE_GUARD_TIMEOUT_S)

    def _endpoint(self) -> str:
        base = (settings.RATE_GUARD_URL or "").strip()
        if not base:
            raise RateGuardFetchError(
                "RATE_GUARD_URL is not configured — external fetches must route "
                "through Rate Guard. Set RATE_GUARD_URL (see rate-guard/README.md)."
            )
        return f"{base.rstrip('/')}/v1/fetch"

    def fetch(
        self, *, upstream: str, method: str, url: str, body: bytes = b""
    ) -> bytes:
        """Fetch ``url`` for ``upstream`` via Rate Guard; return the upstream body.

        Raises ``RateGuardFetchError`` on any failure — the upstream HTTP
        status, when Rate Guard reports one, is on ``.status_code``.
        """
        endpoint = self._endpoint()
        payload: dict = {"upstream": upstream, "method": method, "url": url}
        if body:
            payload["body_b64"] = base64.b64encode(body).decode("ascii")
        try:
            resp = self._client.request("POST", endpoint, json=payload)
        except httpx.HTTPError as exc:
            logger.warning("Rate Guard unreachable for %s %s: %s", upstream, url, exc)
            raise RateGuardFetchError(
                f"Rate Guard unreachable for {url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            if resp.status_code == 502:
                # Rate Guard reached (or refused to reach) the upstream and
                # could not return a usable response — a 403, or exhausted.
                detail = _error_detail(resp)
                raw_status = detail.get("upstream_status")
                upstream_status = raw_status if isinstance(raw_status, int) else None
                raise RateGuardFetchError(
                    f"{upstream} fetch failed via Rate Guard for {url}: "
                    f"{detail.get('detail', detail)}",
                    status_code=upstream_status,
                )
            raise RateGuardFetchError(
                f"Rate Guard returned HTTP {resp.status_code} for {url}"
            )

        try:
            envelope = resp.json()
        except ValueError as exc:
            raise RateGuardFetchError(
                f"Rate Guard returned a malformed response for {url}: {exc}"
            ) from exc
        if not isinstance(envelope, dict):
            raise RateGuardFetchError(
                f"Rate Guard returned a malformed response for {url}"
            )
        try:
            upstream_status = int(envelope.get("status", 0))
        except (ValueError, TypeError) as exc:
            raise RateGuardFetchError(
                f"Rate Guard returned a malformed response for {url}: {exc}"
            ) from exc
        if upstream_status != 200:
            raise RateGuardFetchError(
                f"{upstream} returned HTTP {upstream_status} for {url}",
                status_code=upstream_status,
            )
        try:
            return base64.b64decode(envelope.get("body_b64") or "")
        except (ValueError, TypeError) as exc:
            raise RateGuardFetchError(
                f"Rate Guard returned an undecodable body for {url}: {exc}"
            ) from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RateGuardClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
