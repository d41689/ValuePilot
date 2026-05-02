# Document Delete Action

## Goal / Acceptance Criteria

- Document dedupe apply command is documented in `README.md`.
- `/documents` page shows a delete action for each document.
- The authenticated owner can delete their document from the UI.
- Deletion removes the document and its dependent database rows:
  - `document_pages`
  - `metric_extractions`
  - `metric_facts` linked by `source_document_id`
  - `pdf_documents`
- After deletion, parsed `metric_facts.is_current` is reconciled for affected metric/period slots.
- Affected Value Line ratios and Piotroski F-Score facts are refreshed.
- Non-owners cannot delete another user's document.

## Scope

In:
- README operational documentation.
- Backend document delete service/API.
- Frontend `/documents` delete button and feedback.
- Unit tests for owner deletion, non-owner rejection, dependent cleanup, and current reconciliation.

Out:
- Bulk delete UI.
- Storage object deletion from local/S3-style storage.
- Schema changes.

## Files to Change

- `README.md`
- `backend/app/services/document_dedupe_service.py`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/app/(dashboard)/documents/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_documents_api.py tests/unit/test_document_dedupe_service.py`
- Frontend type/lint/build check if available in the frontend container/package scripts.

## Notes

- 2026-05-02: Started implementation. The delete endpoint should reuse the cleanup service behavior rather than duplicating ad hoc deletes in the route.
- 2026-05-02: Added `DocumentDedupeService.delete_document()` and `DELETE /api/v1/documents/{document_id}`. The route returns 404 when the authenticated user does not own the document.
- 2026-05-02: Explicit single-document deletion removes all `metric_facts` linked by `source_document_id`, including manual facts tied to that document. Duplicate cleanup still preserves non-parsed facts because that path removes redundant uploads, not a user-selected document.
- 2026-05-02: Added a destructive `Delete` action to `/documents`; it prompts for confirmation, calls the owner-only endpoint, refreshes the register, and clears any open detail/compare state for the deleted document.
- 2026-05-02: Documented the dedupe dry-run/apply commands in `README.md`.

## Verification

- 2026-05-02: `docker compose exec api pytest -q tests/unit/test_documents_api.py::test_delete_document_removes_dependents_and_reconciles_current tests/unit/test_documents_api.py::test_delete_document_requires_owner` passed (`2 passed`).
- 2026-05-02: `docker compose exec api pytest -q tests/unit/test_documents_api.py tests/unit/test_document_dedupe_service.py` passed (`24 passed`).
- 2026-05-02: `docker compose exec web npm run lint` passed.
- 2026-05-02: `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- `metric_facts` remains the queryable source of truth.
- Deletion uses structured SQLAlchemy statements; no raw SQL from user input.
- No formula `eval` / `exec`.
- Owner check is enforced before deleting.
- Affected parsed `is_current` slots are reconciled after deletion.
- Affected calculated Value Line ratios and Piotroski F-Score facts are invalidated and recalculated.
