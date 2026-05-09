from __future__ import annotations

import httpx
import pytest

from app.edgar import client as edgar_client


class DummyBucket:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


class DummyHttpClient:
    def __init__(self, responses: list[int | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str) -> httpx.Response:
        self.calls.append((method, url))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        request = httpx.Request(method, url)
        return httpx.Response(response, content=b"ok", request=request)

    def close(self) -> None:
        return None


def _reset_events() -> None:
    with edgar_client._REQUEST_EVENTS_LOCK:
        edgar_client._REQUEST_EVENTS.clear()
        edgar_client._GLOBAL_PAUSE_UNTIL = None


def test_missing_sec_contact_email_fails_before_request(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "SEC_CONTACT_EMAIL", "")
    http_client = DummyHttpClient([200])
    test_client = edgar_client.EdgarClient(http_client=http_client)

    with pytest.raises(RuntimeError, match="SEC_CONTACT_EMAIL"):
        test_client.get("https://www.sec.gov/test")

    assert http_client.calls == []


def test_sec_client_sets_user_agent_from_contact_email(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "SEC_CONTACT_EMAIL", "ops@example.com")
    monkeypatch.setattr(edgar_client.settings, "PROJECT_NAME", "ValuePilot")

    user_agent = edgar_client.build_sec_user_agent()

    assert "ValuePilot" in user_agent
    assert "ops@example.com" in user_agent


def test_default_edgar_rate_limit_is_ten_requests_per_second(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "EDGAR_REQUESTS_PER_SECOND", 10.0)

    bucket = edgar_client._make_bucket()

    assert bucket._rate == 10.0


def test_rate_limiter_invoked_for_get_and_head(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "SEC_CONTACT_EMAIL", "ops@example.com")
    monkeypatch.setattr(edgar_client.settings, "EDGAR_MAX_RETRIES", 0)
    bucket = DummyBucket()
    http_client = DummyHttpClient([200, 200])
    monkeypatch.setattr(edgar_client, "_get_bucket", lambda: bucket)
    test_client = edgar_client.EdgarClient(http_client=http_client)

    test_client.get("https://www.sec.gov/test-get")
    test_client.head("https://www.sec.gov/test-head")

    assert bucket.calls == 2
    assert http_client.calls == [
        ("GET", "https://www.sec.gov/test-get"),
        ("HEAD", "https://www.sec.gov/test-head"),
    ]


def test_retry_policy_stops_after_configured_max_retries(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "SEC_CONTACT_EMAIL", "ops@example.com")
    monkeypatch.setattr(edgar_client.settings, "EDGAR_MAX_RETRIES", 2)
    monkeypatch.setattr(edgar_client.settings, "EDGAR_RETRY_BACKOFF_S", "0,0")
    monkeypatch.setattr(edgar_client.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(edgar_client, "_get_bucket", lambda: DummyBucket())
    http_client = DummyHttpClient([httpx.TransportError("network down")] * 3)
    test_client = edgar_client.EdgarClient(http_client=http_client)

    with pytest.raises(RuntimeError, match="failed after 2 retries"):
        test_client.get("https://www.sec.gov/test-retry")

    assert len(http_client.calls) == 3


def test_retry_backoff_is_capped_at_five_minutes():
    assert edgar_client._parse_backoff("5,30,120,600") == [5.0, 30.0, 120.0, 300.0]


def test_403_and_429_are_recorded_for_health_summary(monkeypatch):
    monkeypatch.setattr(edgar_client.settings, "SEC_CONTACT_EMAIL", "ops@example.com")
    monkeypatch.setattr(edgar_client.settings, "EDGAR_MAX_RETRIES", 0)
    monkeypatch.setattr(edgar_client.settings, "EDGAR_RATE_LIMIT_WINDOW_S", 60)
    monkeypatch.setattr(edgar_client, "_get_bucket", lambda: DummyBucket())
    monkeypatch.setattr(edgar_client.time, "sleep", lambda seconds: None)
    _reset_events()

    forbidden = edgar_client.EdgarClient(http_client=DummyHttpClient([403]))
    with pytest.raises(RuntimeError, match="EDGAR 403"):
        forbidden.get("https://www.sec.gov/test-403")

    throttled = edgar_client.EdgarClient(http_client=DummyHttpClient([429]))
    with pytest.raises(RuntimeError, match="failed after 0 retries"):
        throttled.get("https://www.sec.gov/test-429")

    status = edgar_client.edgar_rate_limit_status()

    assert status["recent_403_count"] == 1
    assert status["recent_429_count"] == 1
    assert status["edgar_block_alert"] is True
