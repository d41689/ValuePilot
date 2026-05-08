# 13F Admin QA Fixtures and Component Split

## Goal / Acceptance Criteria

Continue the 13F Admin hardening work with the next three items:

- Verify non-admin route behavior for `/admin/13f` and document the QA path.
- Add a deterministic pending CIK fixture or seed path so Confirm/Reject dialogs can be exercised without relying on incidental local data.
- Split more of `Admin13FPage` into focused components while preserving behavior and UI contracts.

## Scope

In:

- Frontend route/auth helper coverage for non-admin access expectations.
- Backend or script-level fixture/seed support for a pending manager CIK review row.
- Low-risk frontend component extraction around repeated 13F Admin sections.
- Docker-based verification and task log updates.

Out:

- Backend schema changes.
- Changes to 13F job payload contracts.
- Redesigning the dashboard layout.
- Exposing admin operations to non-admin users.

## Files to Change

- `frontend/lib/authRoutes.js`
- `frontend/lib/authRoutes.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `frontend/components/admin13f/Admin13FPrimitives.tsx`
- `frontend/components/admin13f/ManagerCikDialogs.tsx`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/middleware.ts`
- `backend/app/services/edgar_ingestion.py`
- `backend/app/cli/edgar.py`
- `backend/app/services/seed_data/pending_cik_review_fixture.json`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `docs/tasks/2026-05-08_13f-admin-qa-fixtures-component-split.md`

## Execution Plan

1. Inspect existing auth tests, backend seed scripts, and 13F admin page boundaries.
2. Add or extend tests first:
   - non-admin/admin route classification;
   - pending CIK seed/fixture behavior;
   - any extracted presentation helper behavior if logic is introduced.
3. Implement the pending CIK fixture/seed path with idempotent behavior.
4. Extract focused `Admin13FPage` components around stable sections and repeated item rendering.
5. Run Docker verification:
   - frontend JS tests;
   - relevant backend pytest for seed/fixture support;
   - frontend lint/build.
6. Browser QA non-admin/admin route behavior where practical, and record gaps.

## Rollback Strategy

Revert this task's frontend and seed/fixture changes. No migration or schema changes are planned.

## Contract Checks

- Admin-only route remains protected by middleware and API auth.
- Pending CIK fixture must not auto-confirm a manager.
- Confirm/Reject API payload contracts remain unchanged.
- No raw SQL, eval, or parser/data lineage changes.

## Progress Notes

- 2026-05-08: Created task log before implementation.
- 2026-05-08: Added `resolveAuthRedirect` so middleware and tests share the non-admin `/admin` redirect contract.
- 2026-05-08: Added an idempotent pending CIK fixture seed command. The fixture creates `QA_PENDING_CIK` as `match_status="candidate"` with no confirmed `cik`.
- 2026-05-08: Extracted reusable drawer/metric primitives and CIK review dialogs out of `Admin13FPage`.
- 2026-05-08: Browser QA showed the fixture was seeded but not visible because the managers table only renders the first 12 rows. Added `prioritizeManagersForReview` to surface actionable CIK review rows first.

## Verification

- `docker compose exec web node --test lib/thirteenfAdmin.test.js` passed after the red test for manager prioritization.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 41 tests.
- `docker compose exec web node --test lib` passed: 104 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web npm run build` passed.
- Browser QA:
  - Admin `/admin/13f` renders and shows `QA Pending CIK Manager` in the Managers section.
  - Confirm dialog opens for the pending fixture and was canceled without mutating the fixture.
  - Non-admin `qa-nonadmin@example.com` login redirects direct `/admin/13f` navigation to `/home`; admin page content does not render.
  - Browser session was restored to `d41689@gmail.com` on `/admin/13f`.

## Contract Gate

- Screeners, parser normalization, and formula paths were not changed.
- Pending CIK fixture does not auto-confirm a CIK or expand the ingestion whitelist.
- Confirm/Reject/Revoke payload contracts are unchanged.
- Admin route remains protected by middleware and API auth; non-admin users are redirected to `/home`.
- No schema changes, raw SQL, eval, or parser lineage changes.
