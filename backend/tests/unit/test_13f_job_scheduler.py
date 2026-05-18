from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.institutions import EdgarSyncStatus, JobRun
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
