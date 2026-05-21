"""OpenFigiClient routes /v3/mapping through Rate Guard; the stub serves replay."""
from __future__ import annotations

import base64
import json

import httpx

from app.openfigi import client as openfigi_module
from app.openfigi.client import OpenFigiClient
from app.rate_guard import client as rg

RATE_GUARD = "http://rate-guard:9000"


def _rg_http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _envelope(body: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": 200,
            "headers": {},
            "body_b64": base64.b64encode(body).decode("ascii"),
            "cache": "miss",
        },
    )


def test_map_cusips_routes_through_rate_guard(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(openfigi_module.settings, "EDGAR_FETCH_MODE", "live")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        openfigi_resp = [
            {"data": [{"ticker": "AAPL", "name": "Apple Inc"}]},
            {"error": "No identifier found."},
        ]
        return _envelope(json.dumps(openfigi_resp).encode())

    with OpenFigiClient(http_client=_rg_http(handler)) as client:
        results = client.map_cusips(["037833100", "000000000"])

    assert seen["payload"]["upstream"] == "openfigi"
    assert seen["payload"]["method"] == "POST"
    assert seen["payload"]["url"] == "https://api.openfigi.com/v3/mapping"
    sent_body = json.loads(base64.b64decode(seen["payload"]["body_b64"]))
    assert sent_body == [
        {"idType": "ID_CUSIP", "idValue": "037833100"},
        {"idType": "ID_CUSIP", "idValue": "000000000"},
    ]
    # Result parsing: a data list per CUSIP, [] for the error entry.
    assert results == [[{"ticker": "AAPL", "name": "Apple Inc"}], []]


def test_use_stub_skips_rate_guard(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _envelope(b"[]")

    with OpenFigiClient(use_stub=True, http_client=_rg_http(handler)) as client:
        results = client.map_cusips(["12345678X"])

    assert calls == []  # stub mode never calls Rate Guard
    assert len(results) == 1
    assert results[0][0]["ticker"].startswith("TICKER_")


def test_replay_mode_uses_stub(monkeypatch):
    monkeypatch.setattr(openfigi_module.settings, "EDGAR_FETCH_MODE", "replay")
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _envelope(b"[]")

    with OpenFigiClient(http_client=_rg_http(handler)) as client:
        results = client.map_cusips(["00001234X", "99991234X"])

    assert calls == []
    assert results[0] == []         # 0000... -> no match
    assert len(results[1]) == 2     # 9999... -> ambiguous
