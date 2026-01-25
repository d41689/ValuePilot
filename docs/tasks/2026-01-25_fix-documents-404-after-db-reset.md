# Task: Fix `/documents` 404 after DB reset

## Goal / Acceptance Criteria
- After `alembic downgrade base` + `alembic upgrade head`, `GET /api/v1/documents?user_id=1` returns `200` (not `404 User not found`) in the default Docker Compose dev setup.
- Fix is deterministic and safe (no schema changes).
- All tests pass in Docker.

## Scope
### In
- Add dev-friendly default user seeding so the app is usable immediately after a DB reset.
- Keep existing API semantics for non-dev environments unless explicitly enabled.

### Out
- Authentication/authorization redesign.
- New schema or PRD changes.

## Files To Change
- `backend/app/core/config.py`
- `backend/app/api/v1/endpoints/documents.py`
- `docker-compose.yml`
- `backend/tests/unit/` (add regression test)

## Test Plan (Docker)
- `docker compose exec api alembic downgrade base`
- `docker compose exec api alembic upgrade head`
- `curl -i 'http://localhost:8001/api/v1/documents?user_id=1'`
- `docker compose exec api pytest -q`

## Notes
- Current 404 response is `{"detail":"User not found"}` which indicates the DB is empty of users after reset; the frontend appears to assume `user_id=1`.

## Implementation Notes
- Added an explicit dev bootstrap path: when `DEFAULT_USER_EMAIL` is set and `user_id==DEFAULT_USER_ID` is requested, the documents endpoints will auto-create that user if missing.
- This keeps existing behavior unchanged unless the env var is set.

## Verification Results
- 2026-01-25:
  - `docker compose exec api alembic downgrade base` ✅
  - `docker compose exec api alembic upgrade head` ✅
  - `curl -i 'http://localhost:8001/api/v1/documents?user_id=1'` ✅ (200, `[]`)
  - `docker compose exec api pytest -q` ✅ (89 passed)
