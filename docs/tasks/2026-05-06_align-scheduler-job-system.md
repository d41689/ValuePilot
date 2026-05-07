# 2026-05-06 Align Scheduler with JobRun System

## Goal
Align the 13F ingestion scheduler with the new `JobRun` and `thirteenf_admin_dashboard` system to make the ingestion pipeline transparent, auditable, and visible in the Admin Dashboard.

## Acceptance Criteria
- [x] `backend/app/services/scheduler.py` uses `thirteenf_admin_dashboard.trigger_job` to start the quarterly pipeline.
- [x] A new job type `quarterly_pipeline` (or similar) is implemented in `thirteenf_admin_dashboard.py` that orchestrates the existing ingestion steps.
- [x] Scheduled jobs appear in the Admin Dashboard's "Jobs" tab.
- [x] The scheduler respects `EDGAR_SCHEDULER_ENABLED`.
- [x] Duplicate jobs for the same quarter are prevented via `lock_key`.
- [x] The quarterly pipeline check remains idempotent (doesn't trigger if already ingested).

## Scope
- `backend/app/services/scheduler.py`: Refactor to use the job system.
- `backend/app/services/thirteenf_admin_dashboard.py`: Add `quarterly_pipeline` to `_JOB_LOCK_BUILDERS` and `_execute_job`.
- `backend/app/services/thirteenf_job_worker.py`: (Optional) Verify it handles the new job type correctly.

## Test Plan
- Manual verification: Trigger a check via a script or by waiting for the cron, and verify a `JobRun` is created.
- Unit tests: Add a test in `backend/tests/unit/test_scheduler_alignment.py` to verify `trigger_job` is called with the correct parameters.
- Integration tests: Run the `quarterly_pipeline` job via a worker and verify it completes successfully.

## Files to change
- `backend/app/services/scheduler.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
