from __future__ import annotations

from datetime import date

from app.models.institutions import NoIndexExpectedDate


def _admin(user_factory):
    return user_factory(email="13f-no-index-admin@example.com", role="admin")


def _clear_no_index_dates(db_session) -> None:
    db_session.query(NoIndexExpectedDate).delete()
    db_session.flush()


def test_admin_can_list_no_index_dates_by_year(client, db_session, user_factory, auth_headers):
    _clear_no_index_dates(db_session)
    admin = _admin(user_factory)
    db_session.add_all(
        [
            NoIndexExpectedDate(date=date(2024, 1, 1), reason="federal_holiday", source="auto_generated"),
            NoIndexExpectedDate(date=date(2025, 1, 1), reason="federal_holiday", source="auto_generated"),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/admin/13f/no-index-dates?year=2024", headers=auth_headers(admin))

    assert response.status_code == 200
    payload = response.json()
    assert [item["date"] for item in payload["items"]] == ["2024-01-01"]


def test_admin_can_create_manual_edgar_special_closure(client, db_session, user_factory, auth_headers):
    _clear_no_index_dates(db_session)
    admin = _admin(user_factory)

    response = client.post(
        "/api/v1/admin/13f/no-index-dates",
        headers=auth_headers(admin),
        json={
            "date": "2024-07-05",
            "reason": "edgar_special_closure",
            "holiday_name": "EDGAR special closure",
            "note": "SEC announced closure",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2024-07-05"
    assert payload["reason"] == "edgar_special_closure"
    assert payload["source"] == "admin_manual"
    assert payload["active"] is True


def test_admin_cannot_manually_create_auto_generated_no_index_reason(client, db_session, user_factory, auth_headers):
    _clear_no_index_dates(db_session)
    admin = _admin(user_factory)

    response = client.post(
        "/api/v1/admin/13f/no-index-dates",
        headers=auth_headers(admin),
        json={"date": "2024-07-06", "reason": "weekend"},
    )

    assert response.status_code == 400
    assert "auto_generated" in response.json()["detail"]
    assert db_session.query(NoIndexExpectedDate).count() == 0


def test_admin_patch_deactivates_no_index_date_without_deleting(client, db_session, user_factory, auth_headers):
    _clear_no_index_dates(db_session)
    admin = _admin(user_factory)
    db_session.add(
        NoIndexExpectedDate(
            date=date(2024, 7, 5),
            reason="edgar_special_closure",
            source="admin_manual",
            note="initial",
        )
    )
    db_session.commit()

    response = client.patch(
        "/api/v1/admin/13f/no-index-dates/2024-07-05",
        headers=auth_headers(admin),
        json={"active": False, "note": "re-enabled after correction"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["active"] is False
    assert payload["note"] == "re-enabled after correction"
    assert db_session.query(NoIndexExpectedDate).count() == 1
