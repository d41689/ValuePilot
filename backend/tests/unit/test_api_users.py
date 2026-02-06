from fastapi.testclient import TestClient

def test_create_user_api(client: TestClient, user_factory, auth_headers):
    admin = user_factory("api_admin@example.com", role="admin")
    response = client.post(
        "/api/v1/users/",
        headers=auth_headers(admin),
        json={"email": "api_test@example.com", "password": "StrongPass123!"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "api_test@example.com"
    assert "id" in data

def test_read_users_api(client: TestClient, user_factory, auth_headers):
    admin = user_factory("list_admin@example.com", role="admin")
    user_factory("list_test@example.com", role="user")

    response = client.get("/api/v1/users/", headers=auth_headers(admin))
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(u["email"] == "list_test@example.com" for u in data)

def test_create_duplicate_user(client: TestClient, user_factory, auth_headers):
    admin = user_factory("dup_admin@example.com", role="admin")
    client.post(
        "/api/v1/users/",
        headers=auth_headers(admin),
        json={"email": "dup@example.com", "password": "StrongPass123!"},
    )
    response = client.post(
        "/api/v1/users/",
        headers=auth_headers(admin),
        json={"email": "dup@example.com", "password": "StrongPass123!"},
    )
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]
