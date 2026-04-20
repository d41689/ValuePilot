# Task: Upgrade PostgreSQL Docker image to latest stable

## Goal / Acceptance Criteria
- Docker Compose uses the latest stable PostgreSQL release available at implementation time.
- The `db` service starts successfully on the upgraded version.
- The application can connect to the upgraded database.
- Schema migrations apply cleanly after the upgrade.

## Scope
**In**
- Docker Compose Postgres image version update.
- Safe handling of the old Postgres 15 data directory before starting PostgreSQL 18.
- Docker verification and migration application.

**Out**
- Application schema changes.
- Data backfill/import work beyond preserving a backup of the old PG15 data directory.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → Docker-based development/runtime environment.

## Files To Change
- `docker-compose.yml`
- `docs/tasks/2026-04-19_upgrade-postgres-to-18-3.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Pin the `db` image to the latest stable PostgreSQL release.
2. Back up the current host-mounted PG15 data directory before starting PG18.
3. Recreate the stack with the new image.
4. Re-run Alembic migrations and verify DB/API connectivity.

## Contract Checks
- Verification stays inside Docker Compose.
- Existing PG15 data directory is preserved as a host backup rather than deleted.

## Rollback Strategy
- Point `docker-compose.yml` back to PostgreSQL 15 and restore the backed-up PG15 data directory.

## Notes / Results
- Investigation: the current runtime is PostgreSQL `15.17`.
- Official PostgreSQL release page shows `18.3` as the latest major stable release, alongside `17.9`, `16.13`, and `15.17` on 2026-02-26.
- Updated the Docker image to `postgres:18.3`.
- Backed up the previous PG15 host data directory to `/tmp/valuepilot-postgres15-backup-20260419` before starting PG18.
- Adjusted the host mount layout to match PostgreSQL 18 Docker image expectations:
  - host: `./storage/postgres`
  - container: `/var/lib/postgresql`
- Reinitialized the PG18 data directory and re-applied Alembic migrations.

## Verification Results
- `docker compose exec db psql -U valuepilot -d valuepilot -c "SELECT version();"` → `PostgreSQL 18.3`
- `docker compose exec api alembic upgrade head` → pass
- `docker compose exec api python -c "import urllib.request; ..."` → `{"status":"ok"}`
- `docker compose ps` → `db` healthy; `api`/`web` up
- Host data directory layout now uses PostgreSQL 18 versioned storage:
  - `storage/postgres/18/docker/...`
