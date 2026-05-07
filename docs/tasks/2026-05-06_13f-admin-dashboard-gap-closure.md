# 13F Admin Dashboard Gap Closure

## Goal / Acceptance Criteria

- Close the highest-priority gaps between `13f_admin_data_operations_dashboard_product_plan.md` and the implemented 13F admin dashboard.
- Add explicit scheduler-disabled admin task coverage.
- Add setup checklist readiness payload and UI coverage.
- Add dry-run preview support for manual job actions before triggering mutations.
- Improve quarter health semantics for active ingestion and stale quarters.
- Expose unavailable reasons for zero-holdings ratio states.
- Add regression coverage for amendment supersession in product-facing 13F queries.

## Scope

In:
- Backend admin readiness/status/task payloads.
- Backend tests for the product contract gaps.
- Admin 13F frontend page and helper normalization where needed.
- Oracle's Lens / 13F query regression tests for latest-effective amendment handling.

Out:
- Email / Slack external alert delivery.
- Full CIK edit-search retry workflow.
- Quality warning acceptance workflow.
- Large navigation redesign.

## Files To Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `backend/tests/unit/test_oracles_lens.py`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- Frontend tests if available in the containerized frontend toolchain.

## Progress Notes

- 2026-05-06: Task created. Starting with tests for scheduler task, setup checklist, dry-run preview, quarter health, unavailable reason, and amendment supersession.
- 2026-05-06: Added backend contract coverage for scheduler-disabled P0 task, setup checklist payload, job dry-run preview, active quarter ingesting health, stale quarter health, no-holdings unavailable reason, and amendment supersession in Oracle's Lens.
- 2026-05-06: Implemented admin readiness setup checklist, scheduler-disabled blockers/tasks, dry-run preview metadata, active job and stale quarter state, linked-holding unavailable reason, frontend checklist/current-quarter display, dry-run confirmation preview, and active-lock button disabling.

## Verification Results

- PASS: `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py tests/unit/test_oracles_lens.py` -> 42 passed.
- PASS: `docker compose exec web node --test lib/thirteenfAdmin.test.js` -> 9 passed.
- PARTIAL: `docker compose exec web npm run build` compiled and completed lint/type checking, then failed during Next static prerender with `TypeError: Cannot read properties of null (reading 'useState')`. This error occurred during page prerendering after compilation; it appears to be a broader client-page prerender/runtime issue rather than a TypeScript error from this change.

## Contract Checklist

- `metric_facts` source-of-truth semantics are not changed.
- No raw SQL from user input was added.
- No `eval` / `exec` usage was added.
- 13F product-facing amendment behavior remains scoped to `Filing13F.is_latest_for_period`.
- No parser normalization or lineage contract was changed.
