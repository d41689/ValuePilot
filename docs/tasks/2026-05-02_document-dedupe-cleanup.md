# Document Dedupe Cleanup

## Goal / Acceptance Criteria

- Find duplicate Value Line documents for the same user, same stock/company, and same analyst report date.
- Keep one canonical document per duplicate group, preferring successfully parsed documents and then the most recently uploaded/highest id document.
- Delete duplicate document rows and their dependent parsed data:
  - `document_pages`
  - `metric_extractions`
  - parsed `metric_facts` with `source_document_id = duplicate_doc.id`
  - `pdf_documents`
- Reconcile parsed `metric_facts.is_current` for affected metric/period slots after deletion.
- Recompute Value Line ratios and Piotroski F-Score for affected stocks when apply mode is used.
- Provide dry-run output by default and apply deletion only when explicitly requested.

## Scope

In:
- Backend cleanup service.
- CLI script for dry-run/apply.
- Unit tests for grouping, deletion, fact-current reconciliation, and calculated metric refresh.

Out:
- UI changes.
- Schema changes.
- Deleting manual facts or calculated facts unrelated to affected stocks.

## Files to Change

- `backend/app/services/document_dedupe_service.py`
- `backend/scripts/dedupe_documents.py`
- `backend/tests/unit/test_document_dedupe_service.py`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_document_dedupe_service.py`

## Notes

- 2026-05-02: Started implementation. The cleanup is intentionally not hard-coded to a specific company or document id; it groups by `(user_id, stock_id, report_date)`.
- 2026-05-02: Added `DocumentDedupeService` with dry-run/apply modes. Canonical document selection prefers parsed status, then latest upload time, then highest id.
- 2026-05-02: Apply mode deletes duplicate document dependents first (`metric_facts`, `metric_extractions`, `document_pages`) before deleting `pdf_documents`, then reconciles parsed `is_current` for affected metric slots.
- 2026-05-02: Calculated fact refresh is scoped to each affected `(user_id, stock_id)` pair so cleanup for one user does not delete another user's calculated facts.
- 2026-05-02: Manual/non-parsed facts linked to duplicate documents are preserved. They are reassigned to the kept document when that does not violate the metric fact uniqueness constraint; otherwise `source_document_id` is cleared so the duplicate document can be deleted without losing the manual fact.
- 2026-05-02: Added CLI:
  - Dry-run: `docker compose exec api python -m scripts.dedupe_documents`
  - Apply: `docker compose exec api python -m scripts.dedupe_documents --apply`

## Verification

- 2026-05-02: `docker compose exec api pytest -q tests/unit/test_document_dedupe_service.py` passed (`4 passed`).
- 2026-05-02: `docker compose exec api python -m scripts.dedupe_documents` passed; local DB dry-run found `0` duplicate groups.
- 2026-05-02: `docker compose exec api pytest -q tests/unit/test_document_dedupe_service.py tests/unit/test_documents_api.py tests/unit/test_reparse_existing_document.py` passed (`30 passed`).

## Contract Checklist

- `metric_facts` remains the source of truth for queryable facts.
- Cleanup deletes parsed facts by `source_document_id` only for documents being removed; non-parsed facts are preserved and detached/reassigned before document deletion.
- Calculated fact invalidation is limited to affected stocks/users and known calculated keys.
- No raw SQL from user input.
- No formula `eval` / `exec`.
- Parsed lineage tables are cleaned before deleting the duplicate document rows.
