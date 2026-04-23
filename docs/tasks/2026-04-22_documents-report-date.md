# Task: Surface document report date on documents page

## Goal / Acceptance Criteria
- `/documents` shows each uploaded document's report date when the parser can determine it.
- The parsed report date is stored on the document record so it remains visible in document metadata after parsing.
- New uploads and reparses update document metadata with the parsed report date.

## Scope
**In**
- Persisting parsed report dates onto `pdf_documents`.
- Returning document report dates from the documents API.
- Showing report dates on the `/documents` page.
- Backend tests covering API output and reparse persistence.
- Alembic migration for the new document metadata column.

**Out**
- Changing parser extraction rules for how `report_date` is derived.
- Backfilling historical documents beyond what reparsing already supports.
- Redesigning the documents page beyond adding this metadata.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> document ingestion and normalized storage
- `docs/prd/value-pilot-prd-v0.1.md` -> UI and document registry expectations
- `AGENTS.md` -> Docker-only verification, task logging, contract checks

## Files To Change
- `docs/tasks/2026-04-22_documents-report-date.md` (this file)
- `backend/app/models/artifacts.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/alembic/versions/20260422093000-add_pdf_documents_report_date.py`
- `backend/tests/unit/test_documents_api.py`
- `backend/tests/unit/test_reparse_existing_document.py`
- `frontend/app/(dashboard)/documents/page.tsx`

## Execution Plan (Assumed approved per direct request)
1. Add failing backend tests for document list output and reparse metadata updates.
2. Add a nullable `report_date` column to `pdf_documents` and wire the ORM model.
3. Update ingestion and reparse flows to persist parsed report dates onto the document.
4. Return the stored report date from the documents API and render it on `/documents`.
5. Verify in Docker with migration and targeted tests.

## Contract Checks
- Parsed lineage in `metric_extractions` remains immutable.
- Parsed facts continue to come from normalized mapping flow; no screener/formula behavior changes.
- No raw SQL from user input.
- Document metadata is updated only after successful parsing yields a report date.

## Rollback Strategy
- Revert the new `report_date` UI column and API response field.
- Revert ingestion metadata persistence.
- Downgrade the Alembic migration if the schema change needs to be removed.

## Progress Log
- [x] Add failing tests.
- [x] Add schema/model support for document report dates.
- [x] Persist report dates during upload and reparse.
- [x] Show report dates on `/documents`.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Initial inspection found that `IngestionService` already extracts `report_date` but never writes it to `PdfDocument`.
- `/documents` currently lists upload metadata only, so the missing value is a data plumbing gap rather than a parser gap.
- Added a nullable `pdf_documents.report_date` column instead of inferring report dates on every list request; this keeps the document registry metadata stable and cheap to query.
- Reparse now clears `doc.report_date` before processing pages, then writes the parsed value from the current run so stale metadata does not survive a failed/changed parse.
- The `/documents` UI renders report date as a date-only field, separate from upload timestamp.

## Verification Results
- `docker compose up -d --build` -> pass
- `docker compose exec api alembic upgrade head` -> pass
- `docker compose exec api pytest -q tests/unit/test_documents_api.py` -> pass (`3 passed`)
- `docker compose exec api pytest -q tests/unit/test_reparse_existing_document.py` -> pass (`4 passed`)
- `docker compose exec -w /app web npm run lint` -> pass (`No ESLint warnings or errors`)
