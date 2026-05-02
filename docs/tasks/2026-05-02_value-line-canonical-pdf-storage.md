# Value Line Canonical PDF Storage

## Goal / Acceptance Criteria
- Store newly uploaded PDFs first under `/code/storage/uploads/tmp/{uuid}.pdf`.
- After a Value Line single-company report is parsed, archive the file under `/code/storage/uploads/value_line/{exchange}/{ticker}/{report_date}-{short_hash}.pdf`.
- If the canonical file already exists, reuse it instead of storing a duplicate.
- When a canonical file is established, backfill existing matching `pdf_documents.file_storage_key` values for the same stock and report date.
- Preserve parser lineage, facts, and current-value semantics.

## Scope
- In:
  - File storage service helpers for temp upload, hashing, canonical path creation, and safe reuse/move.
  - Ingestion service call after successful single-company Value Line parsing.
  - Unit tests for canonical path, duplicate reuse, and historical path backfill.
- Out:
  - Restoring PDFs that no longer exist anywhere.
  - Schema changes.
  - Bulk manual repair UI.

## Files to Change
- `backend/app/services/file_storage.py`
- `backend/app/services/ingestion_service.py`
- Backend unit tests under `backend/tests/unit/`
- Existing document download production follow-up files may remain modified from the prior fix.

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_value_line_pdf_storage.py`
- `docker compose exec api pytest -q tests/unit/test_documents_api.py -q`
- `docker compose exec web node --test lib/documentDownload.test.js`
- `docker compose exec web npm run lint`

## Notes
- Backfill must update only document file paths. It must not mutate `metric_extractions` or `metric_facts`.
- Historical records can only be restored automatically when a matching report is uploaded again and parsed to the same `stock_id` + `report_date`.
- Implemented canonical naming as `/code/storage/uploads/value_line/{EXCHANGE}/{TICKER}/{report_date}-{sha256_12}.pdf`.
- Existing matching documents are backfilled only when their current file is missing or their existing file content hash matches the newly archived canonical PDF.
- Existing matching documents with a different on-disk PDF hash are skipped and logged to avoid overwriting a distinct same-date revision.
- Failed or unsupported uploads remain in `tmp/` so the original upload is still available for troubleshooting.

## Verification
- Red check observed before implementation: `docker compose exec api pytest -q tests/unit/test_value_line_pdf_storage.py` failed on missing storage/archive methods.
- Passed: `docker compose exec api pytest -q tests/unit/test_value_line_pdf_storage.py tests/unit/test_ingestion.py tests/unit/test_documents_api.py -q`
- Passed: `docker compose exec web node --test lib/documentDownload.test.js`
- Passed: `docker compose exec web npm run lint`

## Contract Gate
- Only `pdf_documents.file_storage_key` is backfilled; extraction and fact rows are not mutated.
- Screeners remain unchanged and continue using `metric_facts`.
- No raw SQL from user input added.
- No formula `eval`/`exec` behavior touched.
- Parsed lineage and `is_current` semantics are unchanged.
