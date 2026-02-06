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
        params={"refresh_token": payload["refresh_token"]},
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    refreshed = refresh_resp.json()
    assert refreshed["token_type"] == "bearer"
    assert refreshed["access_token"]


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
