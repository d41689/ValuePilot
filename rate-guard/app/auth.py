"""Shared-key authentication for Rate Guard's public surface.

Rate Guard was built as an internal-only egress chokepoint. Once it is exposed
publicly (e.g. behind a Cloudflare Tunnel so a remote dev machine can reach it),
an unauthenticated ``/v1/fetch`` is an open proxy to SEC / OpenFIGI / Dataroma
under our own egress IP and User-Agent — abuse of it gets *our* IP banned. A
shared Bearer key gates the surface, in the same spirit as an API key.

Two accepted-key slots (``RATE_GUARD_API_KEY`` primary + optional
``RATE_GUARD_API_KEY_PREVIOUS``) let you (a) rotate without a hard cutover — set
the new key as primary, keep the old as previous until every caller is updated,
then drop it — and (b) hand a distinct key to a distinct client (e.g. the remote
dev box vs internal), revocable on its own.

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

_KEY_ENV_VARS = ("RATE_GUARD_API_KEY", "RATE_GUARD_API_KEY_PREVIOUS")
_TRUTHY = {"1", "true", "yes", "on"}


def configured_api_keys() -> tuple[str, ...]:
    """The non-empty accepted keys, read live from the environment.

    Live (not cached at import) so tests can toggle them and an operator can
    rotate with a restart rather than a rebuild. Blank / whitespace-only values
    are treated as absent.
    """
    keys = []
    for name in _KEY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            keys.append(value)
    return tuple(keys)


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
