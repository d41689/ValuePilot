# 13F Quality Report Persistence

## Goal / Acceptance Criteria

- Persist 13F quality-check results so readiness and the admin dashboard do not depend only on logs or transient job summaries.
- Store latest quarter-level quality status, issue counts, checked timestamp, unavailable reasons, and issue details.
- Make `quality_check` jobs write durable reports.
- Surface quality reports in admin APIs and `/admin/13f`.
- Make quarter health and admin tasks use the latest persisted quality report.

## Scope

In:
- `quality_reports_13f` schema and model.
- Persistence helpers for `run_quality_checks`.
- Admin quality read APIs.
- Readiness / quarter summary integration.
- Admin UI quality reports section.
- Tests for persisted quality report creation, quality status in quarters, and quality warning task generation.

Out:
- Manual acceptance / dismissal workflow for warnings.
- Alert delivery.
- Per-metric quality override UI.

## Files to Change

- `backend/app/models/institutions.py`
- `backend/alembic/versions/*`
- `backend/app/services/edgar_quality.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/services/scheduler.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`

## Test Plan

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-06: Started after Manager / CIK audit workflow commit `4f0bf22`.
- 2026-05-06: Added durable `quality_reports_13f` schema, persistence helper, quality read APIs, quarter/task readiness integration, scheduler persistence, and admin dashboard quality report section.

## Verification

- `docker compose exec api alembic upgrade head` - passed.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` - 17 passed.
- `docker compose exec api pytest -q` - 228 passed.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` - 87 passed.
- `docker compose exec web npm run lint` - passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` - passed.
