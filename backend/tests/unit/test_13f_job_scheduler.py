from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.institutions import EdgarSyncStatus, JobRun, NoIndexExpectedDate
from app.services.thirteenf_job_worker import (
    claim_next_job,
    complete_leased_job,
    execute_queued_job_once,
    heartbeat_job_lease,
    mark_stale_running_jobs_abandoned,
)
from app.services.thirteenf_scheduler import (
    mark_retry_exhausted_daily_syncs_no_data,
    queue_daily_sync_poll,
)


NOW = datetime(2026, 5, 9, 0, 30, tzinfo=timezone.utc)  # 20:30 ET on 2026-05-08


@pytest.fixture(autouse=True)
def _clear_scheduler_rows(db_session):
    db_session.query(JobRun).delete()
    db_session.query(EdgarSyncStatus).delete()
    db_session.query(NoIndexExpectedDate).delete()
    db_session.commit()


def _job(**overrides) -> JobRun:
    payload = {
        "job_type": "fetch_daily_index",
        "status": "queued",
        "trigger_source": "test",
        "sync_date": date(2026, 5, 8),
        "dedupe_key": "fetch_daily_index:2026-05-08",
        "lock_key": "fetch_daily_index:2026-05-08",
        "input_json": {"job_type": "fetch_daily_index", "sync_date": "2026-05-08"},
    }
    payload.update(overrides)
    return JobRun(**payload)


def test_second_worker_cannot_claim_unexpired_lease(db_session):
    db_session.add(_job())
    db_session.commit()

    claimed = claim_next_job(db_session, worker_id="worker-a", now=NOW, lease_seconds=300)
    second = claim_next_job(db_session, worker_id="worker-b", now=NOW + timedelta(seconds=60), lease_seconds=300)

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.worker_id == "worker-a"
    assert claimed.lease_token
    assert claimed.lease_expires_at == NOW + timedelta(seconds=300)
    assert second is None


def test_expired_lease_can_be_taken_over(db_session):
    job = _job(
        status="running",
        worker_id="worker-a",
        lease_token="old-token",
        lease_expires_at=NOW - timedelta(seconds=1),
        started_at=NOW - timedelta(minutes=10),
    )
    db_session.add(job)
    db_session.commit()

    claimed = claim_next_job(db_session, worker_id="worker-b", now=NOW, lease_seconds=300)

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.worker_id == "worker-b"
    assert claimed.lease_token != "old-token"
    assert claimed.lease_expires_at == NOW + timedelta(seconds=300)


def test_only_lease_owner_can_heartbeat_or_complete_job(db_session):
    db_session.add(_job())
    db_session.commit()
    claimed = claim_next_job(db_session, worker_id="worker-a", now=NOW, lease_seconds=300)

    assert claimed is not None
    assert heartbeat_job_lease(
        db_session,
        job_id=claimed.id,
        worker_id="worker-b",
        lease_token=claimed.lease_token,
        now=NOW + timedelta(seconds=30),
    ) is None
    assert complete_leased_job(
        db_session,
        job_id=claimed.id,
        worker_id="worker-b",
        lease_token=claimed.lease_token,
        status="succeeded",
        now=NOW + timedelta(seconds=60),
    ) is None

    refreshed = heartbeat_job_lease(
        db_session,
        job_id=claimed.id,
        worker_id="worker-a",
        lease_token=claimed.lease_token,
        now=NOW + timedelta(seconds=30),
        lease_seconds=300,
    )
    assert refreshed is not None
    completed = complete_leased_job(
        db_session,
        job_id=claimed.id,
        worker_id="worker-a",
        lease_token=refreshed.lease_token,
        status="succeeded",
        summary_json={"ok": True},
        now=NOW + timedelta(seconds=60),
    )
    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.summary_json == {"ok": True}


def test_duplicate_daily_sync_enqueue_is_skipped_while_active(db_session):
    first = queue_daily_sync_poll(db_session, now=NOW, target_date=date(2026, 5, 8))
    second = queue_daily_sync_poll(db_session, now=NOW, target_date=date(2026, 5, 8))

    assert first["queued"] == 1
    assert second["queued"] == 0
    assert second["skipped_active"] == 1
    assert db_session.query(JobRun).filter(JobRun.job_type == "fetch_daily_index").count() == 1


