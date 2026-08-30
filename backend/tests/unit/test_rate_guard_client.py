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
from app.rate_guard.client import (
    RateGuardClient,
    RateGuardFetchError,
    RateGuardIdentityUnavailable,
)
from app.rate_guard.route_state import RateGuardRoute, clear_active_route, set_active_route

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


def _identity_envelope(
    instance_id: str = "11111111-1111-4111-8111-111111111111",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "service": "rate-guard",
            "instance_id": instance_id,
            "version": "0.1.0",
        },
    )


def test_existing_client_tracks_atomically_replaced_active_route(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", "http://wrong:9000")
    set_active_route(
        RateGuardRoute(
            base_url="https://primary.example",
            expected_instance_id="11111111-1111-4111-8111-111111111111",
            source="primary",
        )
    )
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _envelope()

    try:
        with RateGuardClient(http_client=_rg_http(handler)) as client:
            set_active_route(
                RateGuardRoute(
                    base_url="http://rate-guard-local:9000",
                    expected_instance_id="22222222-2222-4222-8222-222222222222",
                    source="fallback",
                )
            )
            client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")
    finally:
        clear_active_route()

    assert seen["url"] == "http://rate-guard-local:9000/v1/fetch"


def test_discover_identity_accepts_valid_authenticated_endpoint(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return _identity_envelope()

    with RateGuardClient(
        http_client=_rg_http(handler),
        base_url="https://primary.example",
        expected_instance_id=None,
    ) as client:
        actual = client.discover_identity()

    assert actual == "11111111-1111-4111-8111-111111111111"
    assert seen == {
        "url": "https://primary.example/v1/identity",
        "auth": "Bearer s3cret",
    }


@pytest.mark.parametrize("status", [502, 503, 504, 521, 522, 523, 524, 530])
def test_identity_origin_unavailable_is_typed_for_failover(monkeypatch, status):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    with RateGuardClient(
        http_client=_rg_http(lambda _request: httpx.Response(status)),
        base_url="https://primary.example",
        expected_instance_id=None,
    ) as client:
        with pytest.raises(RateGuardIdentityUnavailable):
            client.discover_identity()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500])
def test_identity_configuration_or_auth_failure_never_looks_offline(
    monkeypatch, status
):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    with RateGuardClient(
        http_client=_rg_http(lambda _request: httpx.Response(status)),
        base_url="https://primary.example",
        expected_instance_id=None,
    ) as client:
        with pytest.raises(RateGuardFetchError) as exc:
            client.discover_identity()

    assert not isinstance(exc.value, RateGuardIdentityUnavailable)


def test_verify_identity_accepts_expected_instance_and_sends_auth(monkeypatch):
    expected = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    monkeypatch.setattr(rg.settings, "RATE_GUARD_EXPECTED_INSTANCE_ID", expected)
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return _identity_envelope(expected)

    with RateGuardClient(http_client=_rg_http(handler)) as client:
        actual = client.verify_identity()

    assert actual == expected
    assert seen == {
        "url": "http://rate-guard:9000/v1/identity",
        "auth": "Bearer s3cret",
    }


def test_verify_identity_rejects_missing_expected_identity(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_EXPECTED_INSTANCE_ID", None)

    with RateGuardClient(http_client=_rg_http(lambda request: _identity_envelope())) as client:
        with pytest.raises(RateGuardFetchError, match="EXPECTED_INSTANCE_ID"):
            client.verify_identity()


def test_verify_identity_rejects_a_different_instance(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(
        rg.settings,
        "RATE_GUARD_EXPECTED_INSTANCE_ID",
        "11111111-1111-4111-8111-111111111111",
    )

    with RateGuardClient(
        http_client=_rg_http(
            lambda request: _identity_envelope(
                "22222222-2222-4222-8222-222222222222"
            )
        )
    ) as client:
        with pytest.raises(RateGuardFetchError, match="unexpected instance"):
            client.verify_identity()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"service": "wrong", "instance_id": "x"}),
    ],
)
def test_verify_identity_rejects_unverifiable_response(monkeypatch, response):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(
        rg.settings,
        "RATE_GUARD_EXPECTED_INSTANCE_ID",
        "11111111-1111-4111-8111-111111111111",
    )

    with RateGuardClient(http_client=_rg_http(lambda request: response)) as client:
        with pytest.raises(RateGuardFetchError, match="identity"):
            client.verify_identity()


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


def test_warns_when_key_would_go_over_plain_http_external(monkeypatch, caplog):
    """A key sent to a non-https off-box URL leaks in cleartext — warn once."""
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", "http://rate-guard.example.com")
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    rg._insecure_key_url_warned.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return _envelope(b"ok")

    with caplog.at_level("WARNING"):
        with RateGuardClient(http_client=_rg_http(handler)) as client:
            client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")

    assert any("cleartext" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "url",
    ["https://rate-guard.richmom.vip", "http://rate-guard:9000", "http://localhost:9099"],
)
def test_no_warning_for_https_or_internal_urls(monkeypatch, caplog, url):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", url)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    rg._insecure_key_url_warned.clear()

    with caplog.at_level("WARNING"):
        with RateGuardClient(http_client=_rg_http(lambda r: _envelope(b"ok"))) as client:
            client.fetch(upstream="edgar", method="GET", url="https://www.sec.gov/x")

    assert not any("cleartext" in r.message for r in caplog.records)
