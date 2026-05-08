# 13F Quarter Drilldown

## Goal / Acceptance Criteria

- Add an admin quarter drilldown so an operator can open a quarter from `/admin/13f` and see why it is partial, failed, or needs review.
- The detail payload must include quarter summary, filing rows, pending filing accessions, failed filing accessions, amendment rows, latest quality report, and suggested safe actions.
- The frontend should expose a Review action in the Quarters table and display the detail in a side panel without requiring navigation away from the operations dashboard.

## Scope

In:
- Backend quarter detail service and admin API endpoint.
- Focused tests for pending, failed, amendment, quality, and action payloads.
- Frontend query and side panel.

Out:
- New ingestion semantics or repair automation.
- New schema.
- Non-admin consumer exposure.

## Files to Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-07_13f-quarter-drilldown.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-07: Started after revoked CIK downstream repair tasks. The drilldown is read-only except for reusing existing manual job controls.
- 2026-05-07: Added `GET /api/v1/admin/13f/quarters/{quarter}/detail` with summary, filings, pending/failed slices, amendments, latest quality report, and suggested actions.
- 2026-05-07: Added Quarters table `Review` action and a side panel showing operational detail plus buttons for safe existing jobs.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 25 tests.
- `docker compose exec api pytest -q` passed: 236 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- Drilldown is admin-only and read-only except for existing job triggers.
- No filings, holdings, raw documents, or manager identity records are mutated by the detail endpoint.
- No raw SQL from user input was added.
- No screener, formula, parser, or metric normalization behavior was touched.
- Suggested actions reuse allowlisted job types only.
