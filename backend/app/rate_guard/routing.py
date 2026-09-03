"""Resolve the live Rate Guard route without weakening identity failures."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.core.config import settings
from app.rate_guard.client import (
    RateGuardClient,
    RateGuardFetchError,
    RateGuardIdentityUnavailable,
)
from app.rate_guard.route_state import (
    RateGuardRoute,
    get_active_route,
    set_active_route,
)

logger = logging.getLogger(__name__)


def _require_url(value: str | None, setting_name: str) -> str:
    url = (value or "").strip().rstrip("/")
    if not url:
        raise RuntimeError(f"EDGAR_FETCH_MODE=live requires {setting_name}")
    return url


def _fallback_url() -> str:
    url = _require_url(settings.RATE_GUARD_FALLBACK_URL, "RATE_GUARD_FALLBACK_URL")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "rate-guard-local" or parsed.port != 9000:
        raise RuntimeError(
            "RATE_GUARD_FALLBACK_URL must be the private development endpoint "
            "http://rate-guard-local:9000"
        )
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        raise RuntimeError(
            "RATE_GUARD_FALLBACK_URL must be the private development endpoint "
            "http://rate-guard-local:9000"
        )
    return url


def _probe_rate_guard_route(
    url: str, expected_instance_id: str | None, source: str
) -> RateGuardRoute:
    with RateGuardClient(
        base_url=url, expected_instance_id=expected_instance_id
    ) as client:
        instance_id = (
            client.verify_identity()
            if (expected_instance_id or "").strip()
            else client.discover_identity()
        )
    return RateGuardRoute(
        base_url=url, expected_instance_id=instance_id, source=source
    )


def reconcile_rate_guard_route() -> RateGuardRoute:
    """Select primary, or local only when primary is genuinely unavailable."""
    primary_url = _require_url(settings.RATE_GUARD_URL, "RATE_GUARD_URL")
    expected = (settings.RATE_GUARD_EXPECTED_INSTANCE_ID or "").strip() or None

    try:
        route = _probe_rate_guard_route(primary_url, expected, "primary")
    except RateGuardIdentityUnavailable:
        if not settings.RATE_GUARD_ALLOW_LOCAL_FALLBACK:
            raise
        fallback_url = _fallback_url()
        route = _probe_rate_guard_route(fallback_url, None, "fallback")

    set_active_route(route)
    return route


def reconcile_monitored_rate_guard_route() -> RateGuardRoute:
    """Reconcile one monitor tick and quarantine an unsafe primary identity."""
    current = get_active_route()
    try:
        return reconcile_rate_guard_route()
    except RateGuardIdentityUnavailable:
        # This means neither a permitted fallback nor the primary could be
        # verified. Keep the last route; network calls on an offline route fail.
        raise
    except RateGuardFetchError:
        # If the route currently in use is the endpoint that just failed
        # authentication/identity validation, stop existing long-lived clients
        # from continuing to send requests through it. A verified private
        # fallback remains safe while central credentials are repaired.
        if current is not None and current.source == "primary":
            set_active_route(
                RateGuardRoute(
                    base_url="",
                    expected_instance_id=current.expected_instance_id,
                    source="blocked",
                )
            )
        raise


def verify_live_rate_guard() -> str | None:
    """Resolve and pin the route before any live external client is created."""
    if settings.EDGAR_FETCH_MODE not in {"live", "rate_guard"}:
        return None
    if (
        not settings.RATE_GUARD_ALLOW_LOCAL_FALLBACK
        and not (settings.RATE_GUARD_EXPECTED_INSTANCE_ID or "").strip()
    ):
        raise RuntimeError(
            "EDGAR_FETCH_MODE=live requires RATE_GUARD_EXPECTED_INSTANCE_ID"
        )
    try:
        route = reconcile_rate_guard_route()
    except RateGuardFetchError as exc:
        raise RuntimeError(f"Live Rate Guard verification failed: {exc}") from exc
    logger.info(
        "Verified live Rate Guard %s instance %s at %s",
        route.source,
        route.expected_instance_id,
        route.base_url,
    )
    return route.expected_instance_id
