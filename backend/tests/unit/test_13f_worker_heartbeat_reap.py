from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.institutions import JobWorkerHeartbeat
from app.services.thirteenf_job_worker import reap_stale_worker_heartbeats


def _heartbeat(db_session, worker_id: str, *, status: str, age_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    db_session.add(
        JobWorkerHeartbeat(
            worker_id=worker_id,
            worker_type="13f_admin",
            hostname=worker_id,
            process_id=8,
            status=status,
            current_job_id=None,
            last_heartbeat_at=now - timedelta(seconds=age_seconds),
            started_at=now - timedelta(seconds=age_seconds + 60),
        )
    )
    db_session.commit()


def test_reap_marks_dead_worker_rows_stopped(db_session):
    db_session.query(JobWorkerHeartbeat).delete()
    db_session.commit()
    # Zombie rows abandoned by previous container instances.
    _heartbeat(db_session, "13f-worker-old1", status="idle", age_seconds=3600)
    _heartbeat(db_session, "13f-worker-old2", status="running", age_seconds=7200)
    # The freshly-started current worker.
    _heartbeat(db_session, "13f-worker-current", status="idle", age_seconds=1)

    result = reap_stale_worker_heartbeats(db_session, current_worker_id="13f-worker-current")

    assert result["reaped"] == 2
    assert db_session.get(JobWorkerHeartbeat, "13f-worker-old1").status == "stopped"
    assert db_session.get(JobWorkerHeartbeat, "13f-worker-old2").status == "stopped"
    # The current worker is never reaped, even though it is passed as an arg.
    assert db_session.get(JobWorkerHeartbeat, "13f-worker-current").status == "idle"


def test_reap_leaves_fresh_and_already_stopped_rows(db_session):
    db_session.query(JobWorkerHeartbeat).delete()
    db_session.commit()
    # A still-beating worker — e.g. an outgoing container briefly overlapping a
    # deploy — must not be reaped.
    _heartbeat(db_session, "13f-worker-fresh", status="idle", age_seconds=5)
    # An already-stopped row is left as-is.
    _heartbeat(db_session, "13f-worker-done", status="stopped", age_seconds=9000)

    result = reap_stale_worker_heartbeats(db_session, current_worker_id="13f-worker-current")

    assert result["reaped"] == 0
    assert db_session.get(JobWorkerHeartbeat, "13f-worker-fresh").status == "idle"
    assert db_session.get(JobWorkerHeartbeat, "13f-worker-done").status == "stopped"
