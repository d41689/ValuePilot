"""Rate Guard HTTP API.

    POST /v1/fetch     — fetch a URL via the upstream's rate limiter + cache
    GET  /v1/metrics   — per-upstream budget / cache snapshot
    GET  /healthz      — liveness
"""
from __future__ import annotations

import base64
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auth import is_authorized
from .cache import ResponseCache
from .config import build_upstreams
from .gateway import Gateway, UpstreamError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_cache = ResponseCache(os.environ.get("RATE_GUARD_CACHE_DIR", "/data/cache"))
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


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "upstreams": _gateway.upstream_names()}


@app.post("/v1/fetch")
def fetch(req: FetchRequest) -> dict:
    try:
        body = base64.b64decode(req.body_b64) if req.body_b64 else b""
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="body_b64 is not valid base64")
    try:
        return _gateway.fetch(req.upstream, req.method, req.url, body)
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
