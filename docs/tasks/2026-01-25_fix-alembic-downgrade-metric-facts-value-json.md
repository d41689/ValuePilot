# Task: Fix Alembic downgrade for `metric_facts.value_json`

## Goal / Acceptance Criteria
- `alembic downgrade base` succeeds even if `metric_facts.value_json` currently contains `NULL`s.
- Fix is implemented in the relevant migration downgrade step (no schema redesign).
- Verification is run inside Docker.

## Scope
### In
- Patch the `downgrade()` for the revision that reintroduces `NOT NULL` on `metric_facts.value_json` to first backfill existing `NULL`s.

### Out
- Changing DB schema beyond what is needed for a safe downgrade.
- Data migrations outside of this column.

## Files To Change
- `backend/alembic/versions/2b9f6b3d4c8a_metric_facts_value_json_nullable.py`
- `docs/tasks/2026-01-25_fix-alembic-downgrade-metric-facts-value-json.md`

## Test Plan (Docker)
- `docker compose up -d db`
- `docker compose run --rm api alembic upgrade head`
- Insert or update at least one `metric_facts` row to have `value_json = NULL`
- `docker compose run --rm api alembic downgrade base`

## Progress Log
- 2026-01-25: Task created.
- 2026-01-25: Patched `downgrade()` to backfill `metric_facts.value_json` NULLs with `{}` before restoring `NOT NULL`.
- 2026-01-25: Reproduced in Docker: inserted a `metric_facts` row with `value_json = NULL`, then `alembic downgrade 1a2b3c4d5e6f` succeeded and the row was backfilled to `{}`.
- 2026-01-25: Verified in Docker: `alembic downgrade base` succeeded; re-upgraded to head; `pytest -q` passed (88).
