from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.institutions import EdgarSyncStatus, JobRun, NoIndexExpectedDate


ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}
RETRYABLE_SYNC_STATUSES = {"pending", "failed", "partial_success"}
EASTERN = ZoneInfo("America/New_York")


def queue_daily_sync_poll(
    session: Session,
    *,
    now: datetime | None = None,
    target_date: date | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    target_dates = [target_date] if target_date is not None else _eligible_sync_dates(session, now=now)
    queued = 0
    skipped_active = 0
    skipped_before_earliest = 0

    for sync_date in target_dates:
        if _is_today_in_eastern(sync_date, now) and not _past_earliest_attempt(now):
            skipped_before_earliest += 1
            continue
        if NoIndexExpectedDate.active_for_date(session, sync_date):
            continue
        dedupe_key = f"fetch_daily_index:{sync_date.isoformat()}"
        existing = (
            session.query(JobRun)
            .filter(JobRun.dedupe_key == dedupe_key)
            .filter(JobRun.status.in_(ACTIVE_JOB_STATUSES))
            .one_or_none()
        )
        if existing is not None:
            skipped_active += 1
            continue
        session.add(
            JobRun(
                job_type="fetch_daily_index",
                status="queued",
                trigger_source="scheduler",
                sync_date=sync_date,
                dedupe_key=dedupe_key,
                lock_key=dedupe_key,
                input_json={"job_type": "fetch_daily_index", "sync_date": sync_date.isoformat()},
            )
        )
        queued += 1
    session.commit()
    return {
        "queued": queued,
        "skipped_active": skipped_active,
        "skipped_before_earliest_attempt": skipped_before_earliest,
    }


def mark_retry_exhausted_daily_syncs_no_data(
    session: Session,
    *,
    now: datetime | None = None,
    max_attempts: int | None = None,
) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    max_attempts = max_attempts or settings.THIRTEENF_DAILY_SYNC_MAX_ATTEMPTS
    local_now = now.astimezone(EASTERN)
    rows = (
        session.query(EdgarSyncStatus)
        .filter(EdgarSyncStatus.status == "failed")
        .filter(EdgarSyncStatus.attempt_count >= max_attempts)
        .all()
    )
    marked = 0
    for row in rows:
        if NoIndexExpectedDate.active_for_date(session, row.sync_date):
            continue
        if not _end_of_day_passed(local_now, row.sync_date):
            continue
        row.status = "no_data"
        row.last_error = f"retry_exhausted_after_end_of_day: {row.last_error or ''}".strip()
        row.finished_at = now
        session.add(row)
        marked += 1
    session.commit()
    return {"marked_no_data": marked}


def _eligible_sync_dates(session: Session, *, now: datetime) -> list[date]:
    today_et = now.astimezone(EASTERN).date()
    rows = (
        session.query(EdgarSyncStatus.sync_date)
        .filter(EdgarSyncStatus.status.in_(RETRYABLE_SYNC_STATUSES))
        .order_by(EdgarSyncStatus.sync_date.desc())
        .all()
    )
    dates = [row.sync_date for row in rows]
    if today_et not in dates:
        dates.insert(0, today_et)
    return dates


def _is_today_in_eastern(sync_date: date, now: datetime) -> bool:
    return sync_date == now.astimezone(EASTERN).date()


def _past_earliest_attempt(now: datetime) -> bool:
    local_now = now.astimezone(EASTERN)
    return local_now.time() >= _configured_earliest_attempt_time()


def _configured_earliest_attempt_time() -> time:
    hour_text, minute_text = settings.DAILY_SYNC_EARLIEST_ATTEMPT_ET.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _end_of_day_passed(local_now: datetime, sync_date: date) -> bool:
    if local_now.date() > sync_date:
        return True
    return local_now.date() == sync_date and local_now.time() >= time(23, 59)
