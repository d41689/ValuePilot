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
from app.rate_guard import client as rg
from app.rate_guard.client import RateGuardFetchError

RATE_GUARD = "http://rate-guard:9000"


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
