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
from urllib.parse import urlparse
import uuid

import httpx

from app.core.config import settings
from app.rate_guard.route_state import get_active_route

logger = logging.getLogger(__name__)

# A single /v1/fetch can block while Rate Guard works through its own retry +
# 429/503 global pause; the client timeout must comfortably exceed that.
_RATE_GUARD_TIMEOUT_S = 1800.0
_RATE_GUARD_IDENTITY_TIMEOUT_S = 10.0

# Hosts where a plain-http Rate Guard URL is fine (traffic never leaves the box /
# the Docker network). Anything else must be https when a key is configured.
_INTERNAL_RATE_GUARD_HOSTS = {
    "rate-guard",
    "rate-guard-local",
    "localhost",
    "127.0.0.1",
    "::1",
}
_IDENTITY_ORIGIN_UNAVAILABLE_STATUSES = {502, 503, 504, 521, 522, 523, 524, 530}
# Warn at most once per misconfigured base URL, not per request.
_insecure_key_url_warned: set[str] = set()


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


class RateGuardIdentityUnavailable(RateGuardFetchError):
    """The configured identity origin cannot currently be reached.

    Only this failure class is eligible for development fallback. Authentication,
    malformed responses, and identity mismatches remain ordinary fail-closed
    ``RateGuardFetchError`` failures.
    """


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

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        *,
        base_url: str | None = None,
        expected_instance_id: str | None = None,
    ) -> None:
        self._client = http_client or httpx.Client(timeout=_RATE_GUARD_TIMEOUT_S)
        self._uses_active_route = base_url is None
        active = get_active_route() if self._uses_active_route else None
        self._configured_base_url = (
            active.base_url if active is not None else base_url or settings.RATE_GUARD_URL
        )
        self._configured_expected_instance_id = (
            active.expected_instance_id
            if active is not None
            else (
                expected_instance_id
                if base_url is not None
                else settings.RATE_GUARD_EXPECTED_INSTANCE_ID
            )
        )

    def _route_config(self) -> tuple[str | None, str | None]:
        if self._uses_active_route:
            active = get_active_route()
            if active is not None:
                return active.base_url, active.expected_instance_id
        return self._configured_base_url, self._configured_expected_instance_id

    def _base_url(self) -> str:
        base_url, _expected = self._route_config()
        return self._validated_base_url(base_url)

    def _validated_base_url(self, base_url: str | None) -> str:
        base = (base_url or "").strip()
        if not base:
            raise RateGuardFetchError(
                "RATE_GUARD_URL is not configured — external fetches must route "
                "through Rate Guard. Set RATE_GUARD_URL (see rate-guard/README.md)."
            )
        base = base.rstrip("/")
        self._warn_if_key_over_insecure_url(base)
        return base

    @staticmethod
    def _warn_if_key_over_insecure_url(base: str) -> None:
        """The Bearer key is a secret; sending it over plain http to an off-box
        host leaks it in cleartext. Warn (once per URL) on that misconfiguration.
        Plain http to an internal host (rate-guard/localhost) is expected and OK.
        """
        key = (settings.RATE_GUARD_API_KEY or "").strip()
        if not key:
            return
        parsed = urlparse(base)
        if parsed.scheme == "https":
            return
        if (parsed.hostname or "").lower() in _INTERNAL_RATE_GUARD_HOSTS:
            return
        if base not in _insecure_key_url_warned:
            _insecure_key_url_warned.add(base)
            logger.warning(
                "RATE_GUARD_API_KEY is set but RATE_GUARD_URL=%s is not https to "
                "an internal host — the Bearer key would transit in cleartext. "
                "Use https:// for any external Rate Guard URL.",
                base,
            )

    def _auth_headers(self) -> dict:
        """Bearer header for Rate Guard when a shared key is configured; empty
        otherwise. One env var (RATE_GUARD_API_KEY) gates the public surface
        without touching any per-upstream client."""
        key = (settings.RATE_GUARD_API_KEY or "").strip()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def fetch(
        self, *, upstream: str, method: str, url: str, body: bytes = b""
    ) -> bytes:
        """Fetch ``url`` for ``upstream`` via Rate Guard; return the upstream body.

        Raises ``RateGuardFetchError`` on any failure — the upstream HTTP
        status, when Rate Guard reports one, is on ``.status_code``.
        """
        endpoint = f"{self._base_url()}/v1/fetch"
        payload: dict = {"upstream": upstream, "method": method, "url": url}
        if body:
            payload["body_b64"] = base64.b64encode(body).decode("ascii")
        try:
            resp = self._client.request(
                "POST", endpoint, json=payload, headers=self._auth_headers()
            )
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

    def discover_identity(self) -> str:
        """Return a structurally validated identity without requiring a pin."""
        return self._discover_identity_at(self._base_url())

    def _discover_identity_at(self, base_url: str) -> str:
        url = f"{base_url}/v1/identity"
        try:
            resp = self._client.request(
                "GET",
                url,
                headers=self._auth_headers(),
                timeout=_RATE_GUARD_IDENTITY_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise RateGuardIdentityUnavailable(
                f"Rate Guard identity endpoint is unreachable: {exc}"
            ) from exc
        if resp.status_code in _IDENTITY_ORIGIN_UNAVAILABLE_STATUSES:
            raise RateGuardIdentityUnavailable(
                f"Rate Guard identity origin is unavailable (HTTP {resp.status_code})"
            )
        if resp.status_code != 200:
            raise RateGuardFetchError(
                f"Rate Guard identity endpoint returned HTTP {resp.status_code}"
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise RateGuardFetchError(
                "Rate Guard identity endpoint returned malformed JSON"
            ) from exc
        if not isinstance(body, dict) or body.get("service") != "rate-guard":
            raise RateGuardFetchError(
                "Rate Guard identity endpoint returned a malformed identity"
            )
        actual_raw = body.get("instance_id")
        try:
            actual = str(uuid.UUID(actual_raw))
        except (ValueError, TypeError, AttributeError) as exc:
            raise RateGuardFetchError(
                "Rate Guard identity endpoint returned a malformed identity"
            ) from exc
        if actual_raw != actual:
            raise RateGuardFetchError(
                "Rate Guard identity endpoint returned a malformed identity"
            )
        return actual

    def verify_identity(self) -> str:
        """Prove the configured URL reaches the expected Rate Guard instance."""
        base_url, expected_instance_id = self._route_config()
        expected = (expected_instance_id or "").strip()
        if not expected:
            raise RateGuardFetchError(
                "RATE_GUARD_EXPECTED_INSTANCE_ID is required for live external access"
            )
        try:
            expected = str(uuid.UUID(expected))
        except ValueError as exc:
            raise RateGuardFetchError(
                "RATE_GUARD_EXPECTED_INSTANCE_ID is not a valid UUID"
            ) from exc

        # Pin the same route snapshot for the request and comparison. The
        # monitor may atomically replace the active route between operations.
        actual = self._discover_identity_at(self._validated_base_url(base_url))
        if actual != expected:
            raise RateGuardFetchError(
                f"Rate Guard URL reached unexpected instance {actual}; expected {expected}"
            )
        return actual

    def metrics(self, upstream: str | None = None) -> dict:
        """GET Rate Guard's per-upstream metrics snapshot.

        With ``upstream``, returns just that upstream's snapshot dict; without,
        the full ``{name: snapshot}`` map. Raises ``RateGuardFetchError`` on any
        failure.
        """
        url = f"{self._base_url()}/v1/metrics"
        params = {"upstream": upstream} if upstream else None
        try:
            resp = self._client.request(
                "GET", url, params=params, headers=self._auth_headers()
            )
        except httpx.HTTPError as exc:
            logger.warning("Rate Guard unreachable for /v1/metrics: %s", exc)
            raise RateGuardFetchError(
                f"Rate Guard unreachable for /v1/metrics: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise RateGuardFetchError(
                f"Rate Guard returned HTTP {resp.status_code} for /v1/metrics"
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise RateGuardFetchError(
                f"Rate Guard returned a malformed /v1/metrics response: {exc}"
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("upstreams"), dict):
            raise RateGuardFetchError(
                "Rate Guard returned a malformed /v1/metrics response "
                "(no 'upstreams' map)"
            )
        upstreams = body["upstreams"]
        if upstream is None:
            return upstreams
        snap = upstreams.get(upstream)
        if not isinstance(snap, dict):
            # A structurally-valid response that is missing the requested
            # upstream is a fault — surface it rather than degrade to an
            # all-zeros panel.
            raise RateGuardFetchError(
                f"Rate Guard /v1/metrics has no snapshot for upstream '{upstream}'"
            )
        return snap

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RateGuardClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
