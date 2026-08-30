"""EDGAR client — a thin wrapper over the shared Rate Guard egress client.

Rate limiting, retry, the 429/503 global pause, and per-fetch metrics are owned
by Rate Guard (see ``docs/tasks/2026-05-20_rate-guard-design.md``). EdgarClient
adds nothing but the ``edgar`` upstream name and the SEC host constants — the
``POST /v1/fetch`` plumbing lives in ``app.rate_guard.client.RateGuardClient``,
shared with ``OpenFigiClient`` and ``DataromaClient``.

The public API (``get`` / ``head`` / ``close`` / context manager / the ``BASE``
constants) is unchanged, so existing call sites need no edits. A fetch failure
raises ``RateGuardFetchError`` (from ``app.rate_guard.client``).
"""
import httpx

from app.core.config import settings
from app.rate_guard.client import RateGuardClient
from app.rate_guard.route_state import get_active_route


class EdgarClient:
    """Fetches EDGAR URLs through the Rate Guard egress service."""

    BASE = "https://www.sec.gov"
    EFTS_BASE = "https://efts.sec.gov"
    DATA_BASE = "https://data.sec.gov"

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        if (
            settings.EDGAR_FETCH_MODE == "live"
            and settings.RATE_GUARD_ALLOW_LOCAL_FALLBACK
            and get_active_route() is None
        ):
            # Operator CLIs and one-off workers do not execute FastAPI's
            # lifespan. Resolve the same adaptive route at this boundary too.
            from app.rate_guard.routing import verify_live_rate_guard

            verify_live_rate_guard()
        self._rate_guard = RateGuardClient(http_client)
        if settings.EDGAR_FETCH_MODE == "live":
            # API startup verifies early; this second boundary also protects
            # operator CLIs and one-off workers that do not run FastAPI lifespan.
            try:
                self._rate_guard.verify_identity()
            except BaseException:
                self._rate_guard.close()
                raise

    def get(self, url: str) -> bytes:
        """Fetch URL body via Rate Guard. Raises RateGuardFetchError on any non-200."""
        return self._rate_guard.fetch(upstream="edgar", method="GET", url=url)

    def head(self, url: str) -> None:
        """Probe URL existence via Rate Guard. Raises on any non-200 (e.g. 404)."""
        self._rate_guard.fetch(upstream="edgar", method="HEAD", url=url)

    def close(self) -> None:
        self._rate_guard.close()

    def __enter__(self) -> "EdgarClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
