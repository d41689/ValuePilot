# 13F Failed Job Admin Alerts

## Goal / Acceptance Criteria

- Promote recent failed or partial-success 13F admin jobs into the Admin Tasks queue.
- Task payload should identify job id, job type, status, quarter/accession, failed accession count, and retry target hints.
- Succeeded/canceled jobs should not create alert tasks.
- The frontend task card should display job metadata without requiring the admin to open Job Runs first.

## Scope

In:
- Backend task generation from recent `job_runs`.
- Tests for failed and partial-success tasks.
- Frontend task metadata rendering for job details.

Out:
- Email/Slack notifications.
- New alert table.
- Raw log access.

## Files to Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-07_13f-failed-job-admin-alerts.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-07: Started after job detail timeline. This is intentionally in-app only for V1.
- 2026-05-07: Added Admin Tasks for recent `failed` and `partial_success` job runs.
- 2026-05-07: Job alert metadata includes job id/type/status, quarter/accession, failed accession count, retry targets, error message, and finished time.
- 2026-05-07: Admin task cards render job metadata so operators can see failed job context before opening Job Runs.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 28 tests.
- `docker compose exec api pytest -q` passed: 239 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- Alerts are derived from persisted `job_runs`; no new raw log access was added.
- Retry targets use existing allowlisted job types.
- No ingestion, holdings, manager identity, parser, screener, or formula semantics changed.
- Consumer readiness payload remains unchanged.
