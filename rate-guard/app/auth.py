"""Shared-key authentication for Rate Guard's public surface.

Rate Guard was built as an internal-only egress chokepoint. Once it is exposed
publicly (e.g. behind a Cloudflare Tunnel so a remote dev machine can reach it),
an unauthenticated ``/v1/fetch`` is an open proxy to SEC / OpenFIGI / Dataroma
under our own egress IP and User-Agent — abuse of it gets *our* IP banned. A
single shared Bearer key gates the surface, in the same spirit as an API key.

Opt-in: when ``RATE_GUARD_API_KEY`` is unset or blank, auth is disabled and
every request is allowed, so internal callers and the existing tests keep
working unchanged.
"""
from __future__ import annotations

import os
import secrets


def configured_api_key() -> str:
    """The shared key, or ``""`` when auth is disabled.

    Read live from the environment (not cached at import) so tests can toggle it
    and an operator can rotate it with a restart rather than a rebuild.
    """
    return os.environ.get("RATE_GUARD_API_KEY", "").strip()


def is_authorized(auth_header: str | None) -> bool:
    """Whether a request carrying ``auth_header`` may proceed.

    Auth disabled (no key configured) → always ``True``. Otherwise the header
    must be exactly ``Bearer <key>``, compared in constant time so a wrong key
    leaks no timing signal.
    """
    key = configured_api_key()
    if not key:
        return True
    if not auth_header:
        return False
    return secrets.compare_digest(auth_header, f"Bearer {key}")
