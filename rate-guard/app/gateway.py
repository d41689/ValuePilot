"""The fetch orchestration: cache → token bucket → upstream call → retry.

One ``Gateway`` owns the buckets, metrics and cache for every upstream. It is
the single place external HTTP actually leaves the building.
"""
from __future__ import annotations

import base64
import logging
import math
import time
from urllib.parse import urlparse

import httpx

from .bucket import TokenBucket
from .cache import ResponseCache
from .config import Upstream
from .metrics import UpstreamMetrics

logger = logging.getLogger("rate_guard.gateway")

_MAX_PAUSE_WAIT = 120.0
_MAX_CACHE_AGE_OVERRIDE_S = 3600.0


class UpstreamError(Exception):
    """Raised when a request cannot be completed (bad upstream/host, 403, or
    retries exhausted)."""

    def __init__(self, status: int | None, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


class Gateway:
    def __init__(
        self,
        upstreams: dict[str, Upstream],
        cache: ResponseCache,
        client: httpx.Client | None = None,
    ) -> None:
        self._upstreams = upstreams
        self._cache = cache
        self._buckets = {
            n: TokenBucket(u.rate_per_sec, u.burst) for n, u in upstreams.items()
        }
        self._metrics = {n: UpstreamMetrics() for n in upstreams}
        # follow_redirects MUST stay False: redirects are not re-checked
        # against the host allowlist, so following a 3xx would let an
        # allowlisted host bounce the fetch to an arbitrary host. A 3xx is
        # returned to the caller as-is (see _request_with_retry).
        self._client = client or httpx.Client(timeout=30, follow_redirects=False)

    def upstream_names(self) -> list[str]:
        return list(self._upstreams)

    # -- request path -------------------------------------------------------

    def fetch(
        self,
        upstream: str,
        method: str,
        url: str,
        body: bytes = b"",
        max_cache_age_s: float | None = None,
    ) -> dict:
        if upstream not in self._upstreams:
            raise UpstreamError(None, f"unknown upstream: {upstream!r}")
        u = self._upstreams[upstream]
        method = method.upper()
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            raise UpstreamError(
                None,
                f"scheme {parsed.scheme!r} is not allowed — only https is permitted",
            )
        host = (parsed.hostname or "").lower()
        if host not in u.allowed_hosts:
            raise UpstreamError(
                None, f"host {host!r} is not allowed for upstream {upstream!r}"
            )

        configured_ttl = self._cache_ttl(u, url)
        ttl = configured_ttl
        if max_cache_age_s is not None:
            if (
                not math.isfinite(max_cache_age_s)
                or max_cache_age_s < 0
                or max_cache_age_s > _MAX_CACHE_AGE_OVERRIDE_S
            ):
                raise UpstreamError(
                    None,
                    "max_cache_age_s must be between 0 and 3600 seconds",
                )
            ttl = min(ttl, max_cache_age_s)
        cacheable = configured_ttl > 0 and method in ("GET", "POST")
        key = ResponseCache.key(upstream, method, url, body)
        if cacheable:
            cached = self._cache.get(key, ttl)
            if cached is not None:
                self._metrics[upstream].cache_hit()
                return {
                    "status": cached["status"],
                    "headers": cached["headers"],
                    "body_b64": cached["body_b64"],
                    "cache": "hit",
                }
            self._metrics[upstream].cache_miss()

        resp = self._request_with_retry(u, method, url, body)
        body_b64 = base64.b64encode(resp.content).decode("ascii")
        if cacheable and resp.status_code == 200:
            self._cache.put(key, resp.status_code, dict(resp.headers), body_b64)
        return {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body_b64": body_b64,
            "cache": "miss",
        }

    def _request_with_retry(
        self, u: Upstream, method: str, url: str, body: bytes
    ) -> httpx.Response:
        attempt = 0
        last_status: int | None = None
        while True:
            # A 429/503 on any concurrent request globally pauses the
            # upstream; every retry must wait that pause out before its
            # next attempt, not just sleep its own backoff.
            self._respect_pause(u.name)
            self._buckets[u.name].acquire()
            try:
                resp = self._client.request(
                    method, url, content=body or None, headers=self._headers(u)
                )
            except httpx.HTTPError as exc:
                last_status = None
                logger.warning("%s transport error: %s", u.name, exc)
            else:
                last_status = resp.status_code
                self._metrics[u.name].record(resp.status_code)
                if resp.status_code == 403:
                    logger.error("%s 403 for %s — IP block or bad UA", u.name, url)
                    raise UpstreamError(
                        403, f"{u.name} returned 403 (IP block or bad User-Agent)"
                    )
                if resp.status_code in (429, 503):
                    self._metrics[u.name].pause(u.pause_s)
                    logger.warning(
                        "%s %s — global pause %.0fs",
                        u.name, resp.status_code, u.pause_s,
                    )
                elif resp.status_code < 500:
                    # 2xx/3xx/404/other-4xx are definitive — return as-is.
                    return resp
            attempt += 1
            if attempt > u.max_retries:
                raise UpstreamError(
                    last_status,
                    f"{u.name} failed after {u.max_retries} retries "
                    f"(last status {last_status})",
                )
            backoff = u.backoff_s[min(attempt - 1, len(u.backoff_s) - 1)]
            time.sleep(backoff)

    # -- metrics ------------------------------------------------------------

    def metrics(self, upstream: str) -> dict:
        u = self._upstreams[upstream]
        snap = self._metrics[upstream].snapshot()
        snap["upstream"] = upstream
        snap["rate_per_sec"] = u.rate_per_sec
        snap["max_retries"] = u.max_retries
        snap["estimated_capacity"] = int(u.rate_per_sec * snap["window_seconds"])
        snap["remaining_estimated_capacity"] = max(
            snap["estimated_capacity"] - snap["recent_request_count"], 0
        )
        return snap

    # -- helpers ------------------------------------------------------------

    def _headers(self, u: Upstream) -> dict[str, str]:
        headers = dict(u.extra_headers)
        if u.user_agent:
            headers["User-Agent"] = u.user_agent
        return headers

    def _respect_pause(self, upstream: str) -> None:
        pause = self._metrics[upstream].global_pause_until
        if pause and pause > time.time():
            wait = min(pause - time.time(), _MAX_PAUSE_WAIT)
            logger.info("%s is paused — waiting %.1fs", upstream, wait)
            time.sleep(wait)

    @staticmethod
    def _cache_ttl(u: Upstream, url: str) -> float:
        path = urlparse(url).path
        for prefix in u.cache_long_prefixes:
            if path.startswith(prefix):
                return u.cache_long_ttl_s
        return u.cache_ttl_s
