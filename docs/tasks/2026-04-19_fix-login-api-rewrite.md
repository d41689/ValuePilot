# Task: Fix login API rewrite path

## Goal / Acceptance Criteria
- Frontend login requests to `/api/v1/auth/login` must proxy to the backend route `/api/v1/auth/login` instead of dropping the `/api` prefix.
- Login requests from the web app must no longer return a frontend 404 caused by an incorrect Next.js rewrite target.
- Docker-based verification must confirm the proxied login route reaches the backend.

## Scope
**In**
- Next.js rewrite configuration.
- Docker-based verification of the proxied login endpoint.

**Out**
- Backend auth logic changes.
- User/password changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → Docker-based development/runtime environment.

## Files To Change
- `frontend/next.config.js`
- `docs/tasks/2026-04-19_fix-login-api-rewrite.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Update the Next.js rewrite so `/api/:path*` proxies to backend `/api/:path*`.
2. Restart the `web` service so Next reloads its config.
3. Verify the login endpoint through the frontend origin.

## Contract Checks
- Frontend remains Docker-hosted.
- No backend route or auth contract changes.

## Rollback Strategy
- Revert the rewrite destination and restart `web`.

## Notes / Results
- Investigation found `frontend/lib/api/client.ts` posts to `/api/v1/auth/login`.
- `frontend/next.config.js` rewrote `/api/:path*` to `http://api:8000/:path*`, which transformed `/api/v1/auth/login` into backend `/v1/auth/login` and caused the observed 404.
- Updated the rewrite destination to `http://api:8000/api/:path*` so the backend keeps the `/api` prefix.
- Restarted the `web` service so Next.js reloaded its config.

## Verification Results
- `docker compose restart web` → pass
- `docker compose exec web node -e "fetch('http://localhost:3000/api/v1/auth/login', ...)"` → `422` with backend validation error for missing `email` / `password`
  - This confirms the request now reaches backend `/api/v1/auth/login` instead of failing with a frontend `404`.
- `docker compose exec api python -c "import urllib.request; ..."` → `{"status":"ok"}`
