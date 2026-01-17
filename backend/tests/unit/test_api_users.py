from fastapi.testclient import TestClient

def test_create_user_api(client: TestClient):
    response = client.post("/api/v1/users/?email=api_test@example.com")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "api_test@example.com"
    assert "id" in data

def test_read_users_api(client: TestClient):
    # Create a user first
    client.post("/api/v1/users/?email=list_test@example.com")
    
    response = client.get("/api/v1/users/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Since tests run in a transaction that rolls back, we might see the user we just created
    # provided the client uses the same session. 
    # Our conftest overrides get_db with the *same* session fixture for the function scope.
    assert any(u["email"] == "list_test@example.com" for u in data)

def test_create_duplicate_user(client: TestClient):
    client.post("/api/v1/users/?email=dup@example.com")
    response = client.post("/api/v1/users/?email=dup@example.com")
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]
