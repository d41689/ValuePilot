# 13F Admin Unknown Health Followup

## Goal / Acceptance Criteria

Address review findings for commit `50f59f0`:

- `operationsHealth` must not hide P1 tasks or warning-level setup items when worker heartbeat state is indeterminate.
- The page banner should render `unknown` operations health with neutral styling, matching the badge tone.

## Scope

In:

- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`

Out:

- Backend API contracts
- Worker heartbeat data model

## Test Plan

- `docker compose exec web node --test lib/thirteenfAdmin.test.js`
- `docker compose exec web node --test lib`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`

## Progress Notes

- 2026-05-07: Created from review of commit `50f59f0`.
- 2026-05-07: Added red tests for P1 tasks and warning setup items under `workersIndeterminate`.
- 2026-05-07: Fixed `operationsHealth` so unknown worker state is neutral only when there are no known tasks/setup warnings, and added a neutral `unknown` banner branch in the page.

## Verification

- `docker compose exec web node --test lib/thirteenfAdmin.test.js` passed.
- `docker compose exec web node --test lib` passed.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web npm run build` passed.
