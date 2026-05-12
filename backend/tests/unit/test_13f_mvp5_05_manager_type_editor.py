"""MVP5-05 manager_type editor tests.

Two layers:
1. Pure service tests for ``update_manager_type`` — taxonomy
   validation, no-op when unchanged, audit row insertion.
2. Endpoint integration tests for the admin PATCH route — admin
   gating, 400 on invalid type, 404 on missing manager, history
   endpoint returns the audit events.
"""
from __future__ import annotations

from itertools import count

import pytest

from app.models.institutions import (
    InstitutionManager,
    InstitutionManagerTypeReviewEvent,
)
from app.services.manager_type_review import (
    ManagerTypeUpdateError,
    update_manager_type,
)


_CIK_SEQ = count(9970500000)


def _manager(db_session, *, manager_type: str = "unknown") -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv5-05 Mgr {cik}",
        legal_name=f"Mv5-05 Mgr {cik}",
        edgar_legal_name=f"Mv5-05 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type=manager_type,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


# ===========================================================================
# Service-layer tests
# ===========================================================================


def test_update_manager_type_writes_column_and_audit_event(db_session):
    manager = _manager(db_session, manager_type="unknown")
    result = update_manager_type(
        db_session,
        manager.id,
        new_manager_type="long_term_fundamental",
        reviewer_user_id=None,
        note="seeded admin classification",
    )
    assert result["changed"] is True
    assert result["old_manager_type"] == "unknown"
    assert result["new_manager_type"] == "long_term_fundamental"
    assert result["audit_event_id"] is not None

    refreshed = db_session.get(InstitutionManager, manager.id)
    assert refreshed.manager_type == "long_term_fundamental"

    events = (
        db_session.query(InstitutionManagerTypeReviewEvent)
        .filter(InstitutionManagerTypeReviewEvent.manager_id == manager.id)
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.old_manager_type == "unknown"
    assert event.new_manager_type == "long_term_fundamental"
    assert event.note == "seeded admin classification"


def test_update_manager_type_is_noop_when_unchanged(db_session):
    manager = _manager(db_session, manager_type="long_term_fundamental")
    result = update_manager_type(
        db_session,
        manager.id,
        new_manager_type="long_term_fundamental",
        reviewer_user_id=None,
        note="confirmed",
    )
    assert result["changed"] is False
    assert result["audit_event_id"] is None

    events = (
        db_session.query(InstitutionManagerTypeReviewEvent)
        .filter(InstitutionManagerTypeReviewEvent.manager_id == manager.id)
        .all()
    )
    assert events == [], "no-op must not write an audit row"


def test_update_manager_type_rejects_invalid_taxonomy(db_session):
    manager = _manager(db_session, manager_type="unknown")
    with pytest.raises(ManagerTypeUpdateError, match="new_manager_type must be one of"):
        update_manager_type(
            db_session,
            manager.id,
            new_manager_type="fundamental_long",  # legacy value, no longer valid
            reviewer_user_id=None,
        )


def test_update_manager_type_404_when_manager_missing(db_session):
    with pytest.raises(ManagerTypeUpdateError, match="manager not found"):
        update_manager_type(
            db_session,
            999_999_999,
            new_manager_type="long_term_fundamental",
            reviewer_user_id=None,
        )


# ===========================================================================
# Endpoint integration tests
# ===========================================================================


def test_endpoint_requires_admin(client, db_session, user_factory, auth_headers):
    manager = _manager(db_session)
    non_admin = user_factory(email="mvp5-05-non-admin@example.com", role="user")
    response = client.patch(
        f"/api/v1/admin/13f/managers/{manager.id}/manager-type",
        headers=auth_headers(non_admin),
        json={"new_manager_type": "long_term_fundamental"},
    )
    assert response.status_code in (401, 403)


def test_endpoint_updates_manager_type_and_returns_payload(
    client, db_session, user_factory, auth_headers,
):
    admin = user_factory(email="mvp5-05-admin@example.com", role="admin")
    manager = _manager(db_session, manager_type="unknown")

    response = client.patch(
        f"/api/v1/admin/13f/managers/{manager.id}/manager-type",
        headers=auth_headers(admin),
        json={
            "new_manager_type": "value_concentrated",
            "note": "concentrated top-10 confirmed",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["old_manager_type"] == "unknown"
    assert body["new_manager_type"] == "value_concentrated"
    assert body["audit_event_id"] is not None

    db_session.expire_all()
    refreshed = db_session.get(InstitutionManager, manager.id)
    assert refreshed.manager_type == "value_concentrated"


def test_endpoint_returns_400_on_invalid_taxonomy(
    client, db_session, user_factory, auth_headers,
):
    admin = user_factory(email="mvp5-05-admin-bad@example.com", role="admin")
    manager = _manager(db_session)
    response = client.patch(
        f"/api/v1/admin/13f/managers/{manager.id}/manager-type",
        headers=auth_headers(admin),
        json={"new_manager_type": "fundamental_long"},
    )
    assert response.status_code == 400
    assert "new_manager_type" in response.json()["detail"]


def test_endpoint_returns_404_when_manager_missing(
    client, user_factory, auth_headers,
):
    admin = user_factory(email="mvp5-05-admin-404@example.com", role="admin")
    response = client.patch(
        "/api/v1/admin/13f/managers/999999999/manager-type",
        headers=auth_headers(admin),
        json={"new_manager_type": "long_term_fundamental"},
    )
    assert response.status_code == 404


def test_history_endpoint_returns_audit_events_newest_first(
    client, db_session, user_factory, auth_headers,
):
    admin = user_factory(email="mvp5-05-admin-history@example.com", role="admin")
    manager = _manager(db_session, manager_type="unknown")

    # First change: unknown → long_term_fundamental
    update_manager_type(
        db_session,
        manager.id,
        new_manager_type="long_term_fundamental",
        reviewer_user_id=admin.id,
        note="first classification",
    )
    # Second change: long_term_fundamental → value_concentrated
    update_manager_type(
        db_session,
        manager.id,
        new_manager_type="value_concentrated",
        reviewer_user_id=admin.id,
        note="reconsidered after deeper look",
    )

    response = client.get(
        f"/api/v1/admin/13f/managers/{manager.id}/manager-type-events",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    # Newest first.
    assert items[0]["new_manager_type"] == "value_concentrated"
    assert items[0]["old_manager_type"] == "long_term_fundamental"
    assert items[1]["new_manager_type"] == "long_term_fundamental"
    assert items[1]["old_manager_type"] == "unknown"
