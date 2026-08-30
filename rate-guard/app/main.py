"""Rate Guard HTTP API.

    POST /v1/fetch     — fetch a URL via the upstream's rate limiter + cache
    GET  /v1/metrics   — per-upstream budget / cache snapshot
    GET  /v1/identity  — authenticated persistent installation identity
    GET  /healthz      — liveness
"""
from __future__ import annotations

import base64
import logging
import os
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth import enforce_auth_config, is_authorized
from .cache import ResponseCache
from .config import build_upstreams
from .gateway import Gateway, UpstreamError
from .identity import load_or_create_instance_id

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Fail closed (or warn) on the auth configuration before serving a request —
# never silently boot an unauthenticated public proxy.
enforce_auth_config()

_cache_root = os.environ.get("RATE_GUARD_CACHE_DIR", "/data/cache")
INSTANCE_ID = load_or_create_instance_id(_cache_root)
PROCESS_ID = str(uuid.uuid4())
_cache = ResponseCache(_cache_root)
_gateway = Gateway(build_upstreams(), _cache)

app = FastAPI(title="Rate Guard", version="0.1.0")

# Paths reachable without the shared key. /healthz must stay open — the deploy
# script and Docker healthcheck poll it, and it exposes no upstream capability.
_AUTH_EXEMPT_PATHS = frozenset({"/healthz"})


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    """Gate every non-exempt path behind RATE_GUARD_API_KEY (when configured).

    Runs before route handling, so an unauthenticated /v1/fetch is rejected
    before the gateway makes any upstream request.
    """
    if request.url.path not in _AUTH_EXEMPT_PATHS and not is_authorized(
        request.headers.get("Authorization")
    ):
        return JSONResponse(
            status_code=401, content={"detail": "missing or invalid API key"}
        )
    return await call_next(request)


class FetchRequest(BaseModel):
    upstream: str
    url: str
    method: str = "GET"
    body_b64: str | None = None
    max_cache_age_s: float | None = Field(default=None, ge=0.0, le=3600.0)


@app.get("/healthz")
def healthz() -> dict:
    # Unauthenticated liveness probe — deliberately minimal. The upstream list
    # is capability-revealing, so it lives on the authenticated /v1/metrics.
    return {"status": "ok"}


@app.get("/v1/identity")
def identity() -> dict:
    """Authenticated proof that two ingress URLs reach the same installation."""
    return {
        "service": "rate-guard",
        "instance_id": INSTANCE_ID,
        "process_id": PROCESS_ID,
        "version": app.version,
    }


@app.post("/v1/fetch")
def fetch(req: FetchRequest) -> dict:
    try:
        body = base64.b64decode(req.body_b64) if req.body_b64 else b""
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="body_b64 is not valid base64")
    try:
        return _gateway.fetch(
            req.upstream,
            req.method,
            req.url,
            body,
            max_cache_age_s=req.max_cache_age_s,
        )
    except UpstreamError as exc:
        # 502: Rate Guard reached (or refused to reach) the upstream and could
        # not return a usable response.
        raise HTTPException(
            status_code=502,
            detail={"upstream_status": exc.status, "detail": exc.detail},
        )


@app.get("/v1/metrics")
def metrics(upstream: str | None = None) -> dict:
    names = _gateway.upstream_names()
    selected = [upstream] if upstream else names
    return {
        "upstreams": {
            n: _gateway.metrics(n) for n in selected if n in names
        }
    }
