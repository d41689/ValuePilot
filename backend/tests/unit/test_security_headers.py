"""Security response headers must be present on every API response.

PR #67 added security headers via Next.js ``headers()``, which decorates
Next-rendered page routes but NOT the ``/api/*`` paths Next rewrites to this
API. The API therefore sets its own headers (``add_security_headers`` middleware
in ``app.main``) so coverage is uniform site-wide. Keep the expected values in
sync with ``frontend/next.config.js``.
"""
from fastapi.testclient import TestClient

EXPECTED_SECURITY_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-frame-options": "SAMEORIGIN",
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


def _assert_security_headers(response) -> None:
    for key, value in EXPECTED_SECURITY_HEADERS.items():
        assert response.headers.get(key) == value, (
            f"{key}: expected {value!r}, got {response.headers.get(key)!r}"
        )


def test_security_headers_present_on_health(client: TestClient):
    _assert_security_headers(client.get("/health"))


def test_security_headers_present_on_api_routes(client: TestClient):
    # /api/* responses were the PR #67 review blocker. A GET on a POST-only
    # route answers 405 and still passes through the middleware.
    response = client.get("/api/v1/auth/login")
    assert response.status_code == 405
    _assert_security_headers(response)
