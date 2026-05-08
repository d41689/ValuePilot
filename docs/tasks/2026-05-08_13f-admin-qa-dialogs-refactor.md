# 13F Admin QA Dialogs Refactor

## Goal / Acceptance Criteria

Complete the next 13F Admin hardening batch:

- Add logout / switch-account QA support so an operator can clear the current session and return to login.
- Replace remaining `Confirm CIK` / `Reject CIK` `window.prompt` / `window.confirm` flows with explicit Dialogs.
- Begin decomposing `Admin13FPage` into focused child components without changing backend contracts.

## Scope

In:

- App shell sign-out control and session-clearing helper.
- 13F manager CIK confirm/reject dialogs.
- Focused extraction of low-risk 13F admin UI sections.
- Frontend helper tests and verification.

Out:

- Backend API, schema, and job contract changes.
- Full page redesign.
- Auth token refresh behavior.

## Files to Change

- `frontend/components/layout/AppShell.tsx`
- `frontend/middleware.ts`
- `frontend/lib/authRoutes.js`
- `frontend/lib/authRoutes.test.js`
- `frontend/lib/authSession.js`
- `frontend/lib/authSession.test.js`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-07_13f-admin-qa-dialogs-refactor.md`

## Execution Plan

1. Add tests for session-clearing helper and manager dialog defaults.
2. Implement `clearAuthSession` helper and use it from `AppShell` sign-out button.
3. Replace Confirm/Reject CIK prompt/confirm flows with Dialog state and shared UI controls.
4. Extract low-risk display components from `Admin13FPage`:
   - `MetricTile`
   - `SectionLabel`
   - `DrawerShell`
5. Run Docker verification:
   - `docker compose exec web node --test lib/authSession.test.js`
   - `docker compose exec web node --test lib/thirteenfAdmin.test.js`
   - `docker compose exec web node --test lib`
   - `docker compose exec web npm run lint`
   - `docker compose exec web npm run build`
6. Browser smoke-check logout and manager dialogs without mutating production-like data.

## Rollback Strategy

Revert this task's frontend changes. No backend or migration changes are included.

## Contract Checks

- No raw SQL or backend data contract changes.
- 13F job payloads unchanged.
- Manager CIK confirm/reject endpoints unchanged.
- Auth session clearing only removes `vp_access_token`, `vp_refresh_token`, and `vp_role`.

## Progress Notes

- 2026-05-07: Created after final 13F Admin UX hardening review.
- 2026-05-07: Implemented shared auth session clearing, AppShell sign-out, protected `/admin/*` middleware coverage, Confirm/Reject CIK dialogs, and low-risk `Admin13FPage` display component extraction.
- 2026-05-07: Browser QA found `next build` can leave the dev server with stale `.next` chunks; restarted `web` before final browser verification.

## Verification

- `docker compose exec web node --test lib/authRoutes.test.js lib/authSession.test.js lib/thirteenfAdmin.test.js` — PASS
- `docker compose exec web node --test lib` — PASS (102 tests)
- `docker compose exec web npm run lint` — PASS
- `docker compose exec web npm run build` — PASS
- Browser smoke on `http://localhost:3001/admin/13f` — PASS:
  - Sign out clears session and lands on `/login`.
  - Direct `/admin/13f` after logout redirects to `/login`.
  - Re-login with admin account returns to the 13F Admin page.
  - Amendment detail drawer opens and closes with the shared `DrawerShell`.
  - Confirm/Reject CIK dialogs were covered by helper/unit tests; current local data has no pending CIK review rows to trigger them without seeding data.
