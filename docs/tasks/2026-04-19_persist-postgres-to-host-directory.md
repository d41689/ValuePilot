# Task: Persist PostgreSQL data to host directory

## Goal / Acceptance Criteria
- PostgreSQL data in Docker Compose persists under a host directory in the repository workspace.
- Recreating the `db` container does not discard database files because `/var/lib/postgresql/data` is bind-mounted to the host.
- The host data directory is ignored by git.

## Scope
**In**
- Docker Compose DB volume configuration.
- Git ignore rules for local Postgres data.
- Docker verification that the bind mount is active.

**Out**
- Schema or migration changes.
- Application code changes unrelated to runtime persistence.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → Docker-based development/runtime environment.

## Files To Change
- `docker-compose.yml`
- `.gitignore`
- `docs/tasks/2026-04-19_persist-postgres-to-host-directory.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Bind-mount the Postgres data directory to a host path under the repo.
2. Ignore that host data path in git.
3. Recreate the `db` container and verify the mount is active.

## Contract Checks
- Runtime commands stay inside Docker Compose.
- No host-native DB tooling required.

## Rollback Strategy
- Remove the bind mount, recreate `db`, and fall back to container-only storage.

## Notes / Results
- Current Compose config starts Postgres correctly but does not persist `/var/lib/postgresql/data` to a host directory, so deleting the container would lose DB data.
- Added a bind mount from `./storage/postgres` to `/var/lib/postgresql/data`.
- Added `storage/postgres/` to `.gitignore` so local DB files stay out of version control.

## Verification Results
- `docker compose up -d --build --remove-orphans` → pass
- `docker compose ps` → `db` healthy; `api` and `web` up
- `docker compose exec db pg_isready -U valuepilot -d valuepilot` → accepting connections
- `docker compose exec db ls -la /var/lib/postgresql/data` → Postgres data files present
- `ls -la storage/postgres` → same data files present on host path
