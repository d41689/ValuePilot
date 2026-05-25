"""Admin tasks dedup — failed jobs superseded by a later success on
the same ``lock_key`` must not surface as P1/P2 tasks.

Task doc: ``docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md``

The motivating bug: JobRun #4526 failed (historical_backfill,
"Unsupported job_type"). JobRun #4553 with the same lock_key
succeeded 21 minutes later. The admin overview surfaced #4526 as a
P1 task even though the retry resolved the issue — pure noise.

These tests pin the dedup contract on
``_recent_job_alert_tasks``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

from app.models.institutions import JobRun
from app.services.thirteenf_admin_dashboard import _recent_job_alert_tasks


_LOCK_SEQ = count(99100000)


def _job(
    db_session,
    *,
    job_type: str = "historical_backfill",
    status: str,
    lock_key: str | None = None,
    quarter: str = "2025-Q4",
    created_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_message: str | None = None,
) -> JobRun:
    """Insert a JobRun directly. We don't go through enqueue() because
    that path enforces uniqueness constraints we want to bypass for
    fixture setup (we WANT to land two same-lock_key rows).
    """
    if lock_key is None:
        lock_key = f"lock-{next(_LOCK_SEQ)}"
    job = JobRun(
        job_type=job_type,
        status=status,
        trigger_source="test",
        lock_key=lock_key,
        dedupe_key=lock_key,
        quarter=quarter,
        input_json={"start_quarter": quarter, "end_quarter": quarter, "manager_ids": None, "dry_run": False},
        error_message=error_message,
    )
    db_session.add(job)
    db_session.flush()
    # SQLAlchemy server_default for created_at fires on flush but only
    # if the column wasn't explicitly set. For tests that want to
    # control ordering, override after flush.
    if created_at is not None:
        job.created_at = created_at
    if finished_at is not None:
        job.finished_at = finished_at
    db_session.flush()
    return job


def _task_codes_for_job(tasks: list[dict], job_id: int) -> list[str]:
    return [t["code"] for t in tasks if t.get("metadata", {}).get("job_id") == job_id]


# ---------------------------------------------------------------------------
# The hero case from JobRun #4526 / #4553
# ---------------------------------------------------------------------------


def test_failed_job_superseded_by_later_success_with_same_lock_key_is_hidden(db_session):
    """The exact scenario that motivated this PR: failed → succeeded
    21 minutes later under the same lock_key. The failure should NOT
    surface."""
    base = datetime.now(timezone.utc)
    lock = f"13f_historical_backfill:test-{next(_LOCK_SEQ)}"

    failed = _job(
        db_session,
        status="failed",
        lock_key=lock,
        created_at=base,
        finished_at=base + timedelta(seconds=5),
        error_message="Unsupported job_type: historical_backfill",
    )
    later_succeeded = _job(
        db_session,
        status="succeeded",
        lock_key=lock,
        created_at=base + timedelta(minutes=21),
        finished_at=base + timedelta(minutes=22),
    )

    tasks = _recent_job_alert_tasks(db_session)
    assert _task_codes_for_job(tasks, failed.id) == [], (
        f"failed job {failed.id} must be hidden because succeeded job "
        f"{later_succeeded.id} on the same lock_key=({lock}) ran later"
    )


# ---------------------------------------------------------------------------
# Non-supersession cases — these must still surface
# ---------------------------------------------------------------------------


def test_failed_job_with_no_later_success_still_surfaces(db_session):
    failed = _job(
        db_session,
        status="failed",
        error_message="something broke",
    )
    tasks = _recent_job_alert_tasks(db_session)
    assert _task_codes_for_job(tasks, failed.id) == ["RECENT_JOB_FAILED"], (
        "failed job with no superseding success must still surface as P1"
    )


def test_failed_job_with_later_success_on_different_lock_key_still_surfaces(db_session):
    """A successful job for a DIFFERENT logical operation must not
    accidentally hide an unrelated failure."""
    base = datetime.now(timezone.utc)
    lock_a = f"13f_historical_backfill:lock-A-{next(_LOCK_SEQ)}"
    lock_b = f"13f_historical_backfill:lock-B-{next(_LOCK_SEQ)}"

    failed_a = _job(
        db_session, status="failed", lock_key=lock_a, created_at=base,
        finished_at=base + timedelta(seconds=1),
    )
    _job(
        db_session, status="succeeded", lock_key=lock_b,
        created_at=base + timedelta(minutes=5),
        finished_at=base + timedelta(minutes=6),
    )

    tasks = _recent_job_alert_tasks(db_session)
    assert _task_codes_for_job(tasks, failed_a.id) == ["RECENT_JOB_FAILED"]


def test_failed_job_with_only_later_failed_on_same_lock_key_still_surfaces(db_session):
    """A retry that also failed does NOT supersede the prior failure —
    that's a persistent problem the admin still needs to see."""
    base = datetime.now(timezone.utc)
    lock = f"13f_historical_backfill:retry-failed-{next(_LOCK_SEQ)}"

    first_failed = _job(
        db_session, status="failed", lock_key=lock, created_at=base,
        finished_at=base + timedelta(seconds=1),
    )
    _job(
        db_session, status="failed", lock_key=lock,
        created_at=base + timedelta(minutes=10),
        finished_at=base + timedelta(minutes=10, seconds=1),
    )
    # Surface at least one — the latest failure. The contract is "if
    # nothing succeeded, surface failures"; we don't dedup
    # failure-after-failure here (that's a different UX feature).
    tasks = _recent_job_alert_tasks(db_session)
    surfaced_for_lock = [
        t for t in tasks
        if t.get("metadata", {}).get("job_id") in {first_failed.id}
    ]
    # The earlier failure should still surface because nothing
    # superseded it.
    assert any(t["code"] == "RECENT_JOB_FAILED" for t in surfaced_for_lock), (
        "earlier failure must still surface when no later succeeded job exists"
    )


