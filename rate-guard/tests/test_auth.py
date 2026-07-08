"""Shared-key auth for Rate Guard's public surface.

Pure logic (`is_authorized`, `configured_api_keys`, `enforce_auth_config`) is
unit-tested directly; the middleware wiring (which paths are gated, /healthz
exempt, with-key pass-through) is exercised through the ASGI app with
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

import app.main as main
from app.auth import (
    configured_api_keys,
    enforce_auth_config,
    is_authorized,
    public_auth_required,
)
from app.main import app


@pytest.fixture(autouse=True)
def _clear_key_env(monkeypatch):
    # Each test controls the key env explicitly; never inherit an ambient value.
    # Clear every RATE_GUARD_API_KEY* (labelled slots) + the require flag.
    ambient = [n for n in os.environ if n.startswith("RATE_GUARD_API_KEY")]
    for name in ambient + ["RATE_GUARD_REQUIRE_AUTH"]:
        monkeypatch.delenv(name, raising=False)


# --- pure logic -------------------------------------------------------------

def test_auth_disabled_when_no_key():
    assert is_authorized(None) is True
    assert is_authorized("Bearer whatever") is True
    assert configured_api_keys() == ()


def test_whitespace_only_key_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "   ")
    assert configured_api_keys() == ()
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
    assert is_authorized("bearer s3cret") is False  # case-sensitive scheme
    assert is_authorized("Bearer  s3cret") is False  # double space


def test_correct_bearer_accepted(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert is_authorized("Bearer s3cret") is True


def test_non_ascii_header_is_rejected_not_crashed(monkeypatch):
    """A high-byte Authorization value (uvicorn latin-1-decodes header bytes)
    must return False, never raise TypeError from secrets.compare_digest."""
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert is_authorized("Bearer \xe9\x80") is False
    assert is_authorized("Bearer \x80" + "s3cret") is False


def test_labelled_key_slots_all_accepted(monkeypatch):
    """RATE_GUARD_API_KEY plus any RATE_GUARD_API_KEY_<LABEL> are all accepted —
    a distinct client key and/or a rotation window."""
    monkeypatch.setenv("RATE_GUARD_API_KEY", "primary")
    monkeypatch.setenv("RATE_GUARD_API_KEY_DEVELOPMENT", "dev-box")
    monkeypatch.setenv("RATE_GUARD_API_KEY_PREVIOUS", "old-key")
    assert set(configured_api_keys()) == {"primary", "dev-box", "old-key"}
    assert is_authorized("Bearer primary") is True
    assert is_authorized("Bearer dev-box") is True
    assert is_authorized("Bearer old-key") is True
    assert is_authorized("Bearer neither") is False


def test_non_key_prefixed_var_is_not_a_key(monkeypatch):
    """Only RATE_GUARD_API_KEY* are keys; the require flag is not one."""
    monkeypatch.setenv("RATE_GUARD_REQUIRE_AUTH", "1")
    assert configured_api_keys() == ()


# --- startup config enforcement ---------------------------------------------

def test_enforce_raises_when_required_but_no_key(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_REQUIRE_AUTH", "1")
    assert public_auth_required() is True
    with pytest.raises(RuntimeError, match="refusing to start"):
        enforce_auth_config()


def test_enforce_ok_when_required_and_key_present(monkeypatch):
    monkeypatch.setenv("RATE_GUARD_REQUIRE_AUTH", "true")
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    enforce_auth_config()  # no raise


def test_enforce_only_warns_when_not_required_and_no_key(caplog):
    with caplog.at_level("WARNING"):
        enforce_auth_config()  # no raise
    assert any("auth is DISABLED" in r.message for r in caplog.records)


# --- middleware wiring ------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthz_open_and_minimal(monkeypatch, client):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    resp = client.get("/healthz")
    assert resp.status_code == 200
    # Liveness probe must not disclose the upstream list.
    assert resp.json() == {"status": "ok"}


def test_metrics_requires_key_when_set(monkeypatch, client):
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    assert client.get("/v1/metrics").status_code == 401
    ok = client.get("/v1/metrics", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_fetch_rejected_before_any_upstream_call(monkeypatch, client):
    """No auth → 401 from the middleware, short-circuiting before the gateway
    would touch the network."""
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    called = {"n": 0}

    def _boom(*a, **k):  # gateway must not be reached
        called["n"] += 1
        raise AssertionError("gateway.fetch must not run on an unauthenticated request")

    monkeypatch.setattr(main._gateway, "fetch", _boom)
    resp = client.post(
        "/v1/fetch",
        json={"upstream": "edgar", "method": "GET", "url": "https://www.sec.gov/x"},
    )
    assert resp.status_code == 401
    assert called["n"] == 0


def test_fetch_with_correct_key_passes_auth_and_reaches_gateway(monkeypatch, client):
    """The with-key happy path: auth passes THROUGH to the route, which calls the
    gateway (stubbed here to avoid a real SEC fetch)."""
    monkeypatch.setenv("RATE_GUARD_API_KEY", "s3cret")
    seen = {}

    def _stub(upstream, method, url, body):
        seen["args"] = (upstream, method, url)
        return {"status": 200, "headers": {}, "body_b64": "", "cache": "miss"}

    monkeypatch.setattr(main._gateway, "fetch", _stub)
    resp = client.post(
        "/v1/fetch",
        headers={"Authorization": "Bearer s3cret"},
        json={"upstream": "edgar", "method": "GET", "url": "https://www.sec.gov/x"},
    )
    assert resp.status_code == 200
    assert seen["args"] == ("edgar", "GET", "https://www.sec.gov/x")


def test_endpoints_open_when_no_key(client):
    assert client.get("/v1/metrics").status_code == 200
