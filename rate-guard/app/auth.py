"""Shared-key authentication for Rate Guard's public surface.

Rate Guard was built as an internal-only egress chokepoint. Once it is exposed
publicly (e.g. behind a Cloudflare Tunnel so a remote dev machine can reach it),
an unauthenticated ``/v1/fetch`` is an open proxy to SEC / OpenFIGI / Dataroma
under our own egress IP and User-Agent — abuse of it gets *our* IP banned. A
shared Bearer key gates the surface, in the same spirit as an API key.

Multiple accepted keys — ``RATE_GUARD_API_KEY`` plus any
``RATE_GUARD_API_KEY_<LABEL>`` (e.g. ``RATE_GUARD_API_KEY_DEVELOPMENT`` for a
remote dev box, ``RATE_GUARD_API_KEY_PREVIOUS`` for a rotation window) — let you
(a) rotate without a hard cutover and (b) hand each client its own labelled key,
revocable on its own. A request is authorized if its Bearer matches any of them.
Do not put non-key config under the ``RATE_GUARD_API_KEY_`` prefix.

Safety posture:
- Opt-in default: with **no** key configured, auth is disabled and every request
  is allowed, so CI and internal use are unchanged.
- Fail-closed for public: set ``RATE_GUARD_REQUIRE_AUTH=1`` on the exposed
  instance and ``enforce_auth_config()`` refuses to start if no key is set —
  mirroring the ``SEC_CONTACT_EMAIL`` fail-loud pattern, so an env slip can never
  silently boot an open public proxy.
"""
from __future__ import annotations

import hmac
import logging
import os

logger = logging.getLogger("rate_guard.auth")

_PRIMARY_KEY_ENV = "RATE_GUARD_API_KEY"
_KEY_ENV_PREFIX = "RATE_GUARD_API_KEY_"  # e.g. RATE_GUARD_API_KEY_DEVELOPMENT
_TRUTHY = {"1", "true", "yes", "on"}


def configured_api_keys() -> tuple[str, ...]:
    """Every non-empty accepted key from the environment.

    Reads ``RATE_GUARD_API_KEY`` plus any ``RATE_GUARD_API_KEY_<LABEL>`` var, so
    each caller/purpose gets its own labelled, independently-revocable key. Read
    live (not cached at import) so tests can toggle them and an operator can
    rotate with a restart rather than a rebuild. Blank / whitespace-only values
    are treated as absent. Sorted for deterministic order.
    """
    keys = []
    for name, value in os.environ.items():
        if name == _PRIMARY_KEY_ENV or name.startswith(_KEY_ENV_PREFIX):
            stripped = value.strip()
            if stripped:
                keys.append(stripped)
    return tuple(sorted(keys))


def public_auth_required() -> bool:
    """Whether this instance must refuse to serve without a key (fail-closed)."""
    return os.environ.get("RATE_GUARD_REQUIRE_AUTH", "").strip().lower() in _TRUTHY


def is_authorized(auth_header: str | None) -> bool:
    """Whether a request carrying ``auth_header`` may proceed.

    Auth disabled (no key configured) → always ``True``. Otherwise the header
    must equal ``Bearer <key>`` for one of the accepted keys. The comparison is
    done on **bytes** (never on ``str``): uvicorn latin-1-decodes header bytes,
    and ``compare_digest`` raises ``TypeError`` on a non-ASCII ``str`` — a bytes
    compare accepts any byte value, stays constant-time, and turns a hostile
    high-byte header into a clean ``False`` (→ 401) instead of a 500.
    """
    keys = configured_api_keys()
    if not keys:
        return True
    if not auth_header:
        return False
    provided = auth_header.encode("latin-1", "replace")
    # Compare against every key without early-exit so timing does not reveal
    # which key matched or how many are configured.
    matched = False
    for key in keys:
        if hmac.compare_digest(provided, f"Bearer {key}".encode("latin-1")):
            matched = True
    return matched


def enforce_auth_config() -> None:
    """Validate the auth configuration at startup.

    - ``RATE_GUARD_REQUIRE_AUTH`` set but no key configured → raise (fail-closed:
      never boot an unauthenticated public proxy).
    - No key and auth not required → warn loudly, so an accidental keyless boot
      is visible in the logs.
    """
    if configured_api_keys():
        return
    if public_auth_required():
        raise RuntimeError(
            "RATE_GUARD_REQUIRE_AUTH is set but no RATE_GUARD_API_KEY is "
            "configured — refusing to start an unauthenticated public Rate Guard."
        )
    logger.warning(
        "RATE_GUARD_API_KEY is not set — auth is DISABLED; all /v1/* paths are "
        "open. Set RATE_GUARD_API_KEY (and RATE_GUARD_REQUIRE_AUTH=1 on any "
        "publicly-exposed instance)."
    )
