from __future__ import annotations

import json

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    JobRun,
    JobWorkerHeartbeat,
    QualityReport13F,
    RawSourceDocument,
)


def _clear_13f(db_session) -> None:
    db_session.query(Holding13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(RawSourceDocument).delete()
    db_session.query(JobWorkerHeartbeat).delete()
    db_session.query(JobRun).delete()
    db_session.query(QualityReport13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _admin(user_factory):
    return user_factory(email="13f-manager-admin@example.com", role="admin")


def test_admin_can_create_manager_with_prd_defaults(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)

    response = client.post(
        "/api/v1/admin/13f/managers",
        headers=auth_headers(admin),
        json={"canonical_name": "Pershing Square", "manager_type": "activist", "is_featured": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["canonical_name"] == "Pershing Square"
    assert payload["display_name"] == "Pershing Square"
    assert payload["status"] == "candidate"
    assert payload["match_status"] == "candidate"
    assert payload["manager_type"] == "activist"
    assert payload["is_featured"] is True
    assert payload["value_unit_override"] == "infer"
    assert payload["cik"] is None


def test_admin_cannot_create_active_manager_directly(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)

    response = client.post(
        "/api/v1/admin/13f/managers",
        headers=auth_headers(admin),
        json={"canonical_name": "Unsafe Active Manager", "status": "active"},
    )

    assert response.status_code == 400
    assert "confirm-cik" in response.json()["detail"]
    assert db_session.query(InstitutionManager).count() == 0


def test_admin_can_patch_manager_without_confirming_cik(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = InstitutionManager(canonical_name="Old Name", legal_name="Old Name", match_status="candidate")
    db_session.add(manager)
    db_session.commit()

    response = client.patch(
        f"/api/v1/admin/13f/managers/{manager.id}",
        headers=auth_headers(admin),
        json={
            "display_name": "Updated Display",
            "manager_type": "fundamental_long",
            "source_url": "https://example.test/source",
            "confidence_score": 72,
            "review_note": "manual cleanup",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Updated Display"
    assert payload["manager_type"] == "fundamental_long"
    assert payload["source_url"] == "https://example.test/source"
    assert payload["confidence_score"] == 72
    assert payload["review_note"] == "manual cleanup"
    assert payload["status"] == "candidate"
    assert payload["cik"] is None


def test_admin_cannot_patch_status_active_directly(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = InstitutionManager(canonical_name="Candidate", legal_name="Candidate", match_status="candidate")
    db_session.add(manager)
    db_session.commit()

    response = client.patch(
        f"/api/v1/admin/13f/managers/{manager.id}",
        headers=auth_headers(admin),
        json={"status": "active"},
    )

    assert response.status_code == 400
    assert "confirm-cik" in response.json()["detail"]
    db_session.refresh(manager)
    assert manager.status == "candidate"
    assert manager.match_status == "candidate"
    assert manager.confirmed_by is None
    assert manager.confirmed_at is None


def test_deactivate_manager_removes_it_from_active_tracking(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = InstitutionManager(
        canonical_name="Active Manager",
        legal_name="Active Manager",
        cik="0001234567",
        match_status="confirmed",
        status="active",
    )
    db_session.add(manager)
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/deactivate",
        headers=auth_headers(admin),
        json={"note": "No longer tracked"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "inactive"
    assert payload["match_status"] == "inactive"
    assert payload["cik"] == "0001234567"
    assert payload["review_note"] == "No longer tracked"


def test_bulk_import_creates_candidate_managers_only(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)

    response = client.post(
        "/api/v1/admin/13f/managers/bulk-import",
        headers=auth_headers(admin),
        json={
            "csv_text": (
                "canonical_name,source_url,manager_type,is_featured,cik\n"
                "Akre Capital,https://example.test/akre,fundamental_long,true,0001166559\n"
                "Baupost Group,,unknown,false,\n"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_count"] == 2
    assert payload["skipped_count"] == 0
    managers = db_session.query(InstitutionManager).order_by(InstitutionManager.canonical_name.asc()).all()
    assert [manager.status for manager in managers] == ["candidate", "candidate"]
    assert [manager.match_status for manager in managers] == ["candidate", "candidate"]
    assert [manager.cik for manager in managers] == [None, None]
    assert managers[0].source_url == "https://example.test/akre"
    assert managers[0].is_featured is True


def test_confirm_cik_sets_active_status_and_does_not_enqueue_backfill(client, db_session, user_factory, auth_headers):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = InstitutionManager(
        canonical_name="Pershing Square",
        legal_name="Pershing Square",
        match_status="candidate",
        candidate_cik="1336528",
        candidate_legal_name="PERSHING SQUARE CAPITAL MANAGEMENT, L.P.",
    )
    db_session.add(manager)
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/13f/managers/{manager.id}/confirm-cik",
        headers=auth_headers(admin),
        json={"note": "SEC page matches"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "active"
    assert payload["match_status"] == "confirmed"
    assert payload["cik"] == "0001336528"
    assert payload["edgar_legal_name"] == "PERSHING SQUARE CAPITAL MANAGEMENT, L.P."
    assert payload["canonical_name"] == "Pershing Square"
    assert payload["confirmed_by"] == admin.id
    assert payload["confirmed_at"] is not None
    assert db_session.query(JobRun).count() == 0


def test_backfill_preview_estimates_without_enqueuing_jobs(client, db_session, user_factory, auth_headers, monkeypatch):
    _clear_13f(db_session)
    admin = _admin(user_factory)
    manager = InstitutionManager(
        canonical_name="Active Manager",
        legal_name="Active Manager",
        cik="0001234567",
        match_status="confirmed",
        status="active",
    )
    db_session.add(manager)
    db_session.commit()

    class FakeEdgarClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            return json.dumps(
                {
                    "cik": "1234567",
                    "name": "Active Manager",
                    "filings": {
                        "recent": {
                            "accessionNumber": ["0000000000-23-000001"],
                            "form": ["13F-HR"],
                            "filingDate": ["2023-05-15"],
                            "reportDate": ["2023-03-31"],
                        }
                    },
                }
            ).encode("utf-8")

    monkeypatch.setattr("app.edgar.client.EdgarClient", FakeEdgarClient)

    response = client.get(
        f"/api/v1/admin/13f/managers/{manager.id}/backfill-preview",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["manager_id"] == manager.id
    assert payload["status"] == "preview"
    assert payload["will_enqueue"] is False
    assert payload["estimated_request_count"] >= 1
    assert payload["estimated_rate_limit_wait_seconds"] >= 0
    assert db_session.query(JobRun).count() == 0
