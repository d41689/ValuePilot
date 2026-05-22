def test_register_login_me_refresh_flow(client):
    register_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "auth_flow@example.com", "password": "StrongPass123!"},
    )
    assert register_resp.status_code == 201, register_resp.text
    assert register_resp.json()["email"] == "auth_flow@example.com"

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "auth_flow@example.com", "password": "StrongPass123!"},
    )
    assert login_resp.status_code == 200, login_resp.text
    payload = login_resp.json()
    assert "access_token" in payload
    assert "refresh_token" in payload

    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me_resp.status_code == 200, me_resp.text
    assert me_resp.json()["email"] == "auth_flow@example.com"

    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": payload["refresh_token"]},
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    refreshed = refresh_resp.json()
    assert refreshed["token_type"] == "bearer"
    assert refreshed["access_token"]


def test_refresh_rejects_a_non_refresh_token(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "auth_reject@example.com", "password": "StrongPass123!"},
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "auth_reject@example.com", "password": "StrongPass123!"},
    )
    access_token = login_resp.json()["access_token"]

    # An access token must not be accepted where a refresh token is required.
    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token is not a refresh token"


def test_login_rejects_invalid_credentials(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "auth_invalid@example.com", "password": "StrongPass123!"},
    )

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "auth_invalid@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


def _login(client, email):
    """Register + login, returning the issued token pair."""
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "StrongPass123!"},
    )
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "StrongPass123!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_logout_revokes_the_refresh_token(client):
    tokens = _login(client, "auth_logout@example.com")

    logout = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert logout.status_code == 204, logout.text

    # The revoked token can no longer be exchanged.
    resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp.status_code == 401


def test_logout_is_idempotent(client):
    tokens = _login(client, "auth_logout_twice@example.com")

    first = client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    second = client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 204, first.text
    assert second.status_code == 204, second.text


def test_refresh_rotation_invalidates_the_old_token(client):
    tokens = _login(client, "auth_rotate@example.com")

    # Exchanging the refresh token rotates it: the response carries a new one.
    rotated = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert rotated.status_code == 200, rotated.text
    new_refresh = rotated.json()["refresh_token"]
    assert new_refresh != tokens["refresh_token"]

    # The freshly minted token carries the session forward...
    again = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_refresh}
    )
    assert again.status_code == 200, again.text

    # ...but the original, now-spent token is dead. (Replaying it also burns the
    # family — see test_reuse_detection_burns_the_whole_family — so this replay
    # is asserted last.)
    replay = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["detail"] == "Refresh token reuse detected"


def test_reuse_detection_burns_the_whole_family(client):
    tokens = _login(client, "auth_reuse@example.com")

    # A legitimate rotation chain: A -> B -> C.
    b = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    ).json()["refresh_token"]
    c = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": b}
    ).json()["refresh_token"]

    # Replaying the long-spent token A is a reuse: the family is burned.
    replay = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["detail"] == "Refresh token reuse detected"

    # The currently-live token C is revoked too — reuse anywhere in the family
    # invalidates the whole lineage.
    live = client.post("/api/v1/auth/refresh", json={"refresh_token": c})
    assert live.status_code == 401


def test_refresh_rejects_an_unknown_jti(client):
    """A validly-signed refresh token whose jti is not in the store — e.g. a
    token minted before this feature shipped — is rejected, not honoured."""
    from app.core.security import create_refresh_token

    forged = create_refresh_token(999999, "user", jti="jti-not-in-store")
    resp = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": forged}
    )
    assert resp.status_code == 401
