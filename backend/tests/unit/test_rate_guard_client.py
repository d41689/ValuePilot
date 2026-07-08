"""RateGuardClient — the shared POST /v1/fetch plumbing for the egress service.

Rate Guard is simulated with an ``httpx.MockTransport`` returning the
``/v1/fetch`` envelope shape; no real network or Rate Guard process is needed.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.rate_guard import client as rg
from app.rate_guard.client import RateGuardClient, RateGuardFetchError

RATE_GUARD = "http://rate-guard:9000"


def _rg_http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _envelope(body: bytes = b"ok", upstream_status: int = 200) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": upstream_status,
            "headers": {},
            "body_b64": base64.b64encode(body).decode("ascii"),
            "cache": "miss",
        },
    )


def test_get_routes_payload_through_rate_guard(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return _envelope(b"PAGE")

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        body = client.fetch(
            upstream="dataroma", method="GET", url="https://www.dataroma.com/x"
        )

    assert body == b"PAGE"
    assert seen["url"] == "http://rate-guard:9000/v1/fetch"
    assert seen["payload"] == {
        "upstream": "dataroma",
        "method": "GET",
        "url": "https://www.dataroma.com/x",
    }
    assert "body_b64" not in seen["payload"]  # no body for a GET


def test_post_body_is_base64_encoded(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _envelope(b"{}")

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        client.fetch(
            upstream="openfigi",
            method="POST",
            url="https://api.openfigi.com/v3/mapping",
            body=b'[{"x":1}]',
        )

    assert base64.b64decode(seen["payload"]["body_b64"]) == b'[{"x":1}]'
    assert seen["payload"]["method"] == "POST"


def test_unset_rate_guard_url_raises_and_does_not_fetch(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", None)
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _envelope()

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        with pytest.raises(RateGuardFetchError, match="RATE_GUARD_URL") as exc:
            client.fetch(upstream="dataroma", method="GET", url="https://www.dataroma.com/x")

    assert exc.value.status_code is None
    assert calls == []


def test_fetch_sends_bearer_when_api_key_set(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return _envelope(b"ok")

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")

    assert seen["auth"] == "Bearer s3cret"


def test_fetch_omits_auth_header_when_no_api_key(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", None)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return _envelope(b"ok")

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")

    assert seen["auth"] is None


def test_metrics_sends_bearer_when_api_key_set(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return _metrics_envelope({"edgar": {"x": 1}})

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        client.metrics("edgar")

    assert seen["auth"] == "Bearer s3cret"


def test_upstream_non_200_carries_status(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    with RateGuardClient(http_client=_rg_http(lambda r: _envelope(b"", 404))) as client:
        with pytest.raises(RateGuardFetchError, match="404") as exc:
            client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")

    assert exc.value.status_code == 404


def test_rate_guard_502_carries_upstream_status(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502, json={"detail": {"upstream_status": 403, "detail": "blocked"}}
        )

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        with pytest.raises(RateGuardFetchError) as exc:
            client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")

    assert exc.value.status_code == 403


def test_rate_guard_non_502_error_raises(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    with RateGuardClient(http_client=_rg_http(lambda r: httpx.Response(503))) as client:
        with pytest.raises(RateGuardFetchError, match="503") as exc:
            client.fetch(upstream="dataroma", method="GET", url="https://www.dataroma.com/x")

    assert exc.value.status_code is None


def test_rate_guard_unreachable_raises(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        with pytest.raises(RateGuardFetchError, match="unreachable") as exc:
            client.fetch(upstream="dataroma", method="GET", url="https://www.dataroma.com/x")

    assert exc.value.status_code is None


def test_malformed_envelope_raises(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def bad_status(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "?", "body_b64": "", "cache": "miss"})

    with RateGuardClient(http_client=_rg_http(bad_status)) as client:
        with pytest.raises(RateGuardFetchError, match="malformed"):
            client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")

    def bad_body(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 200, "body_b64": "abc", "cache": "miss"})

    with RateGuardClient(http_client=_rg_http(bad_body)) as client:
        with pytest.raises(RateGuardFetchError, match="undecodable"):
            client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")


def test_rate_guard_fetch_error_is_a_runtime_error():
    # Subclasses RuntimeError so existing broad `except` call sites keep working.
    assert issubclass(RateGuardFetchError, RuntimeError)


def _metrics_envelope(upstream_snaps: dict) -> httpx.Response:
    """A Rate Guard /v1/metrics response."""
    return httpx.Response(200, json={"upstreams": upstream_snaps})


def test_metrics_returns_a_single_upstream_snapshot(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _metrics_envelope(
            {"edgar": {"recent_request_count": 9, "recent_403_count": 1}}
        )

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        snap = client.metrics("edgar")

    assert seen["url"] == "http://rate-guard:9000/v1/metrics?upstream=edgar"
    assert snap == {"recent_request_count": 9, "recent_403_count": 1}


def test_metrics_without_upstream_returns_all(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return _metrics_envelope({"edgar": {"x": 1}, "openfigi": {"y": 2}})

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        snaps = client.metrics()

    assert set(snaps) == {"edgar", "openfigi"}


def test_metrics_raises_when_rate_guard_unreachable(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        with pytest.raises(RateGuardFetchError, match="unreachable"):
            client.metrics("edgar")


def test_metrics_raises_on_non_200(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    with RateGuardClient(http_client=_rg_http(lambda r: httpx.Response(500))) as client:
        with pytest.raises(RateGuardFetchError, match="500"):
            client.metrics("edgar")


def test_metrics_raises_on_malformed_json(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        with pytest.raises(RateGuardFetchError, match="malformed"):
            client.metrics("edgar")


def test_metrics_raises_when_upstreams_map_missing(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        with pytest.raises(RateGuardFetchError, match="upstreams"):
            client.metrics("edgar")


def test_metrics_raises_when_requested_upstream_absent(monkeypatch):
    """A valid response missing the requested upstream is a fault, not {}."""
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return _metrics_envelope({"openfigi": {"x": 1}})  # no "edgar"

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        with pytest.raises(RateGuardFetchError, match="edgar"):
            client.metrics("edgar")
