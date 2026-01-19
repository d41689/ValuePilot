# Task: Remove FastAPI example deprecation warning

## Goal / Acceptance Criteria
- `docker compose exec -T api pytest -q` runs without the FastAPI `example` deprecation warning.

## Scope
### In Scope
- Update FastAPI schema usage to replace deprecated `example` with `examples`.
- Update related tests if necessary.

### Out of Scope
- API behavior changes.
- Schema migrations.
- UI changes.

## PRD References
- N/A (tooling/deprecation cleanup)

## Files To Change
- `backend/app/api/v1/api.py`
- `backend/app/api/v1/endpoints/*.py`
- `docs/tasks/2026-01-18_fastapi-example-warning.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q`

## Execution Plan (Approved)
1. Locate deprecated `example` usage in FastAPI schemas.
2. Replace with `examples` per FastAPI docs.
3. Run tests to confirm warning removed.
4. Record verification results.

## Rollback Strategy
- Revert schema changes and re-run tests.

## Verification
- `docker compose exec -T api pytest -q`
