# Task: Fix prod compose to use shared infra database

## Goal / Acceptance Criteria
- `docker-compose.prod.yml` does not start its own local PostgreSQL container.
- The prod `api` service connects to the shared PostgreSQL service provided by `../infra/`.
- Default prod DB connection values align with `../infra/.env.example` and target `valuepilot_prod`.
- The prod stack can start successfully once the shared infra stack is up.

## Scope
**In**
- `docker-compose.prod.yml` only.
- Docker verification against `../infra/docker-compose.yml`.

**Out**
- Application code changes.
- Shared infra repo changes.
- Data migrations beyond normal app startup `alembic upgrade head`.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → Docker-based development/runtime environment.

## Files To Change
- `docker-compose.prod.yml`
- `docs/tasks/2026-04-20_fix-prod-compose-shared-infra-db.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Remove the local `db` service from prod compose.
2. Point `api` at shared-infra `postgres` using ValuePilot prod defaults.
3. Validate compose config.
4. Start `../infra` and then the prod stack to verify startup and DB connectivity.

## Contract Checks
- Verification is run through Docker Compose only.
- Prod API targets the shared `projects-shared` network database.

## Rollback Strategy
- Restore the old prod compose `db` service and API DB URL.

## Notes / Results
- Investigation found `docker-compose.prod.yml` still defined a fake local `db` container using `sleep infinity`.
- Investigation found `../infra/docker-compose.yml` exposes PostgreSQL on the shared network under hostname `postgres`, and `../infra/.env.example` defines `VALUEPILOT_DB_USER=valuepilot`, `VALUEPILOT_DB_PASSWORD=valuepilot`, `VALUEPILOT_PROD_DB=valuepilot_prod`.
- Removed the local prod `db` service entirely.
- Updated prod `api` to connect to shared infra `postgres` using `VALUEPILOT_DB_USER`, `VALUEPILOT_DB_PASSWORD`, and `VALUEPILOT_PROD_DB` defaults aligned with `../infra/.env.example`.
- Verified the prod API connects to `valuepilot_prod` on the shared infra PostgreSQL instance.
- Fixed two production-only frontend build blockers discovered during verification:
  - `frontend/middleware.ts` `config.matcher` now uses explicit strings instead of a spread expression.
  - `frontend/app/(auth)/login/page.tsx` no longer uses `useSearchParams()`, avoiding the production suspense/prerender requirement.

## Verification Results
- `docker compose -f docker-compose.prod.yml config` → pass
- `docker compose -f ../infra/docker-compose.yml up -d` → pass
- `docker compose -f docker-compose.prod.yml up -d --build` → pass
- `docker compose -f docker-compose.prod.yml exec api python -c "from sqlalchemy import text; ..."` → `[('valuepilot_prod', 'valuepilot')]`
- `docker compose -f docker-compose.prod.yml exec api python -c "import urllib.request; ..."` → `{"status":"ok"}`
- `docker compose -f docker-compose.prod.yml logs web` → production `next build` completes and `next start` reaches `Ready`
- `docker compose -f docker-compose.prod.yml exec web node -e "fetch('http://localhost:3000/api/v1/auth/login', ...)"` → `422` backend validation response, confirming the prod frontend proxies requests to the prod API successfully
