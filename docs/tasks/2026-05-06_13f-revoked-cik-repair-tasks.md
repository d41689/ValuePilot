# 13F Revoked CIK Repair Tasks

## Goal / Acceptance Criteria

- When a confirmed manager CIK is revoked and prior filings are affected, the admin task queue must show a clear downstream repair task.
- The task should name the affected manager, old CIK, affected filing count, affected quarters, and next step: reconfirm the correct CIK, then reprocess affected quarters.
- Reconfirming the manager should remove the repair task because the manager is no longer in `match_status='revoked'`.

## Scope

In:
- Admin task generation from `institution_manager_cik_review_events`.
- Task metadata for affected manager / quarters.
- Frontend task cards display metadata when present.

Out:
- Automatic filing reassignment, deletion, or reingestion.
- New downstream repair job type.
- Bulk repair automation.

## Files to Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-06_13f-revoked-cik-repair-tasks.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-06: Started after CIK revocation audit workflow. This task intentionally surfaces human repair guidance; it does not mutate downstream holdings.
- 2026-05-06: Added P1 `REVOKED_CIK_DOWNSTREAM_REVIEW` tasks for managers still in `match_status='revoked'` with a revocation event requiring downstream review.
- 2026-05-06: Task metadata now includes manager id/name, old CIK, affected filing count, affected quarters, and review event id.
- 2026-05-06: Admin task cards show metadata so the affected scope is visible without opening the Managers table.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 24 tests.
- `docker compose exec api pytest -q` passed: 235 tests.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` passed: 89 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- Existing filings, holdings, and raw documents are not mutated by repair task generation.
- The task is advisory and only appears while the manager remains revoked.
- No raw SQL from user input was added.
- No formula or screener behavior was touched.
- Admin task metadata preserves downstream audit context without exposing a destructive repair button.