def test_hourly_poll_backfills_every_missing_date_after_the_latest_watermark(db_session):
    db_session.add(
        EdgarSyncStatus(
            sync_date=date(2026, 5, 4),
            status="success",
            attempt_count=1,
        )
    )
    db_session.commit()

    result = queue_daily_sync_poll(db_session, now=NOW)

    assert result["queued"] == 4
    assert [
        row.sync_date
        for row in db_session.query(JobRun)
        .filter(JobRun.job_type == "fetch_daily_index")
        .order_by(JobRun.sync_date.asc())
        .all()
    ] == [
        date(2026, 5, 5),
        date(2026, 5, 6),
        date(2026, 5, 7),
        date(2026, 5, 8),
    ]


def test_hourly_poll_repairs_an_internal_date_hole_before_the_latest_success(db_session):
    """Newest-first workers can advance the watermark before older jobs run."""
    db_session.add_all(
        [
            EdgarSyncStatus(sync_date=date(2026, 5, 4), status="success", attempt_count=1),
            EdgarSyncStatus(sync_date=date(2026, 5, 6), status="success", attempt_count=1),
            EdgarSyncStatus(sync_date=date(2026, 5, 7), status="success", attempt_count=1),
            EdgarSyncStatus(sync_date=date(2026, 5, 8), status="success", attempt_count=1),
        ]
    )
    db_session.commit()

    result = queue_daily_sync_poll(db_session, now=NOW)

    assert result["queued"] == 1
    job = db_session.query(JobRun).one()
    assert job.sync_date == date(2026, 5, 5)


def test_first_poll_uses_bounded_bootstrap_lookback(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.thirteenf_scheduler.settings.THIRTEENF_DAILY_SYNC_BOOTSTRAP_DAYS",
        3,
    )

    result = queue_daily_sync_poll(db_session, now=NOW)

    assert result["queued"] == 3
    assert [
        row.sync_date
        for row in db_session.query(JobRun)
        .filter(JobRun.job_type == "fetch_daily_index")
        .order_by(JobRun.sync_date.asc())
        .all()
    ] == [date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8)]


def test_gap_reconciliation_materializes_weekends_without_fetch_jobs(monkeypatch, db_session):
    monkeypatch.setattr(
        "app.services.thirteenf_scheduler.settings.THIRTEENF_DAILY_SYNC_BOOTSTRAP_DAYS",
        1,
    )
    db_session.add(
        EdgarSyncStatus(
            sync_date=date(2026, 5, 8),
            status="success",
            attempt_count=1,
        )
    )
    db_session.commit()
    monday_evening = datetime(2026, 5, 12, 0, 30, tzinfo=timezone.utc)  # Mon May 11, 20:30 ET

    result = queue_daily_sync_poll(db_session, now=monday_evening)

    assert result["queued"] == 1
    assert result["skipped_no_index"] == 2
    assert [row.sync_date for row in db_session.query(JobRun).all()] == [date(2026, 5, 11)]
    weekend_rows = (
        db_session.query(NoIndexExpectedDate)
        .order_by(NoIndexExpectedDate.date.asc())
        .all()
    )
    assert [(row.date, row.reason, row.source) for row in weekend_rows] == [
        (date(2026, 5, 9), "weekend", "auto_generated"),
        (date(2026, 5, 10), "weekend", "auto_generated"),
    ]


def test_hourly_polling_does_not_enqueue_today_before_earliest_attempt(monkeypatch, db_session):
    before_earliest = datetime(2026, 5, 8, 23, 0, tzinfo=timezone.utc)  # 19:00 ET
    monkeypatch.setattr("app.services.thirteenf_scheduler.settings.DAILY_SYNC_EARLIEST_ATTEMPT_ET", "20:00")

    result = queue_daily_sync_poll(db_session, now=before_earliest, target_date=date(2026, 5, 8))

    assert result["queued"] == 0
    assert result["skipped_before_earliest_attempt"] == 1
    assert db_session.query(JobRun).count() == 0


def test_retry_exhausted_after_end_of_day_marks_failed_sync_no_data(db_session):
    sync = EdgarSyncStatus(
        sync_date=date(2026, 5, 8),
        status="failed",
        attempt_count=3,
        last_error="HTTP 404 fetching daily index",
    )
    db_session.add(sync)
    db_session.commit()

    result = mark_retry_exhausted_daily_syncs_no_data(
        db_session,
        now=datetime(2026, 5, 9, 4, 30, tzinfo=timezone.utc),  # 00:30 ET next day
        max_attempts=3,
    )

    assert result == {"marked_no_data": 1}
    db_session.refresh(sync)
    assert sync.status == "no_data"
    assert "retry_exhausted" in sync.last_error


