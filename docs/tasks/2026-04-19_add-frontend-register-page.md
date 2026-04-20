# Task: Add frontend registration page

## Goal / Acceptance Criteria
- Frontend exposes a `/register` page alongside `/login`.
- `/register` submits to the existing backend `POST /api/v1/auth/register` endpoint.
- Successful registration routes the user to `/login` so they can sign in.
- The auth middleware treats `/register` as a public auth page and redirects authenticated users to `/home`.
- Login and register pages link to each other.

## Scope
**In**
- Frontend auth routing and page UI.
- Frontend middleware update for the new public auth route.
- Lightweight frontend unit test for auth public-path behavior.

**Out**
- Backend auth contract changes.
- Email verification or password reset flows.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → Docker-based runtime / UI semantics.

## Files To Change
- `frontend/middleware.ts`
- `frontend/lib/authRoutes.js` (new)
- `frontend/lib/authRoutes.test.js` (new)
- `frontend/app/(auth)/login/page.tsx`
- `frontend/app/(auth)/register/page.tsx` (new)
- `docs/tasks/2026-04-19_add-frontend-register-page.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Add a small auth-route helper and unit test covering public auth paths.
2. Update middleware to recognize `/register`.
3. Add the frontend registration page and cross-links between login/register.
4. Verify in Docker:
   - `docker compose exec web node --test lib/authRoutes.test.js`
   - `docker compose exec web npm run lint`

## Contract Checks
- Frontend uses the existing backend `POST /api/v1/auth/register` route without changing the API contract.
- No backend auth changes.

## Rollback Strategy
- Remove the `/register` page, helper, and middleware update.

## Notes / Results
- Investigation confirmed the backend already exposes `POST /api/v1/auth/register`, but the frontend currently only provides `/login`.
- Added `frontend/lib/authRoutes.js` plus a small unit test so `/login` and `/register` are treated consistently as public auth routes.
- Updated `frontend/middleware.ts` to allow `/register` and redirect authenticated users from both auth pages to `/home`.
- Added `frontend/app/(auth)/register/page.tsx` wired to `POST /api/v1/auth/register`.
- Updated the login page to:
  - link to `/register`
  - show a success banner when redirected back after registration
- Updated the register page to link back to `/login`.

## Verification Results
- `docker compose exec web node --test lib/authRoutes.test.js` → pass
- `docker compose exec web npm run lint` → pass with pre-existing warnings in `frontend/app/(dashboard)/watchlist/page.tsx` only; no new auth-page warnings introduced
