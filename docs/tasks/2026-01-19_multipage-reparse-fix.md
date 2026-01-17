# Task: Multi-page Reparse Updates All Pages

## Goal / Acceptance Criteria
- Reparse on a multi-page container updates facts for every parsed page, not just the first.
- Screener results show current values for all pages (stocks) from the multi-page document.
- No schema migrations.
- `metric_extractions` remain immutable; new facts are inserted and prior parsed facts for the same (stock_id, metric_key, period_end_date) are deactivated.

## Scope
- In scope:
  - Diagnose multi-page reparse path.
  - Fix ingestion/reparse to iterate per page and resolve stock per page.
  - Update tests for multi-page reparse.
- Out of scope:
  - UI changes.
  - Schema changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/prd/value-pilot-prd-v0.1-multipage.md`
- `AGENTS.md`

## Files to change
- `backend/app/services/ingestion_service.py`
- `backend/app/api/v1/endpoints/documents.py` (if needed)
- `backend/tests/unit/test_reparse_existing_document.py`
- `backend/tests/unit/test_multipage_value_line_upload.py` (if needed)

## Plan
1. Add failing test for multi-page reparse updating all pages.
2. Fix reparse to handle multi-page per-page parsing and stock resolution.
3. Run Docker tests and update task log.

## Rollback Strategy
- Revert reparse changes and tests if the behavior cannot be corrected safely.

## Test Plan (Docker)
- `docker compose exec api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec api pytest -q`

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec -T api pytest -q`
