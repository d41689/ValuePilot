# Task: Show document ID column on Documents page

## Goal / Acceptance Criteria
- Documents table includes a new `ID` column showing each document's id.
- Column is visible in the Document Register card table on `/documents`.

## Scope
### In Scope
- Frontend table update to display id.

### Out of Scope
- API changes.
- Backend changes.

## PRD References
- N/A (UI enhancement)

## Files To Change
- `frontend/app/(dashboard)/documents/page.tsx`
- `docs/tasks/2026-01-18_documents-id-column.md`

## Test Plan (Docker)
- Manual check in browser.

## Execution Plan (Approved)
1. Locate Documents table rendering.
2. Add `ID` column header and cell rendering from data.
3. Verify in browser.

## Rollback Strategy
- Revert the table changes.

## Notes / Decisions
- Added a compact `ID` column to the Documents table for quick reference.
