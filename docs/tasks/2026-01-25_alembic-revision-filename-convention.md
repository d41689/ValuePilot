# Task: Alembic revision filename convention + rename existing revisions

## Goal / Acceptance Criteria
- Document Alembic revision *filename* convention in `AGENTS.md`.
- Rename all files in `backend/alembic/versions/` to follow `YYYYMMDDHHMMSS-description.py`.
- Alembic can still load the revision graph after rename (no changes to `revision` / `down_revision` identifiers).

## Scope
### In
- `AGENTS.md` documentation update.
- Git rename of existing Alembic revision files in `backend/alembic/versions/`.
- Update any repo references to the old filenames (docs/scripts/tests).

### Out
- Any schema changes, migration content changes, or revision id changes.

## Files To Change
- `AGENTS.md`
- `backend/alembic/versions/*`
- Any docs referencing old migration filenames (as found by `rg`)

## Execution Plan
1. Add filename convention section to `AGENTS.md`.
2. Rename existing revision files using their `Create Date` timestamps.
3. Update references to old filenames across the repo.
4. Verify Alembic in Docker and run tests.

## Test Plan (Docker)
- `docker compose up -d --build`
- `docker compose exec api alembic history`
- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q`

## Verification Results
- 2026-01-25:
  - `docker compose exec api alembic history` ✅
  - `docker compose exec api alembic upgrade head` ✅
  - `docker compose exec api pytest -q` ✅ (88 passed)

## Notes / Decisions
- Alembic identifies revisions via `revision` / `down_revision` inside each file; filenames are not part of the graph identity, so renaming is safe as long as those identifiers do not change.
- Renamed existing revisions:
  - `08307bdf4ed3_initial_schema.py` -> `20260117034130-initial_schema.py`
  - `1a2b3c4d5e6f_metric_facts_period_type_text.py` -> `20260120120000-metric_facts_period_type_text.py`
  - `2b9f6b3d4c8a_metric_facts_value_json_nullable.py` -> `20260120201000-metric_facts_value_json_nullable.py`
