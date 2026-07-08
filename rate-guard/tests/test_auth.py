"""Shared-key auth for Rate Guard's public surface.

Pure `is_authorized` logic is unit-tested directly; the middleware wiring
(which paths are gated, /healthz exempt) is exercised through the ASGI app with
`TestClient`. Importing `app.main` builds the upstream registry (needs
`SEC_CONTACT_EMAIL`) and a `ResponseCache` (needs a writable dir), so both are
provided before the import below.
"""
import os
import tempfile

os.environ.setdefault("SEC_CONTACT_EMAIL", "ci@example.com")
os.environ.setdefault("RATE_GUARD_CACHE_DIR", tempfile.mkdtemp(prefix="rg-cache-"))

import pytest
from fastapi.testclient import TestClient

from app.auth import is_authorized
from app.main import app


# --- pure logic -------------------------------------------------------------

def test_auth_disabled_when_no_key(monkeypatch):
    monkeypatch.delenv("RATE_GUARD_API_KEY", raising=False)
    assert is_authorized(None) is True
    assert is_authorized("Bearer whatever") is True


def test_whitespace_only_key_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "   ")
    assert is_authorized(None) is True


def test_missing_header_rejected_when_key_set(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert is_authorized(None) is False
    assert is_authorized("") is False


def test_wrong_or_malformed_header_rejected(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert is_authorized("Bearer nope") is False
    assert is_authorized("s3cret") is False        # scheme missing
    assert is_authorized("Basic s3cret") is False  # wrong scheme


def test_correct_bearer_accepted(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert is_authorized("Bearer s3cret") is True


# --- middleware wiring ------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthz_open_even_when_key_set(monkeypatch, client):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert client.get("/healthz").status_code == 200


def test_metrics_requires_key_when_set(monkeypatch, client):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert client.get("/v1/metrics").status_code == 401
    ok = client.get("/v1/metrics", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_fetch_rejected_before_any_upstream_call(monkeypatch, client):
    """No auth → 401 from the middleware, short-circuiting before the gateway
    would touch the network. (The correct-key path is not exercised here to
    avoid a real SEC fetch.)"""
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    resp = client.post(
        "/v1/fetch",
        json={"upstream": "edgar", "method": "GET", "url": "https://www.sec.gov/x"},
    )
    assert resp.status_code == 401


def test_endpoints_open_when_no_key(monkeypatch, client):
    monkeypatch.delenv("RATE_GUARD_API_KEY", raising=False)
    assert client.get("/v1/metrics").status_code == 200
