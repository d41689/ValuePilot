# 13F Admin Async Jobs And Worker Heartbeat

## Goal / Acceptance Criteria

- Convert 13F admin manual job triggers from synchronous execution to queued asynchronous execution.
- Add durable worker heartbeat visibility so admins can tell whether a 13F job worker is alive, idle, running, or stale.
- Add job detail API and UI drilldown for job input, summary, errors, timing, lock key, and worker ownership.
- Preserve duplicate active-job lock behavior.
- Keep job execution constrained to allowlisted internal job types only.

## Scope

In:
- Job heartbeat schema / migration.
- DB-backed 13F job worker integrated with existing Docker/API runtime.
- Admin API endpoints for job detail and worker heartbeat.
- Frontend job detail panel and worker heartbeat card.
- Tests for queued trigger, worker execution, duplicate locks, job detail, and stale heartbeat reporting.

Out:
- Redis/Celery/RQ adoption.
- Distributed multi-worker scheduling guarantees beyond database row claiming.
- Arbitrary command execution.
- Alerts/notifications.

## Files to Change

- `backend/app/models/institutions.py`
- `backend/alembic/versions/*`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/services/thirteenf_job_worker.py`
- `backend/app/main.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`

## Test Plan

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-06: Started from the committed V1 admin dashboard implementation.
- 2026-05-06: Added durable `job_worker_heartbeats` schema, async queued job semantics, DB-backed worker execution, job detail endpoint, worker heartbeat endpoint, and `/admin/13f` worker/job detail UI.
- 2026-05-06: Fixed queued job cancellation so canceled jobs release the active lock key.

## Verification

- `docker compose exec api alembic upgrade head` - passed.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` - 10 passed.
- `docker compose exec api pytest -q` - 221 passed.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` - 86 passed.
- `docker compose exec web npm run lint` - passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` - passed.
- `docker compose up -d --build` - attempted to activate the new worker env in the local running services, but Docker socket escalation was blocked by the environment approval layer.
