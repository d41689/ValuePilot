from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, text

from app.models.sec_publication import SecEconomicClassificationReview
from app.models.stocks import Stock
from app.services.canonical_financials import reviewed_method_gate
from app.services import method_applicability


def _stock(db_session) -> Stock:
    stock = Stock(ticker="FT07API", exchange="NYSE", company_name="FT07 API Co")
    db_session.add(stock)
    db_session.commit()
    return stock


def test_method_review_endpoints_are_admin_only_and_db_timestamped(
    client, db_session, user_factory, auth_headers
) -> None:
    user = user_factory("ft07-api-user@example.com")
    admin = user_factory("ft07-api-admin@example.com", role="admin")
    stock = _stock(db_session)
    classification_payload = {
        "economic_class": "ordinary",
        "effective_from": "2020-01-01",
        "review_reason": "Reviewed operating model and regulated-industry status.",
    }

    forbidden = client.post(
        f"/api/v1/admin/stocks/{stock.id}/method-classification-reviews",
        headers=auth_headers(user),
        json=classification_payload,
    )
    assert forbidden.status_code == 403

    created = client.post(
        f"/api/v1/admin/stocks/{stock.id}/method-classification-reviews",
        headers=auth_headers(admin),
        json=classification_payload,
    )
    assert created.status_code == 201, created.text
    assert created.json()["reviewer_user_id"] == admin.id
    assert created.json()["economic_class"] == "ordinary"
    assert created.json()["known_at"]
    assert created.json()["created_txid"] > 0

    forged = client.post(
        f"/api/v1/admin/stocks/{stock.id}/method-risk-reviews",
        headers=auth_headers(admin),
        json={
            "risk_attribute": "high_sbc",
            "is_present": False,
            "effective_from": str(date(2020, 1, 1)),
            "review_reason": "Reviewed dilution evidence.",
            "known_at": "2000-01-01T00:00:00Z",
        },
    )
    assert forged.status_code == 422

    risk = client.post(
        f"/api/v1/admin/stocks/{stock.id}/method-risk-reviews",
        headers=auth_headers(admin),
        json={
            "risk_attribute": "high_sbc",
            "is_present": False,
            "effective_from": str(date(2020, 1, 1)),
            "review_reason": "Reviewed dilution evidence.",
        },
    )
    assert risk.status_code == 201, risk.text
    assert risk.json()["risk_attribute"] == "high_sbc"
    assert risk.json()["known_at"]


def test_classification_review_conflicts_are_typed_and_rollback_cleanly(
    client, db_session, user_factory, auth_headers
) -> None:
    admin = user_factory("ft07-conflict-admin@example.com", role="admin")
    stock = _stock(db_session)
    route = f"/api/v1/admin/stocks/{stock.id}/method-classification-reviews"
    original = client.post(
        route,
        headers=auth_headers(admin),
        json={
            "economic_class": "ordinary",
            "effective_from": "2020-01-01",
            "review_reason": "Initial reviewed classification.",
        },
    )
    assert original.status_code == 201, original.text
    original_id = original.json()["id"]

    overlap = client.post(
        route,
        headers=auth_headers(admin),
        json={
            "economic_class": "bank",
            "effective_from": "2025-01-01",
            "review_reason": "Missing exact supersession target.",
        },
    )
    assert overlap.status_code == 409, overlap.text
    assert overlap.json()["detail"]["code"] == "overlapping_method_review"
    assert db_session.scalar(
        select(func.count()).select_from(SecEconomicClassificationReview).where(
            SecEconomicClassificationReview.stock_id == stock.id
        )
    ) == 1
    unchanged = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2025, 1, 1),
    )
    assert unchanged.economic_class == "ordinary"

    invalid_interval = client.post(
        route,
        headers=auth_headers(admin),
        json={
            "economic_class": "bank",
            "effective_from": "2025-01-01",
            "effective_to": "2024-12-31",
            "review_reason": "Invalid interval.",
            "supersedes_review_id": original_id,
        },
    )
    assert invalid_interval.status_code == 409
    assert invalid_interval.json()["detail"]["code"] == "invalid_effective_interval"

    replacement = client.post(
        route,
        headers=auth_headers(admin),
        json={
            "economic_class": "bank",
            "effective_from": "2025-01-01",
            "review_reason": "Reviewed prospective classification.",
            "supersedes_review_id": original_id,
        },
    )
    assert replacement.status_code == 201, replacement.text

    stale = client.post(
        route,
        headers=auth_headers(admin),
        json={
            "economic_class": "reit",
            "effective_from": "2025-01-01",
            "review_reason": "Stale concurrent review attempt.",
            "supersedes_review_id": original_id,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "stale_review_supersession"
    assert db_session.scalar(
        select(func.count()).select_from(SecEconomicClassificationReview).where(
            SecEconomicClassificationReview.stock_id == stock.id
        )
    ) == 2
    current = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2025, 1, 1),
    )
    assert current.economic_class == "bank"
    assert current.reason_code == "owner_earnings_unsupported_for_bank"


def test_concurrent_admin_deactivation_is_typed_and_rollback_cleanly(
    client, db_session, user_factory, auth_headers, monkeypatch
) -> None:
    admin = user_factory("ft07-race-admin@example.com", role="admin")
    stock = _stock(db_session)
    route = f"/api/v1/admin/stocks/{stock.id}/method-classification-reviews"
    original = client.post(
        route,
        headers=auth_headers(admin),
        json={
            "economic_class": "ordinary",
            "effective_from": "2020-01-01",
            "review_reason": "Initial reviewed classification.",
        },
    )
    assert original.status_code == 201, original.text
    original_id = original.json()["id"]
    real_lock = method_applicability._lock_review_slot

    def deactivate_after_validation(session, *, stock_id: int, kind: str) -> None:
        real_lock(session, stock_id=stock_id, kind=kind)
        session.execute(
            text("UPDATE users SET is_active=false WHERE id=:reviewer"),
            {"reviewer": admin.id},
        )

    monkeypatch.setattr(
        method_applicability, "_lock_review_slot", deactivate_after_validation
    )
    rejected = client.post(
        route,
        headers=auth_headers(admin),
        json={
            "economic_class": "bank",
            "effective_from": "2025-01-01",
            "review_reason": "Concurrent deactivation must fail closed.",
            "supersedes_review_id": original_id,
        },
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "reviewer_not_authorized"
    assert db_session.scalar(
        select(func.count()).select_from(SecEconomicClassificationReview).where(
            SecEconomicClassificationReview.stock_id == stock.id
        )
    ) == 1
    db_session.expire_all()
    assert db_session.get(type(admin), admin.id).is_active is True
    unchanged = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2025, 1, 1),
    )
    assert unchanged.economic_class == "ordinary"
