from datetime import datetime

from app.models.artifacts import PdfDocument


def test_screener_requires_auth(client):
    resp = client.post("/api/v1/screener/run", json={"type": "AND", "conditions": []})
    assert resp.status_code == 401


def test_non_admin_cannot_access_admin_endpoints(client, user_factory, auth_headers):
    user = user_factory("plain_user@example.com", role="user")
    headers = auth_headers(user)

    list_resp = client.get("/api/v1/admin/users", headers=headers)
    assert list_resp.status_code == 403

    users_resp = client.get("/api/v1/users/", headers=headers)
    assert users_resp.status_code == 403


def test_admin_can_list_users(client, user_factory, auth_headers):
    admin = user_factory("admin_user@example.com", role="admin")
    user_factory("member_user@example.com", role="user")

    resp = client.get("/api/v1/admin/users", headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text
    emails = {row["email"] for row in resp.json()}
    assert "admin_user@example.com" in emails
    assert "member_user@example.com" in emails


def test_user_cannot_read_other_users_document(client, db_session, user_factory, auth_headers):
    owner = user_factory("owner_user@example.com")
    intruder = user_factory("intruder_user@example.com")

    doc = PdfDocument(
        user_id=owner.id,
        file_name="owned.pdf",
        source="upload",
        file_storage_key="/tmp/owned.pdf",
        parse_status="parsed",
        upload_time=datetime.utcnow(),
        raw_text="owner-only",
    )
    db_session.add(doc)
    db_session.commit()

    resp = client.get(f"/api/v1/documents/{doc.id}/raw_text", headers=auth_headers(intruder))
    assert resp.status_code == 404