def test_failed_job_superseded_by_later_partial_success_is_hidden(db_session):
    """partial_success means the system tried again and got further —
    surfacing the prior failure adds noise."""
    base = datetime.now(timezone.utc)
    lock = f"13f_historical_backfill:partial-{next(_LOCK_SEQ)}"

    failed = _job(
        db_session, status="failed", lock_key=lock, created_at=base,
        finished_at=base + timedelta(seconds=5),
    )
    _job(
        db_session, status="partial_success", lock_key=lock,
        created_at=base + timedelta(minutes=10),
        finished_at=base + timedelta(minutes=12),
    )

    tasks = _recent_job_alert_tasks(db_session)
    assert _task_codes_for_job(tasks, failed.id) == [], (
        "failure must be hidden when a later partial_success ran on "
        "the same lock_key"
    )


def test_failed_job_with_no_lock_key_still_surfaces(db_session):
    """Defense: not every job_type uses lock_key (legacy paths might
    leave it empty / blank). Dedup must NOT silently swallow such
    failures."""
    base = datetime.now(timezone.utc)
    failed = _job(
        db_session, status="failed", lock_key="",  # empty string
        created_at=base, finished_at=base + timedelta(seconds=1),
    )
    tasks = _recent_job_alert_tasks(db_session)
    assert _task_codes_for_job(tasks, failed.id) == ["RECENT_JOB_FAILED"]


# ---------------------------------------------------------------------------
# Ordering invariant — newer-finished failures show up first
# ---------------------------------------------------------------------------


def test_recent_job_alert_tasks_returns_newest_first(db_session):
    base = datetime.now(timezone.utc)
    older = _job(
        db_session, status="failed",
        created_at=base, finished_at=base + timedelta(seconds=1),
        error_message="old",
    )
    newer = _job(
        db_session, status="failed",
        created_at=base + timedelta(hours=1),
        finished_at=base + timedelta(hours=1, seconds=1),
        error_message="new",
    )
    tasks = _recent_job_alert_tasks(db_session)
    # Find positions of our two test jobs in the returned list.
    job_ids = [t.get("metadata", {}).get("job_id") for t in tasks]
    older_pos = job_ids.index(older.id)
    newer_pos = job_ids.index(newer.id)
    assert newer_pos < older_pos, (
        "newer failure should be ranked before older one"
    )
