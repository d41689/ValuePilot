"""DataromaClient routes Dataroma page fetches through Rate Guard."""
from __future__ import annotations

import base64
import json

import httpx

from app.dataroma.client import DataromaClient
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


def test_get_holdings_routes_through_rate_guard(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _envelope(b"<html>holdings</html>")

    with DataromaClient(http_client=_rg_http(handler)) as client:
        body = client.get_holdings("BRK")

    assert body == b"<html>holdings</html>"
    assert seen["payload"]["upstream"] == "dataroma"
    assert seen["payload"]["method"] == "GET"
    assert seen["payload"]["url"] == "https://www.dataroma.com/m/holdings.php?m=BRK"


def test_get_managers_hits_the_managers_url(monkeypatch):
    monkeypatch.setattr(rg.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = json.loads(request.content)["url"]
        return _envelope(b"<html>managers</html>")

    with DataromaClient(http_client=_rg_http(handler)) as client:
        body = client.get_managers()

    assert body == b"<html>managers</html>"
    assert seen["url"] == "https://www.dataroma.com/m/managers.php"
