# Task: Fix prod frontend standalone startup

## Goal / Acceptance Criteria
- ValuePilot prod frontend starts without the Next.js warning about using `next start` with `output: standalone`.
- The prod frontend continues to serve pages on the existing host port mapping.
- Frontend `/api/v1/*` requests continue to proxy to the prod API correctly after the startup change.

## Scope
**In**
- Production Docker Compose startup command for the `web` service.
- Docker-based verification of prod frontend startup and proxy behavior.

**Out**
- Frontend feature changes.
- Backend/API contract changes.
- Dockerfile refactors beyond what is needed for the standalone startup fix.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Docker-based runtime / deployment expectations

## Files To Change
- `docker-compose.prod.yml`
- `docs/tasks/2026-04-20_fix-prod-frontend-standalone-start.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Confirm the prod web service currently uses `next start` despite `output: standalone`.
2. Update the prod web command to build and then launch `node .next/standalone/server.js` with the same host/port.
3. Rebuild and restart the prod stack with Docker Compose.
4. Verify:
   - web logs no longer contain the standalone warning
   - the frontend still responds on `localhost:3101`
   - the frontend still proxies `/api/v1/auth/login` to the prod API

## Contract Checks
- Verification is run through Docker Compose only.
- No schema, parser, screener, formula, or lineage behavior changes.
- No raw SQL or eval/exec changes are introduced.

## Rollback Strategy
- Restore the previous `web` service command in `docker-compose.prod.yml`.
- Rebuild and restart the prod stack.

## Progress Log
- [x] Inspect current prod frontend startup path.
- [x] Update prod web startup to Next standalone server.
- [x] Rebuild and verify in Docker.

## Notes / Decisions / Gotchas
- Current `docker-compose.prod.yml` runs:
  - `npm run build && npm run start -- --hostname 0.0.0.0 --port 3000`
- `frontend/next.config.js` already sets `output: 'standalone'`, so the recommended prod launch target is `.next/standalone/server.js`.
- Updated the prod `web` command to:
  - `npm run build && HOSTNAME=0.0.0.0 PORT=3000 node .next/standalone/server.js`
- This keeps the existing host port mapping and same-origin `/api/v1` proxy behavior unchanged.
- Pre-existing frontend lint warnings in `frontend/app/(dashboard)/watchlist/page.tsx` still appear during build, but the standalone startup warning is gone.

## Verification Results
- `docker compose -f docker-compose.prod.yml config` -> pass
- `docker compose -f docker-compose.prod.yml up -d --build web` -> pass
- `docker compose -f docker-compose.prod.yml logs --tail=120 web` -> no `next start` / standalone warning; startup reaches `✓ Ready`
- `curl -I http://localhost:3101` -> `307 Temporary Redirect` to `/home`
- `curl -sS http://localhost:8101/health` -> `{"status":"ok"}`
- `curl -d '{}' https://invest.richmom.vip/api/v1/auth/login` -> `422` with missing `email` / `password`, confirming the frontend still proxies to the prod API after the startup change
