"""MVP3-08 admin UI endpoint contract tests.

Covers the five new routes added to thirteenf_admin.py:
  POST /admin/13f/backfill/preview
  POST /admin/13f/backfill/enqueue
  GET  /admin/13f/backfill/needs-validation
  POST /admin/13f/jobs/reparse-by-quarter/preview
  POST /admin/13f/jobs/reparse-by-quarter/enqueue

Auth gate, 400 on typed service errors, and response-shape assertions.
"""

from __future__ import annotations

from itertools import count
from unittest import mock

import pytest

from app.models.institutions import (
    JobRun,
    QualityFinding13F,
    QualityReport13F,
)

_EMAIL_SEQ = count(1)


def _admin(user_factory):
    return user_factory(email=f"admin-mvp308-{next(_EMAIL_SEQ)}@example.com", role="admin")


def _non_admin(user_factory):
    return user_factory(email=f"user-mvp308-{next(_EMAIL_SEQ)}@example.com", role="user")


# ---------------------------------------------------------------------------
# POST /admin/13f/backfill/preview
# ---------------------------------------------------------------------------


def test_backfill_preview_requires_admin(client, user_factory, auth_headers):
    response = client.post(
        "/api/v1/admin/13f/backfill/preview",
        headers=auth_headers(_non_admin(user_factory)),
        json={},
    )
    assert response.status_code in (401, 403)