def test_watchdog_requires_timeout_and_expired_lease(db_session):
    expired_lease_recent_job = _job(
        status="running",
        lock_key="recent",
        dedupe_key="recent",
        started_at=NOW - timedelta(minutes=2),
        lease_expires_at=NOW - timedelta(seconds=1),
    )
    old_unexpired_lease = _job(
        status="running",
        lock_key="old-unexpired",
        dedupe_key="old-unexpired",
        started_at=NOW - timedelta(minutes=30),
        lease_expires_at=NOW + timedelta(minutes=5),
    )
    abandoned_target = _job(
        status="running",
        lock_key="abandon",
        dedupe_key="abandon",
        started_at=NOW - timedelta(minutes=30),
        lease_expires_at=NOW - timedelta(seconds=1),
    )
    db_session.add_all([expired_lease_recent_job, old_unexpired_lease, abandoned_target])
    db_session.commit()

    result = mark_stale_running_jobs_abandoned(db_session, now=NOW, timeout_seconds=600)

    assert result == {"abandoned": 1}
    db_session.refresh(expired_lease_recent_job)
    db_session.refresh(old_unexpired_lease)
    db_session.refresh(abandoned_target)
    assert expired_lease_recent_job.status == "running"
    assert old_unexpired_lease.status == "running"
    assert abandoned_target.status == "failed"
    assert abandoned_target.error_message == "job_lease_expired_or_timeout"


def test_watchdog_uses_per_job_type_timeouts_by_default(db_session):
    fetch_daily_index = _job(
        job_type="fetch_daily_index",
        status="running",
        lock_key="fetch",
        dedupe_key="fetch",
        started_at=NOW - timedelta(minutes=7),
        lease_expires_at=NOW - timedelta(seconds=1),
    )
    quarter_ingest = _job(
        job_type="ingest_holdings_for_quarter",
        status="running",
        lock_key="quarter",
        dedupe_key="quarter",
        started_at=NOW - timedelta(minutes=30),
        lease_expires_at=NOW - timedelta(seconds=1),
    )
    db_session.add_all([fetch_daily_index, quarter_ingest])
    db_session.commit()

    result = mark_stale_running_jobs_abandoned(db_session, now=NOW)

    assert result == {"abandoned": 1}
    db_session.refresh(fetch_daily_index)
    db_session.refresh(quarter_ingest)
    assert fetch_daily_index.status == "failed"
    assert quarter_ingest.status == "running"


def test_watchdog_recovers_timed_out_synchronous_stage_without_a_lease(db_session):
    """A process death can strand an in-process pipeline child without a lease."""
    stale_stage = _job(
        job_type="oracles_lens_score_backfill",
        status="running",
        lock_key="oracles_lens_score:2025-Q1:v1.0",
        dedupe_key="oracles_lens_score:2025-Q1:v1.0",
        started_at=NOW - timedelta(minutes=61),
        heartbeat_at=NOW - timedelta(minutes=61),
        lease_expires_at=None,
    )
    recent_stage = _job(
        job_type="oracles_lens_score_backfill",
        status="running",
        lock_key="oracles_lens_score:2025-Q2:v1.0",
        dedupe_key="oracles_lens_score:2025-Q2:v1.0",
        started_at=NOW - timedelta(minutes=59),
        heartbeat_at=NOW - timedelta(minutes=59),
        lease_expires_at=None,
    )
    db_session.add_all([stale_stage, recent_stage])
    db_session.commit()

    result = mark_stale_running_jobs_abandoned(db_session, now=NOW)

    assert result == {"abandoned": 1}
    db_session.refresh(stale_stage)
    db_session.refresh(recent_stage)
    assert stale_stage.status == "failed"
    assert stale_stage.finished_at == NOW
    assert stale_stage.error_message == "job_missing_lease_or_timeout"
    assert recent_stage.status == "running"


