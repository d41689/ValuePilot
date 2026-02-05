# 2026-02-04 Reparse vs Screener Stale Data

## Goal / Acceptance Criteria
- Reparse of a document updates screener-visible metrics for the affected stock.
- Screener reflects the latest parsed metric_facts (is_current=true) after reparse.
- No schema changes.

## Scope
### In Scope
- Backend ingestion/reparse flow and screener query path.
- Fixing is_current semantics, refresh logic, or cache invalidation affecting screener.
- Add regression test.

### Out of Scope
- UI changes.
- New schema/migrations.

## Files To Change
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/tests/*`
- `docs/tasks/2026-02-04_reparse-screener-stale.md`

## Test Plan (Docker)
- `docker compose exec api pytest -q <targeted test>`
- `docker compose exec api pytest -q`

## Progress Update
- Added reparse fallback to re-extract PDF words when cached page text is used, without mutating stored page text unless missing.
- Added regression coverage for reparse fallback when cached text is empty.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec api pytest -q`

## Contract Checklist
- [x] No schema changes.
- [x] Reparse updates screener-visible facts.
- [x] Tests passing.
