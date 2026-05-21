"""Per-upstream configuration for Rate Guard.

Each external API ("upstream") is described declaratively: which hosts it may
reach, its rate limit, retry/backoff policy, the headers Rate Guard injects,
and its response-cache TTLs. Adding an upstream later is a config change here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Upstream:
    name: str
    allowed_hosts: tuple[str, ...]
    rate_per_sec: float
    burst: int
    max_retries: int
    backoff_s: tuple[float, ...]
    # On a 429/503 the upstream is globally paused for this long; every
    # in-flight retry waits the pause out before its next attempt.
    pause_s: float = 60.0
    user_agent: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    # GET/POST responses are cached for `cache_ttl_s` (0 disables the cache).
    # Paths under `cache_long_prefixes` are immutable once published and use
    # `cache_long_ttl_s` instead.
    cache_ttl_s: float = 0.0
    cache_long_prefixes: tuple[str, ...] = ()
    cache_long_ttl_s: float = 30 * 24 * 3600.0


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _sec_user_agent() -> str:
    """SEC mandates a descriptive User-Agent that carries contact info.

    A missing contact address is a configuration error: SEC blocks requests
    with an unidentifiable User-Agent, so fail loud at startup rather than
    silently shipping a placeholder that earns an IP ban.
    """
    contact = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not contact:
        raise RuntimeError(
            "SEC_CONTACT_EMAIL is required for the 'edgar' upstream — "
            "SEC rejects requests without a contactable User-Agent."
        )
    project = os.environ.get("PROJECT_NAME", "ValuePilot").strip() or "ValuePilot"
    return f"{project} {contact}"


def build_upstreams() -> dict[str, Upstream]:
    """Construct the upstream registry from the environment."""
    openfigi_key = os.environ.get("OPENFIGI_API_KEY", "").strip()
    return {
        "edgar": Upstream(
            name="edgar",
            allowed_hosts=("www.sec.gov", "efts.sec.gov", "data.sec.gov"),
            rate_per_sec=_env_float("RATE_GUARD_EDGAR_RPS", 8.0),
            burst=1,
            max_retries=5,
            backoff_s=(5.0, 30.0, 120.0, 300.0, 300.0),
            user_agent=_sec_user_agent(),
            extra_headers={"Accept-Encoding": "gzip"},
            cache_ttl_s=3600.0,
            # /Archives/edgar/... index + filing files never change once filed.
            cache_long_prefixes=("/Archives/",),
            cache_long_ttl_s=30 * 24 * 3600.0,
        ),
        "openfigi": Upstream(
            name="openfigi",
            allowed_hosts=("api.openfigi.com",),
            # ~250 req/min with an API key, ~25 without.
            rate_per_sec=_env_float(
                "RATE_GUARD_OPENFIGI_RPS", 4.0 if openfigi_key else 0.4
            ),
            burst=1,
            max_retries=3,
            backoff_s=(2.0, 10.0, 30.0),
            # OpenFIGI's /v3/mapping requires Content-Type: application/json;
            # Rate Guard forwards the raw body with httpx `content=`, which
            # sets no content type, so it must be injected here.
            extra_headers=(
                {"Content-Type": "application/json", "X-OPENFIGI-APIKEY": openfigi_key}
                if openfigi_key
                else {"Content-Type": "application/json"}
            ),
            cache_ttl_s=7 * 24 * 3600.0,
        ),
        "dataroma": Upstream(
            name="dataroma",
            allowed_hosts=("www.dataroma.com", "dataroma.com"),
            rate_per_sec=_env_float("RATE_GUARD_DATAROMA_RPS", 0.5),
            burst=1,
            max_retries=2,
            backoff_s=(10.0, 60.0),
            user_agent="Mozilla/5.0 (compatible; ValuePilot/1.0; +https://valuepilot.com)",
            cache_ttl_s=3600.0,
        ),
    }
