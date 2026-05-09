from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect

from app.models.institutions import (
    EDGAR_SYNC_STATUSES,
    JOB_RUN_STATUSES,
    MANAGER_STATUSES,
    NO_INDEX_REASONS,
    NO_INDEX_SOURCES,
    VALUE_UNIT_OVERRIDES,
    EdgarSyncStatus,
    InstitutionManager,
    JobRun,
    NoIndexExpectedDate,
)


def test_13f_schema_foundation_tables_and_columns_exist(db_session):
    inspector = inspect(db_session.bind)

    manager_columns = {column["name"] for column in inspector.get_columns("institution_managers")}
    assert {
        "canonical_name",
        "display_name",
        "edgar_legal_name",
        "cik",
        "status",
        "manager_type",
        "is_featured",
        "source",
        "source_url",
        "confidence_score",
        "value_unit_override",
        "confirmed_by",
        "confirmed_at",
        "review_note",
        "created_at",
        "updated_at",
    } <= manager_columns

    sync_columns = {column["name"] for column in inspector.get_columns("edgar_sync_status")}
    assert {
        "sync_date",
        "status",
        "started_at",
        "finished_at",
        "attempt_count",
        "last_error",
        "form_idx_url",
        "raw_document_id",
        "filings_seen_count",
        "tracked_13f_hr_found_count",
        "tracked_13f_nt_found_count",
        "created_at",
        "updated_at",
    } <= sync_columns

    no_index_columns = {column["name"] for column in inspector.get_columns("no_index_expected_dates")}
    assert {
        "date",
        "reason",
        "holiday_name",
        "source",
        "note",
        "active",
        "created_by",
        "created_at",
        "updated_at",
    } <= no_index_columns

    job_columns = {column["name"] for column in inspector.get_columns("job_runs")}
    assert {
        "sync_date",
        "lease_token",
        "lease_expires_at",
        "updated_at",
    } <= job_columns


def test_13f_schema_foundation_indexes_exist(db_session):
    inspector = inspect(db_session.bind)

    sync_indexes = {index["name"] for index in inspector.get_indexes("edgar_sync_status")}
    assert "idx_sync_status" in sync_indexes

    job_indexes = {index["name"] for index in inspector.get_indexes("job_runs")}
    assert "idx_job_runs" in job_indexes
    assert "uq_job_runs_active_lock_key" in job_indexes
    assert "ix_job_runs_sync_date" in job_indexes
    assert "ix_job_runs_lease_expires_at" in job_indexes

    manager_indexes = {index["name"] for index in inspector.get_indexes("institution_managers")}
    assert "ix_institution_managers_status" in manager_indexes
    assert "ix_institution_managers_cik_status" in manager_indexes


@pytest.mark.parametrize("status", sorted(MANAGER_STATUSES))
def test_manager_status_accepts_prd_statuses(status):
    manager = InstitutionManager(canonical_name="Test Manager", legal_name="Test Manager", status=status)

    assert manager.status == status


def test_manager_status_rejects_unknown_status():
    with pytest.raises(ValueError):
        InstitutionManager(canonical_name="Test Manager", legal_name="Test Manager", status="confirmed")


@pytest.mark.parametrize(
    ("match_status", "expected_status"),
    [
        ("confirmed", "active"),
        ("revoked", "needs_review"),
        ("rejected", "ignored"),
        ("candidate", "candidate"),
        ("seeded", "candidate"),
    ],
)
def test_legacy_match_status_populates_prd_status(db_session, match_status, expected_status):
    manager = InstitutionManager(legal_name="Legacy Manager", match_status=match_status)
    db_session.add(manager)
    db_session.flush()

    assert manager.canonical_name == "Legacy Manager"
    assert manager.status == expected_status


@pytest.mark.parametrize("value_unit_override", sorted(VALUE_UNIT_OVERRIDES))
def test_manager_value_unit_override_accepts_prd_values(value_unit_override):
    manager = InstitutionManager(
        canonical_name="Test Manager",
        legal_name="Test Manager",
        value_unit_override=value_unit_override,
    )

    assert manager.value_unit_override == value_unit_override


@pytest.mark.parametrize("status", sorted(EDGAR_SYNC_STATUSES))
def test_sync_status_accepts_prd_statuses(status):
    sync = EdgarSyncStatus(sync_date=date(2026, 5, 8), status=status)

    assert sync.status == status


@pytest.mark.parametrize("status", sorted(JOB_RUN_STATUSES))
def test_job_run_status_accepts_prd_statuses(status):
    job = JobRun(job_type="fetch_daily_index", lock_key="fetch_daily_index:2026-05-08", status=status)

    assert job.status == status


def test_job_run_lease_fields_round_trip(db_session):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    job = JobRun(
        job_type="fetch_daily_index",
        lock_key="fetch_daily_index:2026-05-08",
        status="running",
        sync_date=date(2026, 5, 8),
        lease_token="lease-token-1",
        lease_expires_at=expires_at,
    )
    db_session.add(job)
    db_session.flush()

    persisted = db_session.get(JobRun, job.id)
    assert persisted.sync_date == date(2026, 5, 8)
    assert persisted.lease_token == "lease-token-1"
    assert persisted.lease_expires_at is not None


@pytest.mark.parametrize("reason", sorted(NO_INDEX_REASONS))
@pytest.mark.parametrize("source", sorted(NO_INDEX_SOURCES))
def test_no_index_expected_date_accepts_prd_reason_and_source(reason, source):
    item = NoIndexExpectedDate(date=date(2026, 5, 9), reason=reason, source=source)

    assert item.reason == reason
    assert item.source == source


def test_no_index_expected_date_active_lookup_ignores_inactive_rows(db_session):
    inactive = NoIndexExpectedDate(
        date=date(2026, 5, 9),
        reason="edgar_special_closure",
        source="admin_manual",
        active=False,
    )
    active = NoIndexExpectedDate(
        date=date(2026, 5, 10),
        reason="weekend",
        source="auto_generated",
        active=True,
    )
    db_session.add_all([inactive, active])
    db_session.flush()

    assert NoIndexExpectedDate.active_for_date(db_session, date(2026, 5, 9)) is None
    assert NoIndexExpectedDate.active_for_date(db_session, date(2026, 5, 10)).date == date(2026, 5, 10)
