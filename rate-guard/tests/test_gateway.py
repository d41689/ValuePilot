import base64
import time

import httpx
import pytest

from app.cache import ResponseCache
from app.config import Upstream
from app.gateway import Gateway, UpstreamError


def _upstream(**overrides) -> Upstream:
    base = dict(
        name="test",
        allowed_hosts=("example.com",),
        rate_per_sec=1000.0,
        burst=10,
        max_retries=2,
        backoff_s=(0.0,),
        pause_s=0.0,
        cache_ttl_s=0.0,
    )
    base.update(overrides)
    return Upstream(**base)


def _gateway(tmp_path, handler, upstreams=None) -> Gateway:
    upstreams = upstreams or {"test": _upstream()}
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Gateway(upstreams, ResponseCache(str(tmp_path)), client=client)


def test_rejects_unknown_upstream(tmp_path):
    gw = _gateway(tmp_path, lambda r: httpx.Response(200))
    with pytest.raises(UpstreamError):
        gw.fetch("nope", "GET", "https://example.com/x")


def test_rejects_host_not_in_allowlist(tmp_path):
    gw = _gateway(tmp_path, lambda r: httpx.Response(200))
    with pytest.raises(UpstreamError):
        gw.fetch("test", "GET", "https://evil.example.org/x")


def test_successful_fetch_returns_body(tmp_path):
    gw = _gateway(tmp_path, lambda r: httpx.Response(200, content=b"hello"))
    out = gw.fetch("test", "GET", "https://example.com/x")
    assert out["status"] == 200
    assert base64.b64decode(out["body_b64"]) == b"hello"
    assert out["cache"] == "miss"


def test_cache_hit_skips_the_second_upstream_call(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"cached-body")

    gw = _gateway(tmp_path, handler, {"test": _upstream(cache_ttl_s=3600.0)})
    first = gw.fetch("test", "GET", "https://example.com/x")
    second = gw.fetch("test", "GET", "https://example.com/x")

    assert first["cache"] == "miss"
    assert second["cache"] == "hit"
    assert len(calls) == 1
    assert base64.b64decode(second["body_b64"]) == b"cached-body"


def test_403_raises_immediately_without_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403)

    gw = _gateway(tmp_path, handler)
    with pytest.raises(UpstreamError) as exc:
        gw.fetch("test", "GET", "https://example.com/x")
    assert exc.value.status == 403
    assert len(calls) == 1  # 403 is not retried


def test_retries_5xx_then_succeeds(tmp_path):
    statuses = [500, 503, 200]

    def handler(request):
        return httpx.Response(statuses.pop(0), content=b"ok")

    gw = _gateway(
        tmp_path, handler, {"test": _upstream(max_retries=4, backoff_s=(0.0,))}
    )
    out = gw.fetch("test", "GET", "https://example.com/x")
    assert out["status"] == 200


def test_retries_exhausted_raises(tmp_path):
    gw = _gateway(
        tmp_path,
        lambda r: httpx.Response(500),
        {"test": _upstream(max_retries=1, backoff_s=(0.0,))},
    )
    with pytest.raises(UpstreamError):
        gw.fetch("test", "GET", "https://example.com/x")


def test_429_global_pause_is_respected_before_retry(tmp_path):
    """A 429 arms a global pause; the retry must wait it out, not just its
    own backoff."""
    statuses = [429, 200]

    def handler(request):
        return httpx.Response(statuses.pop(0), content=b"ok")

    gw = _gateway(
        tmp_path,
        handler,
        {"test": _upstream(max_retries=2, backoff_s=(0.0,), pause_s=0.3)},
    )
    start = time.monotonic()
    out = gw.fetch("test", "GET", "https://example.com/x")
    elapsed = time.monotonic() - start

    assert out["status"] == 200
    # Backoff is 0s — the only delay is the 0.3s global pause being respected.
    assert elapsed >= 0.25


def test_rejects_non_https_url(tmp_path):
    gw = _gateway(tmp_path, lambda r: httpx.Response(200))
    with pytest.raises(UpstreamError):
        gw.fetch("test", "GET", "http://example.com/x")


def test_metrics_count_requests_and_cache(tmp_path):
    gw = _gateway(
        tmp_path,
        lambda r: httpx.Response(200, content=b"x"),
        {"test": _upstream(cache_ttl_s=3600.0)},
    )
    gw.fetch("test", "GET", "https://example.com/a")
    gw.fetch("test", "GET", "https://example.com/a")  # cache hit
    m = gw.metrics("test")
    assert m["recent_request_count"] == 1
    assert m["cache_hits"] == 1
    assert m["cache_misses"] == 1