def test_fetch_daily_index_job_executes_daily_sync(db_session):
    db_session.add(_job())
    db_session.commit()
    claimed = claim_next_job(db_session, worker_id="worker-a", now=NOW, lease_seconds=300)

    with patch("app.services.thirteenf_daily_sync.run_daily_index_sync", return_value={"status": "success"}) as mock_sync:
        from app.services.thirteenf_admin_dashboard import execute_job_payload

        summary = execute_job_payload(
            db_session,
            "fetch_daily_index",
            {"sync_date": "2026-05-08", "_job_id": claimed.id},
        )

    assert summary["status"] == "succeeded"
    mock_sync.assert_called_once()
    assert mock_sync.call_args.args[1] == date(2026, 5, 8)


@pytest.mark.parametrize("form_type", ["13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"])
def test_daily_accession_hands_off_to_its_parsed_report_quarter(
    db_session,
    form_type,
):
    detail = {
        "filing_id": 123,
        "accession_number": "0001067983-26-000001",
        "report_quarter": "2026-Q1",
        "status": "succeeded",
    }
    with patch(
        "app.services.thirteenf_filing_detail.ingest_accession_filing_detail",
        return_value=detail,
    ), patch(
        "app.services.thirteenf_admin_dashboard.trigger_job",
        return_value={"id": 456, "conflict": False},
    ) as mock_trigger:
        from app.services.thirteenf_admin_dashboard import execute_job_payload

        summary = execute_job_payload(
            db_session,
            "ingest_accession",
            {
                "accession_no": detail["accession_number"],
                "manager_id": 9,
                "cik": "0001067983",
                "form_type": form_type,
                "source": "daily_index",
                "sync_date": "2026-05-15",
            },
        )

    mock_trigger.assert_called_once_with(
        db_session,
        requested_by_user_id=None,
        payload={
            "job_type": "quarterly_pipeline",
            "quarter": "2026-Q1",
            "trigger_source": "daily_sync",
        },
    )
    assert summary["quarter_refresh"] == {
        "quarter": "2026-Q1",
        "job_id": 456,
        "conflict": False,
    }


def test_daily_accession_does_not_guess_a_quarter_when_period_needs_review(db_session):
    with patch(
        "app.services.thirteenf_filing_detail.ingest_accession_filing_detail",
        return_value={
            "filing_id": 123,
            "accession_number": "0001067983-26-000001",
            "report_quarter": None,
            "status": "needs_review",
        },
    ), patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        from app.services.thirteenf_admin_dashboard import execute_job_payload

        summary = execute_job_payload(
            db_session,
            "ingest_accession",
            {
                "accession_no": "0001067983-26-000001",
                "manager_id": 9,
                "form_type": "13F-HR",
                "source": "daily_index",
                "sync_date": "2026-05-15",
            },
        )

    mock_trigger.assert_not_called()
    assert summary["quarter_refresh"] is None


def test_non_daily_accession_does_not_recursively_enqueue_a_quarter_pipeline(db_session):
    with patch(
        "app.services.thirteenf_filing_detail.ingest_accession_filing_detail",
        return_value={
            "filing_id": 123,
            "accession_number": "0001067983-26-000001",
            "report_quarter": "2026-Q1",
            "status": "succeeded",
        },
    ), patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        from app.services.thirteenf_admin_dashboard import execute_job_payload

        summary = execute_job_payload(
            db_session,
            "ingest_accession",
            {
                "accession_no": "0001067983-26-000001",
                "manager_id": 9,
                "form_type": "13F-HR",
                "source": "historical_backfill",
                "sync_date": "2026-05-15",
            },
        )

    mock_trigger.assert_not_called()
    assert summary["quarter_refresh"] is None


def test_multiple_daily_accessions_enqueue_exactly_one_quarter_refresh(db_session):
    """The real JobRun lock, not a mock, is the fan-in boundary for a busy day."""
    from app.services.thirteenf_admin_dashboard import execute_job_payload

    detail_results = [
        {
            "filing_id": 123,
            "accession_number": "0001067983-26-000001",
            "report_quarter": "2026-Q1",
            "status": "succeeded",
        },
        {
            "filing_id": 124,
            "accession_number": "0001067983-26-000002",
            "report_quarter": "2026-Q1",
            "status": "succeeded",
        },
    ]
    with patch(
        "app.services.thirteenf_filing_detail.ingest_accession_filing_detail",
        side_effect=detail_results,
    ):
        first = execute_job_payload(
            db_session,
            "ingest_accession",
            {
                "accession_no": "0001067983-26-000001",
                "manager_id": 9,
                "form_type": "13F-HR",
                "source": "daily_index",
                "sync_date": "2026-05-15",
            },
        )
        second = execute_job_payload(
            db_session,
            "ingest_accession",
            {
                "accession_no": "0001067983-26-000002",
                "manager_id": 10,
                "form_type": "13F-HR/A",
                "source": "daily_index",
                "sync_date": "2026-05-15",
            },
        )

    refreshes = (
        db_session.query(JobRun)
        .filter(JobRun.job_type == "quarterly_pipeline")
        .filter(JobRun.quarter == "2026-Q1")
        .all()
    )
    assert len(refreshes) == 1
    assert refreshes[0].lock_key == "quarterly_pipeline:2026-Q1"
    assert refreshes[0].trigger_source == "daily_sync"
    assert first["quarter_refresh"] == {
        "quarter": "2026-Q1",
        "job_id": refreshes[0].id,
        "conflict": False,
    }
    assert second["quarter_refresh"] == {
        "quarter": "2026-Q1",
        "job_id": refreshes[0].id,
        "conflict": True,
    }


