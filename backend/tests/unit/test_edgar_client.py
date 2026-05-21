"""EdgarClient routes every EDGAR fetch through the Rate Guard egress service.

Rate Guard is simulated with an ``httpx.MockTransport`` returning the
``/v1/fetch`` envelope shape; no real network or Rate Guard process is needed.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.edgar import client as edgar_client
from app.edgar.client import EdgarClient, EdgarFetchError

RATE_GUARD = "http://rate-guard:9000"


def _rg_client(handler) -> httpx.Client:
    """An httpx client whose POSTs to Rate Guard are served by ``handler``."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _fetch_ok(body: bytes = b"ok", upstream_status: int = 200) -> httpx.Response:
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


def _reset_events() -> None:
    with edgar_client._REQUEST_EVENTS_LOCK:
        edgar_client._REQUEST_EVENTS.clear()


def test_get_routes_through_rate_guard(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["payload"] = json.loads(request.content)
        return _fetch_ok(b"FILING-BYTES")

    with EdgarClient(http_client=_rg_client(handler)) as client:
        body = client.get("https://www.sec.gov/Archives/edgar/x.idx")

    assert body == b"FILING-BYTES"
    assert seen["url"] == "http://rate-guard:9000/v1/fetch"
    assert seen["method"] == "POST"
    assert seen["payload"] == {
        "upstream": "edgar",
        "method": "GET",
        "url": "https://www.sec.gov/Archives/edgar/x.idx",
    }


def test_head_routes_method_head(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return _fetch_ok(b"")

    with EdgarClient(http_client=_rg_client(handler)) as client:
        client.head("https://www.sec.gov/probe")

    assert seen["payload"]["method"] == "HEAD"


def test_get_without_rate_guard_url_raises_and_does_not_fetch(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", None)
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _fetch_ok()

    with EdgarClient(http_client=_rg_client(handler)) as client:
        with pytest.raises(EdgarFetchError, match="RATE_GUARD_URL") as exc:
            client.get("https://www.sec.gov/x")

    assert exc.value.status_code is None
    assert calls == []  # the guard fires before any fetch is attempted


def test_upstream_non_200_raises(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return _fetch_ok(b"", upstream_status=404)

    with EdgarClient(http_client=_rg_client(handler)) as client:
        with pytest.raises(EdgarFetchError, match="404") as exc:
            client.get("https://www.sec.gov/missing")

    assert exc.value.status_code == 404  # the upstream 404 is recoverable


def test_rate_guard_502_raises(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={"detail": {"upstream_status": 403, "detail": "edgar returned 403"}},
        )

    with EdgarClient(http_client=_rg_client(handler)) as client:
        with pytest.raises(EdgarFetchError, match="Rate Guard") as exc:
            client.get("https://www.sec.gov/blocked")

    assert exc.value.status_code == 403  # the upstream 403 from the 502 detail


def test_rate_guard_unreachable_raises(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with EdgarClient(http_client=_rg_client(handler)) as client:
        with pytest.raises(EdgarFetchError, match="unreachable") as exc:
            client.get("https://www.sec.gov/x")

    assert exc.value.status_code is None  # not an upstream HTTP failure


def test_rate_guard_non_502_error_raises(monkeypatch):
    """A non-200/non-502 from Rate Guard itself (e.g. Rate Guard 503) raises
    EdgarFetchError with no upstream status."""
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)  # Rate Guard itself unavailable

    with EdgarClient(http_client=_rg_client(handler)) as client:
        with pytest.raises(EdgarFetchError, match="503") as exc:
            client.get("https://www.sec.gov/x")

    assert exc.value.status_code is None  # a Rate Guard fault, not an upstream status


def test_malformed_success_envelope_raises(monkeypatch):
    """A 200 from Rate Guard with a non-numeric status or an undecodable body
    raises EdgarFetchError, not a stray ValueError — a uniform error contract."""
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)

    def bad_status(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "?", "body_b64": "", "cache": "miss"})

    with EdgarClient(http_client=_rg_client(bad_status)) as client:
        with pytest.raises(EdgarFetchError, match="malformed"):
            client.get("https://www.sec.gov/x")

    def bad_body(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 200, "body_b64": "abc", "cache": "miss"})

    with EdgarClient(http_client=_rg_client(bad_body)) as client:
        with pytest.raises(EdgarFetchError, match="undecodable"):
            client.get("https://www.sec.gov/x")


def test_fetches_are_recorded_for_the_rate_limit_status(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "RATE_GUARD_URL", RATE_GUARD)
    monkeypatch.setattr(edgar_client.settings, "EDGAR_RATE_LIMIT_WINDOW_S", 60)
    _reset_events()

    with EdgarClient(http_client=_rg_client(lambda r: _fetch_ok(b"ok"))) as client:
        client.get("https://www.sec.gov/ok")

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502, json={"detail": {"upstream_status": 403, "detail": "403"}}
        )

    with EdgarClient(http_client=_rg_client(forbidden)) as client:
        with pytest.raises(EdgarFetchError):
            client.get("https://www.sec.gov/blocked")

    status = edgar_client.edgar_rate_limit_status()
    assert status["recent_request_count"] == 2
    assert status["recent_403_count"] == 1
    assert status["edgar_block_alert"] is True
    assert status["global_pause_until"] is None


def test_edgar_fetch_error_is_a_runtime_error():
    # EdgarFetchError subclasses RuntimeError so existing broad `except`
    # call sites (e.g. edgar_ingestion.py) keep catching it unchanged.
    assert issubclass(EdgarFetchError, RuntimeError)
