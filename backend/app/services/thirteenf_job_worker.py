from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.institutions import JobRun, JobWorkerHeartbeat

logger = logging.getLogger(__name__)


def record_worker_heartbeat(
    session: Session,
    *,
    worker_id: str,
    status: str,
    current_job_id: int | None = None,
    now: datetime | None = None,
) -> JobWorkerHeartbeat:
    now = now or datetime.now(timezone.utc)
    heartbeat = session.get(JobWorkerHeartbeat, worker_id)
    if heartbeat is None:
        heartbeat = JobWorkerHeartbeat(
            worker_id=worker_id,
            worker_type="13f_admin",
            hostname=socket.gethostname(),
            process_id=os.getpid(),
            status=status,
            current_job_id=current_job_id,
            last_heartbeat_at=now,
            started_at=now,
        )
    else:
        heartbeat.status = status
        heartbeat.current_job_id = current_job_id
        heartbeat.last_heartbeat_at = now
        heartbeat.hostname = socket.gethostname()
        heartbeat.process_id = os.getpid()
    session.add(heartbeat)
    session.commit()
    session.refresh(heartbeat)
    return heartbeat


def list_worker_heartbeats(
    session: Session,
    *,
    now: datetime | None = None,
    stale_after_seconds: int | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    stale_after_seconds = stale_after_seconds or settings.THIRTEENF_JOB_WORKER_HEARTBEAT_STALE_S
    cutoff = now - timedelta(seconds=stale_after_seconds)
    workers = session.query(JobWorkerHeartbeat).order_by(JobWorkerHeartbeat.last_heartbeat_at.desc()).all()
    return [_worker_payload(worker, cutoff=cutoff) for worker in workers]


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_seconds: int | None = None,
) -> JobRun | None:
    now = now or datetime.now(timezone.utc)
    lease_seconds = lease_seconds or settings.THIRTEENF_JOB_LEASE_SECONDS
    job = (
        session.query(JobRun)
        .filter(
            or_(
                JobRun.status == "queued",
                (JobRun.status == "running") & (JobRun.lease_expires_at.isnot(None)) & (JobRun.lease_expires_at < now),
            )
        )
        .order_by(JobRun.created_at.asc(), JobRun.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return None
    job.status = "running"
    job.worker_id = worker_id
    if job.started_at is None:
        job.started_at = now
    job.heartbeat_at = now
    job.lease_token = uuid.uuid4().hex
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def heartbeat_job_lease(
    session: Session,
    *,
    job_id: int,
    worker_id: str,
    lease_token: str,
    now: datetime | None = None,
    lease_seconds: int | None = None,
) -> JobRun | None:
    now = now or datetime.now(timezone.utc)
    lease_seconds = lease_seconds or settings.THIRTEENF_JOB_LEASE_SECONDS
    job = session.get(JobRun, job_id)
    if not _lease_owner_matches(job, worker_id=worker_id, lease_token=lease_token):
        return None
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def complete_leased_job(
    session: Session,
    *,
    job_id: int,
    worker_id: str,
    lease_token: str,
    status: str,
    summary_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    now: datetime | None = None,
) -> JobRun | None:
    now = now or datetime.now(timezone.utc)
    job = session.get(JobRun, job_id)
    if not _lease_owner_matches(job, worker_id=worker_id, lease_token=lease_token):
        return None
    job.status = status
    job.summary_json = summary_json
    job.error_message = error_message
    job.heartbeat_at = now
    job.finished_at = now
    job.lease_expires_at = None
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def mark_stale_running_jobs_abandoned(
    session: Session,
    *,
    now: datetime | None = None,
    timeout_seconds: int = 600,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    timeout_cutoff = now - timedelta(seconds=timeout_seconds)
    jobs = (
        session.query(JobRun)
        .filter(JobRun.status == "running")
        .filter(JobRun.started_at.isnot(None))
        .filter(JobRun.started_at < timeout_cutoff)
        .filter(JobRun.lease_expires_at.isnot(None))
        .filter(JobRun.lease_expires_at < now)
        .all()
    )
    for job in jobs:
        job.status = "failed"
        job.error_message = "job_lease_expired_or_timeout"
        job.finished_at = now
        session.add(job)
    session.commit()
    return {"abandoned": len(jobs)}


def execute_queued_job_once(session: Session, *, worker_id: str) -> JobRun | None:
    record_worker_heartbeat(session, worker_id=worker_id, status="idle")
    job = claim_next_job(session, worker_id=worker_id)
    if job is None:
        return None
    record_worker_heartbeat(session, worker_id=worker_id, status="running", current_job_id=job.id)
    from app.services import thirteenf_admin_dashboard
    from app.services.notifications import notify_job_completion

    try:
        payload = dict(job.input_json or {})
        payload["_job_id"] = job.id
        summary = thirteenf_admin_dashboard.execute_job_payload(session, job.job_type, payload)
        job = complete_leased_job(
            session,
            job_id=job.id,
            worker_id=worker_id,
            lease_token=job.lease_token,
            status=summary.pop("status", "succeeded"),
            summary_json=summary,
            now=datetime.now(timezone.utc),
        )
    except Exception as exc:
        session.rollback()
        job = complete_leased_job(
            session,
            job_id=job.id,
            worker_id=worker_id,
            lease_token=job.lease_token,
            status="failed",
            error_message=str(exc),
            now=datetime.now(timezone.utc),
        )
    finally:
        record_worker_heartbeat(session, worker_id=worker_id, status="idle")

    try:
        notify_job_completion(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            quarter=job.quarter,
            summary=job.summary_json or {},
            error_message=job.error_message,
        )
    except Exception:
        logger.warning("Failed to send job completion notification for job %s", job.id, exc_info=True)
    return job


def _lease_owner_matches(job: JobRun | None, *, worker_id: str, lease_token: str) -> bool:
    if job is None:
        return False
    return (
        job.status == "running"
        and job.worker_id == worker_id
        and bool(job.lease_token)
        and job.lease_token == lease_token
    )


class ThirteenFJobWorker:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        *,
        worker_id: str | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        self.db_factory = db_factory
        self.worker_id = worker_id or f"13f-worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.poll_interval_s = poll_interval_s or settings.THIRTEENF_JOB_WORKER_POLL_INTERVAL_S
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name=self.worker_id, daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        logger.info("13F job worker started: %s", self.worker_id)
        while not self._stop_event.is_set():
            session = self.db_factory()
            try:
                job = execute_queued_job_once(session, worker_id=self.worker_id)
                if job is None:
                    record_worker_heartbeat(session, worker_id=self.worker_id, status="idle")
            except Exception as exc:
                session.rollback()
                logger.exception("13F job worker loop failed: %s", exc)
                try:
                    record_worker_heartbeat(session, worker_id=self.worker_id, status="error")
                except Exception:
                    session.rollback()
            finally:
                session.close()
            self._stop_event.wait(self.poll_interval_s)
        session = self.db_factory()
        try:
            record_worker_heartbeat(session, worker_id=self.worker_id, status="stopped")
        finally:
            session.close()
        logger.info("13F job worker stopped: %s", self.worker_id)


def _worker_payload(worker: JobWorkerHeartbeat, *, cutoff: datetime) -> dict[str, Any]:
    status = worker.status
    if worker.last_heartbeat_at < cutoff and status not in {"stopped"}:
        status = "stale"
    return {
        "worker_id": worker.worker_id,
        "worker_type": worker.worker_type,
        "hostname": worker.hostname,
        "process_id": worker.process_id,
        "status": status,
        "current_job_id": worker.current_job_id,
        "last_heartbeat_at": worker.last_heartbeat_at.isoformat(),
        "started_at": worker.started_at.isoformat(),
        "updated_at": worker.updated_at.isoformat() if worker.updated_at else None,
    }
