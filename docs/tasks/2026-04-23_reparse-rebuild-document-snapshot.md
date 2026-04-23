# Task: Reparse should rebuild a document's parsed snapshot

## Goal / Acceptance Criteria
- When a user clicks `reparse`, the system should discard the document's old parsed snapshot and rebuild it from the current parse output.
- Old `parsed` records linked to the same `document_id` must not remain visible after reparse.
- If the parsed identity changes (for example `FNVD -> FNV`), the document should only show the new company after reparse.
- `/documents` should no longer surface mixed old/new companies for the same document after reparse.

## Scope
**In**
- Reparse behavior in `IngestionService`
- Regression tests for document-level parsed snapshot replacement
- Task log updates

**Out**
- Introducing a formal `parse_run` model
- Manual fact semantics
- Frontend-only filtering workarounds

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Value Line-only scope, lineage, normalized facts
- `AGENTS.md` -> task logging, Docker-only verification, parser safety

## Files To Change
- `docs/tasks/2026-04-23_reparse-rebuild-document-snapshot.md`
- `backend/app/services/ingestion_service.py`
- `backend/tests/unit/test_reparse_existing_document.py`
- `backend/tests/unit/test_documents_api.py` if endpoint-level coverage is needed

## Execution Plan
1. Add a regression test for reparse where a document's parsed identity changes from one stock to another.
2. Make `reparse_existing_document()` clear the document's old parsed snapshot before rebuilding it.
3. Verify that only the rebuilt parsed facts remain attached to the document.
4. Run targeted Docker tests, then broader regression.

## Contract Checks
- Only delete `source_type='parsed'` rows for the target `document_id`.
- Do not touch manual facts.
- Preserve original PDF and document shell; rebuild only the parsed snapshot.

## Rollback Strategy
- Revert service/test changes and restore prior reparse behavior if this unexpectedly breaks current-document reads.

## Progress Log
- [x] Add failing regression test.
- [x] Implement snapshot rebuild behavior.
- [x] Run targeted Docker verification.
- [x] Run broader Docker verification.

## Notes / Decisions / Gotchas
- The simplest correct behavior here is treating `document_id` as a single current parsed snapshot, not an append-only parse history.
- Implementation clears only `source_type='parsed'` facts for the target document and all `metric_extractions` for that document before rebuilding.
- This preserves manual facts and the document shell/PDF while ensuring `/documents` no longer shows mixed company identities after reparse.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec api pytest -q tests/unit/test_documents_api.py`
- `docker compose exec api pytest -q`
- Results:
  - `7 passed in 0.36s`
  - `7 passed in 1.47s`
  - `124 passed in 21.53s`
