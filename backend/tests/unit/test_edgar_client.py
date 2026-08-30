"""EdgarClient is a thin wrapper over RateGuardClient (upstream='edgar').

The shared POST /v1/fetch plumbing — success / 502 / unreachable / malformed
envelope — is covered by test_rate_guard_client.py; these tests only verify the
wrapper routes EDGAR fetches correctly and propagates failures.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.edgar.client import EdgarClient
from app.edgar import client as edgar_module
from app.rate_guard import client as rg
from app.rate_guard.client import RateGuardFetchError
from app.rate_guard.route_state import RateGuardRoute, clear_active_route, set_active_route

RATE_GUARD = "http://rate-guard:9000"


@pytest.fixture(autouse=True)
def _default_to_replay(monkeypatch):
    # Wrapper routing tests use a one-response transport. Live identity behavior
    # is covered explicitly below.
    monkeypatch.setattr(edgar_module.settings, "EDGAR_FETCH_MODE", "replay")
    monkeypatch.setattr(
        edgar_module.settings, "RATE_GUARD_ALLOW_LOCAL_FALLBACK", False
    )
    clear_active_route()
    yield
    clear_active_route()


def _rg_http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _envelope(body: bytes = b"ok", upstream_status: int = 200) -> httpx.Response:
    """A Rate Guard ``/v1/fetch`` success envelope."""
    return httpx.Response(
        200,
        json={
            "status": upstream_status,
            "headers": {},
            "body_b64": base64.b64encode(body).decode("ascii"),
            "cache": "miss",
        },
    )


def test_get_routes_through_rate_guard_as_the_edgar_upstream(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return _envelope(b"FILING-BYTES")

    with EdgarClient(http_client=_rg_http(handler)) as client:
        body = client.get("https://www.sec.gov/Archives/edgar/x.idx")

    assert body == b"FILING-BYTES"
    assert seen["url"] == "http://rate-guard:9000/v1/fetch"
    assert seen["payload"] == {
        "upstream": "edgar",
        "method": "GET",
        "url": "https://www.sec.gov/Archives/edgar/x.idx",
    }


def test_head_routes_method_head(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _envelope(b"")

    with EdgarClient(http_client=_rg_http(handler)) as client:
        client.head("https://www.sec.gov/probe")

    assert seen["payload"]["method"] == "HEAD"
    assert seen["payload"]["upstream"] == "edgar"


def test_upstream_404_propagates_with_status(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)

    with EdgarClient(http_client=_rg_http(lambda r: _envelope(b"", 404))) as client:
        with pytest.raises(RateGuardFetchError, match="404") as exc:
            client.get("https://www.sec.gov/missing")

    assert exc.value.status_code == 404  # the upstream status survives the wrapper


def test_base_constants_name_the_sec_hosts():
    assert EdgarClient.BASE == "https://www.sec.gov"
    assert EdgarClient.EFTS_BASE == "https://efts.sec.gov"
    assert EdgarClient.DATA_BASE == "https://data.sec.gov"


def test_edgar_fetch_carries_the_bearer_key_end_to_end(monkeypatch):
    """A per-upstream client (EdgarClient) must propagate the auth header to Rate
    Guard when RATE_GUARD_API_KEY is set — the header plumbing is shared, but this
    proves it end-to-end through a real per-upstream wrapper, not just the base
    RateGuardClient."""
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_API_KEY", "s3cret")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return _envelope(b"PAGE")

    with EdgarClient(http_client=_rg_http(handler)) as client:
        assert client.get("https://www.sec.gov/x") == b"PAGE"

    assert seen["auth"] == "Bearer s3cret"


def test_live_edgar_client_verifies_instance_before_it_can_fetch(monkeypatch):
    expected = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(edgar_module.settings, "EDGAR_FETCH_MODE", "live")
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(rg.settings, "RATE_GUARD_EXPECTED_INSTANCE_ID", expected)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "service": "rate-guard",
                "instance_id": expected,
                "version": "0.1.0",
            },
        )

    with EdgarClient(http_client=_rg_http(handler)):
        pass

    assert seen == ["/v1/identity"]


def test_live_cli_resolves_adaptive_route_without_fastapi_lifespan(monkeypatch):
    from app.rate_guard import routing

    expected = "22222222-2222-4222-8222-222222222222"
    monkeypatch.setattr(edgar_module.settings, "EDGAR_FETCH_MODE", "live")
    monkeypatch.setattr(edgar_module.settings, "RATE_GUARD_ALLOW_LOCAL_FALLBACK", True)
    calls: list[str] = []

    def resolve():
        calls.append("resolve")
        set_active_route(
            RateGuardRoute(
                "http://rate-guard-local:9000", expected, "fallback"
            )
        )
        return expected

    monkeypatch.setattr(routing, "verify_live_rate_guard", resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://rate-guard-local:9000/v1/identity"
        return httpx.Response(
            200,
            json={"service": "rate-guard", "instance_id": expected},
        )

    with EdgarClient(http_client=_rg_http(handler)):
        pass

    assert calls == ["resolve"]
