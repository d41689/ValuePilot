# 13F Admin Data Operations Dashboard Implementation

## Goal / Acceptance Criteria

- Implement the 13F Admin Data Operations dashboard described in `docs/plans/13f_admin_data_operations_dashboard_product_plan.md`.
- Ship admin and consumer readiness APIs.
- Ship admin quarter/task/manager/job read APIs and safe job trigger contracts.
- Ship a read-only admin dashboard route at `/admin/13f`.
- Preserve 13F data correctness contracts, including latest-effective filing and amendment status semantics.

## Scope

In:
- Backend readiness service and endpoints.
- Durable job-run model and migration where needed.
- Admin API surfaces for status, readiness, quarters, tasks, managers, and jobs.
- Manual job trigger API with allowlisted job types, lock keys, dry-run support, and duplicate active-job prevention.
- Consumer-safe readiness payload.
- Oracle's Lens readiness integration where practical.
- Frontend admin dashboard using shared shadcn-style UI components.
- Tests for readiness, consumer-safe field exclusion, job lock keys, amendment status, and frontend helpers.

Out:
- Fully asynchronous worker infrastructure.
- SEC network fetching inside tests.
- Confirmed-CIK revocation workflow; documented as post-MVP 3 gap.
- Arbitrary shell command execution from UI.

## Files to Change

- `backend/app/models/institutions.py`
- `backend/alembic/versions/*`
- `backend/app/services/13f_admin/*` or equivalent service modules
- `backend/app/api/v1/endpoints/*`
- `backend/app/api/v1/api.py`
- `backend/tests/unit/*`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `frontend/lib/*`
- `frontend/components/layout/AppShell.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm test -- --runInBand` or available frontend test command
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-06: Started implementation from the approved product plan.
- 2026-05-06: Added `job_runs` model and migration for durable admin job history and lock keys.
- 2026-05-06: Added 13F admin readiness service covering phase/health, consumer-safe readiness, task queue, amendment status, historical depth, managers, and job runs.
- 2026-05-06: Added admin and consumer readiness endpoints plus admin quarter/task/manager/job endpoints.
- 2026-05-06: Added `/admin/13f` frontend dashboard with readiness, freshness, quarter health, tasks, manual controls, managers, and job history.
- 2026-05-06: Added admin nav entry visible only to admin users.
- 2026-05-06: Updated allowlisted manual job triggers to execute existing internal 13F functions synchronously and persist status / summary in `job_runs`.
- 2026-05-06: Connected Oracle's Lens to the consumer-safe 13F readiness endpoint and added persistent data freshness / setup-state messaging.
- 2026-05-06: Expanded `/admin/13f` manual controls to include backfill, CUSIP enrichment, stock bootstrap, EDGAR stock enrichment, accession retry, amendment reprocess, and manager confirm/reject actions.

## Verification

- `docker compose exec api alembic upgrade head` - passed.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` - 5 passed.
- `docker compose exec api pytest -q` - 216 passed.
- `docker compose exec web node --test lib/thirteenfAdmin.test.js` - 3 passed.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` - 85 passed.
- `docker compose exec web npm run lint` - passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` - passed.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` - 85 passed after Oracle's Lens readiness integration.
- `docker compose exec web npm run lint` - passed after Oracle's Lens readiness integration.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` - passed after Oracle's Lens readiness integration.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` - 85 passed after expanded admin controls.
- `docker compose exec web npm run lint` - passed after expanded admin controls.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` - passed after expanded admin controls.
