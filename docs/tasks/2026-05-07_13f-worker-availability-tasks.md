# 13F Worker Availability Tasks

## Goal / Acceptance Criteria

- Promote worker unavailable and stuck queued job conditions into Admin Tasks.
- If queued jobs exist but no active worker heartbeat is present, show a P1 task with queued job count and oldest queued job metadata.
- If an active worker exists but a queued job has been waiting too long, show a P2 stuck queued job task.
- Do not create worker availability tasks when there are no queued jobs.

## Scope

In:
- Backend task generation from `job_runs` and `job_worker_heartbeats`.
- Tests for unavailable worker and stuck queued job conditions.
- Frontend task metadata rendering for queued jobs and worker state.

Out:
- Worker restart automation.
- Deployment orchestration.
- Email/Slack alerts.

## Files to Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-07_13f-worker-availability-tasks.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-07: Started after failed job admin alerts. This task should only surface operational diagnostics and should not attempt to restart workers.
- 2026-05-07: Added `JOB_WORKER_UNAVAILABLE` P1 task when queued jobs exist without an active worker heartbeat.
- 2026-05-07: Added `STUCK_QUEUED_JOB` P2 task when an active worker exists but the oldest queued job has waited longer than the configured threshold.
- 2026-05-07: Admin task cards now show queued job count, oldest queued job, queue age, and active/seen worker counts.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 30 tests.
- `docker compose exec api pytest -q` passed: 241 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- Worker availability tasks are diagnostics only; no worker restart or deployment action is automated.
- Tasks appear only when queued jobs exist.
- No raw logs, shell commands, ingestion semantics, holdings data, parser behavior, screeners, or formulas were changed.
