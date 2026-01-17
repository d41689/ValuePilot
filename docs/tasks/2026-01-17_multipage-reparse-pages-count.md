# Task: Fix multi-page reparse + show parsed page counts

## Goal / Acceptance Criteria
- Multi-page reparse parses every Value Line page and sets `parse_status=parsed` when all pages succeed.
- `/documents` list shows total pages and parsed page count in the Pages column.
- Parsed page count reflects pages with successful parsing output.

## Scope
### In Scope
- Adjust ValueLine identity extraction / reparse flow to avoid false failures on multi-page documents.
- Expose `parsed_page_count` in the documents list API.
- Update `/documents` UI to display `parsed_page_count / page_count`.
- Add tests for reparse multi-page success and documents list counts.

### Out of Scope
- Schema migrations.
- Changes to non-documents screens beyond the pages column display.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` (data lineage, document artifacts)
- `docs/prd/value-pilot-prd-v0.1-multipage.md` (multi-page container semantics, parse_status)

## Files To Change
- `backend/app/services/ingestion_service.py`
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_reparse_existing_document.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/app/(dashboard)/documents/page.tsx`
- `docs/tasks/2026-01-17_multipage-reparse-pages-count.md`

## Test Plan (Docker)
- `docker compose exec api pytest -q backend/tests/unit/test_reparse_existing_document.py`
- `docker compose exec api pytest -q backend/tests/unit/test_documents_api.py`
- `docker compose exec api pytest -q`

## Progress
- Added parser identity test to cover deeper headers and colon exchange format.
- Added parsed page count assertions in documents list API test.
- Expanded ValueLine identity extraction patterns and search window.
- Allowed parsing when identity is present even if "VALUE LINE" header text is missing.
- Added parsed_page_count to documents list API and Pages column shows parsed/total.

## Decisions / Notes
- parsed_page_count is computed from distinct page numbers in metric_extractions (all runs).
- Identity exchange tokens normalize NASDAQ variants to NDQ for stock resolution consistency.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_ingestion.py`
- `docker compose exec -T api pytest -q tests/unit/test_documents_api.py`
- `docker compose exec -T api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec -T api pytest -q`