def test_backfill_preview_returns_scope(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/backfill/preview",
        headers=auth_headers(admin),
        json={"start_quarter": "2024-Q1", "end_quarter": "2024-Q2"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["start_quarter"] == "2024-Q1"
    assert payload["end_quarter"] == "2024-Q2"
    assert "quarters" in payload
    assert isinstance(payload["quarters"], list)
    assert "value_unit_risk_warning" in payload
    assert "requires_dry_run" in payload
    assert payload["value_unit_risk_warning"] is False
    assert payload["requires_dry_run"] is False


def test_backfill_preview_flags_pre_2023_range(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/backfill/preview",
        headers=auth_headers(admin),
        json={"start_quarter": "2022-Q3", "end_quarter": "2023-Q1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["value_unit_risk_warning"] is True
    assert payload["requires_dry_run"] is True


def test_backfill_preview_uses_default_start_when_omitted(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/backfill/preview",
        headers=auth_headers(admin),
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    # Default start is 2023-Q1; result must not flag pre-2023 risk
    assert payload["value_unit_risk_warning"] is False
    assert payload["start_quarter"] == "2023-Q1"


# ---------------------------------------------------------------------------
# POST /admin/13f/backfill/enqueue
# ---------------------------------------------------------------------------


def test_backfill_enqueue_requires_admin(client, user_factory, auth_headers):
    response = client.post(
        "/api/v1/admin/13f/backfill/enqueue",
        headers=auth_headers(_non_admin(user_factory)),
        json={"start_quarter": "2024-Q1"},
    )
    assert response.status_code in (401, 403)


def test_backfill_enqueue_creates_job(client, db_session, user_factory, auth_headers):
    admin = _admin(user_factory)
    before = db_session.query(JobRun).filter_by(job_type="historical_backfill").count()
    response = client.post(
        "/api/v1/admin/13f/backfill/enqueue",
        headers=auth_headers(admin),
        json={"start_quarter": "2024-Q1", "end_quarter": "2024-Q2"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "job_id" in payload
    assert payload["status"] == "queued"
    assert "lock_key" in payload
    after = db_session.query(JobRun).filter_by(job_type="historical_backfill").count()
    assert after == before + 1


def test_backfill_enqueue_pre_2023_without_dry_run_returns_400(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/backfill/enqueue",
        headers=auth_headers(admin),
        json={"start_quarter": "2022-Q3", "end_quarter": "2023-Q1", "dry_run": False},
    )
    assert response.status_code == 400
    assert "dry_run" in response.json()["detail"].lower() or "pre-2023" in response.json()["detail"].lower()


def test_backfill_enqueue_pre_2023_with_dry_run_succeeds(client, db_session, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/backfill/enqueue",
        headers=auth_headers(admin),
        json={"start_quarter": "2022-Q3", "end_quarter": "2022-Q4", "dry_run": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["dry_run"] is True


def test_backfill_enqueue_duplicate_returns_400(client, db_session, user_factory, auth_headers):
    admin = _admin(user_factory)
    body = {"start_quarter": "2024-Q3", "end_quarter": "2024-Q4"}
    first = client.post("/api/v1/admin/13f/backfill/enqueue", headers=auth_headers(admin), json=body)
    assert first.status_code == 200, first.text

    second = client.post("/api/v1/admin/13f/backfill/enqueue", headers=auth_headers(admin), json=body)
    assert second.status_code == 400
    assert "already active" in second.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /admin/13f/backfill/needs-validation
# ---------------------------------------------------------------------------


def test_needs_validation_requires_admin(client, user_factory, auth_headers):
    response = client.get(
        "/api/v1/admin/13f/backfill/needs-validation",
        headers=auth_headers(_non_admin(user_factory)),
    )
    assert response.status_code in (401, 403)


def test_needs_validation_empty_when_no_findings(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.get(
        "/api/v1/admin/13f/backfill/needs-validation",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    payload = response.json()
    assert "quarters" in payload
    assert isinstance(payload["quarters"], list)


def test_needs_validation_lists_open_backfill_findings(client, db_session, user_factory, auth_headers):
    from app.services.thirteenf_historical_backfill import HISTORICAL_BACKFILL_RULE_CODE
    import datetime

    admin = _admin(user_factory)
    now = datetime.datetime.now(datetime.timezone.utc)
    report = QualityReport13F(
        quarter="2023-Q2",
        status="warning",
        error_count=0,
        warning_count=2,
        info_count=0,
        summary="backfill test",
        checked_at=now,
    )
    db_session.add(report)
    db_session.flush()
    for i in range(2):
        db_session.add(QualityFinding13F(
            validation_run_id=report.id,
            rule_code=HISTORICAL_BACKFILL_RULE_CODE,
            severity="warning",
            entity_type="filing",
            entity_id=i + 9000,
            quarter="2023-Q2",
            detail="needs validation",
            status="open",
            first_seen_at=now,
            last_seen_at=now,
        ))
    db_session.commit()

    response = client.get(
        "/api/v1/admin/13f/backfill/needs-validation",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    quarters = response.json()["quarters"]
    match = next((q for q in quarters if q["quarter"] == "2023-Q2"), None)
    assert match is not None
    assert match["open_count"] == 2


# ---------------------------------------------------------------------------
# POST /admin/13f/jobs/reparse-by-quarter/preview
# ---------------------------------------------------------------------------


def test_reparse_quarter_preview_requires_admin(client, user_factory, auth_headers):
    response = client.post(
        "/api/v1/admin/13f/jobs/reparse-by-quarter/preview",
        headers=auth_headers(_non_admin(user_factory)),
        json={"quarter": "2024-Q1"},
    )
    assert response.status_code in (401, 403)


def test_reparse_quarter_preview_requires_quarter(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/jobs/reparse-by-quarter/preview",
        headers=auth_headers(admin),
        json={},
    )
    assert response.status_code == 400


def test_reparse_quarter_preview_returns_scope(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/jobs/reparse-by-quarter/preview",
        headers=auth_headers(admin),
        json={"quarter": "2024-Q1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scope"]["kind"] == "quarter"
    assert payload["scope"]["value"] == "2024-Q1"
    assert "candidate_filings" in payload
    assert "estimated_scope" in payload
    assert "lock_key" in payload
    assert payload["requires_confirmation"] is True


# ---------------------------------------------------------------------------
# POST /admin/13f/jobs/reparse-by-quarter/enqueue
# ---------------------------------------------------------------------------


def test_reparse_quarter_enqueue_requires_admin(client, user_factory, auth_headers):
    response = client.post(
        "/api/v1/admin/13f/jobs/reparse-by-quarter/enqueue",
        headers=auth_headers(_non_admin(user_factory)),
        json={"quarter": "2024-Q1"},
    )
    assert response.status_code in (401, 403)


def test_reparse_quarter_enqueue_requires_quarter(client, user_factory, auth_headers):
    admin = _admin(user_factory)
    response = client.post(
        "/api/v1/admin/13f/jobs/reparse-by-quarter/enqueue",
        headers=auth_headers(admin),
        json={},
    )
    assert response.status_code == 400


def test_reparse_quarter_enqueue_creates_job(client, db_session, user_factory, auth_headers):
    admin = _admin(user_factory)
    before = db_session.query(JobRun).filter_by(job_type="batch_reparse_by_quarter").count()
    response = client.post(
        "/api/v1/admin/13f/jobs/reparse-by-quarter/enqueue",
        headers=auth_headers(admin),
        json={"quarter": "2024-Q1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "job_id" in payload
    assert payload["status"] == "queued"
    assert payload["job_type"] == "batch_reparse_by_quarter"
    after = db_session.query(JobRun).filter_by(job_type="batch_reparse_by_quarter").count()
    assert after == before + 1


def test_reparse_quarter_enqueue_duplicate_returns_400(client, db_session, user_factory, auth_headers):
    admin = _admin(user_factory)
    body = {"quarter": "2024-Q2"}
    first = client.post("/api/v1/admin/13f/jobs/reparse-by-quarter/enqueue", headers=auth_headers(admin), json=body)
    assert first.status_code == 200, first.text

    second = client.post("/api/v1/admin/13f/jobs/reparse-by-quarter/enqueue", headers=auth_headers(admin), json=body)
    assert second.status_code == 400
    assert "already active" in second.json()["detail"].lower()
