# Task: Fix Docker Compose DB connectivity

## Goal / Acceptance Criteria
- `docker compose up -d --build --remove-orphans` starts a working PostgreSQL database, not a sleeping container.
- `api` can connect to the `db` service via Docker Compose networking.
- `web`, `api`, and `db` all start cleanly, and API health responds successfully.
- Database readiness is explicit so `api` waits for a healthy `db`.

## Scope
**In**
- Docker Compose service configuration only.
- Runtime verification via Docker Compose commands.

**Out**
- Application code changes unrelated to container startup.
- Schema or data model changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → Development / runtime environment is Docker-based.

## Files To Change
- `docker-compose.yml`
- `docs/tasks/2026-04-19_fix-docker-compose-db-connectivity.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Remove the `sleep infinity` override from `db` and restore real Postgres initialization variables.
2. Point `api` at the Compose service hostname `db`.
3. Add a DB healthcheck and gate `api` startup on DB health.
4. Rebuild and restart with Docker Compose, then verify DB readiness and API health.

## Contract Checks
- Verification is run through Docker Compose only.
- No host-native Python tooling.

## Rollback Strategy
- Revert `docker-compose.yml` to the previous service wiring and restart the stack.

## Notes / Results
- Investigation found the `db` container was `Up` but only running `sleep infinity`, so PostgreSQL never started.
- Investigation also found `api` was configured to connect to `postgres`, while the Compose service hostname available to the app was `db`.
- Updated `db` to use real Postgres initialization env vars (`POSTGRES_*`) and removed the `sleep infinity` override.
- Added a DB healthcheck and made `api` wait for `db` health before starting.
- Updated `api` `DATABASE_URL` to use `db` as the hostname.

## Verification Results
- `docker compose up -d --build --remove-orphans` → pass
- `docker compose ps` → `db` healthy, `api`/`web` up
- `docker compose exec db pg_isready -U valuepilot -d valuepilot` → accepting connections
- `docker compose exec api python -c "import psycopg2; ..."` → `db-connect-ok`
- `docker compose exec api python -c "import urllib.request; ..."` → `{"status":"ok"}`