def test_trigger_fetch_daily_index_job_sets_sync_date(db_session):
    from app.services.thirteenf_admin_dashboard import trigger_job

    result = trigger_job(
        db_session,
        requested_by_user_id=None,
        payload={"job_type": "fetch_daily_index", "sync_date": "2026-05-08", "trigger_source": "scheduler"},
    )

    job = db_session.get(JobRun, result["id"])
    assert job.sync_date == date(2026, 5, 8)
    assert job.dedupe_key == "fetch_daily_index:2026-05-08"
    assert job.lock_key == "fetch_daily_index:2026-05-08"


def test_execute_queued_job_once_renews_lease_during_long_job(monkeypatch, db_session):
    db_session.add(_job())
    db_session.commit()
    heartbeat_seen = threading.Event()
    heartbeat_calls: list[dict] = []

    def fake_heartbeat(session, **kwargs):
        heartbeat_calls.append(kwargs)
        heartbeat_seen.set()
        return object()

    def fake_execute_job_payload(session, job_type, payload):
        assert heartbeat_seen.wait(timeout=1.0)
        return {"status": "succeeded"}

    monkeypatch.setattr("app.services.thirteenf_job_worker.heartbeat_job_lease", fake_heartbeat)
    monkeypatch.setattr("app.services.thirteenf_admin_dashboard.execute_job_payload", fake_execute_job_payload)

    job = execute_queued_job_once(
        db_session,
        worker_id="worker-a",
        heartbeat_session_factory=lambda: object(),
        heartbeat_interval_s=0.01,
        lease_seconds=300,
    )

    assert job.status == "succeeded"
    assert heartbeat_calls
    assert heartbeat_calls[0]["worker_id"] == "worker-a"
    assert heartbeat_calls[0]["lease_token"]


def test_lease_heartbeat_thread_uses_detached_scalar_identity(monkeypatch):
    """The background thread must never dereference the main Session's job.

    SQLAlchemy expires ORM attributes on commit. Reading ``job.id`` or
    ``job.lease_token`` from the heartbeat thread can therefore issue SQL on
    the worker's concurrently-busy Session and raise ``InvalidRequestError``.
    A stand-in that permits each scalar to be read once pins the required
    capture-before-thread behavior without relying on a timing race.
    """
    from app.services.thirteenf_job_worker import _start_lease_heartbeat

    class ExpiringJob:
        def __init__(self):
            self._reads = {"id": 0, "lease_token": 0}

        @property
        def id(self):
            self._reads["id"] += 1
            if self._reads["id"] > 1:
                raise AssertionError("heartbeat thread dereferenced attached job.id")
            return 42

        @property
        def lease_token(self):
            self._reads["lease_token"] += 1
            if self._reads["lease_token"] > 1:
                raise AssertionError(
                    "heartbeat thread dereferenced attached job.lease_token"
                )
            return "lease-token"

    heartbeat_seen = threading.Event()
    monkeypatch.setattr(
        "app.services.thirteenf_job_worker.heartbeat_job_lease",
        lambda session, **kwargs: heartbeat_seen.set(),
    )

    stop = _start_lease_heartbeat(
        ExpiringJob(),
        worker_id="worker-a",
        heartbeat_session_factory=lambda: object(),
        heartbeat_interval_s=0.01,
        lease_seconds=300,
    )
    try:
        assert heartbeat_seen.wait(timeout=1.0)
    finally:
        stop()
