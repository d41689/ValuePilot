# Task: Move DCF Stock Price Row to Bottom

## Goal / Acceptance Criteria
- On `http://localhost:3001/stocks/LRN/dcf`, the **Stock Price** row appears as the last row in the DCF table/section.
- No other ordering changes in the DCF rows.

## Scope
**In:** UI change to reorder the Stock Price row on the DCF page for stocks.
**Out:** Any data/model changes, backend changes, or broader UI refactors.

## PRD References
- docs/prd/value-pilot-prd-v0.1.md (UI display integrity; no schema changes)

## Files to Change
- TBD after locating DCF page implementation

## Test Plan (Docker)
- `docker compose exec api pytest -q` (only if backend tests are impacted)
- Frontend build/test commands TBD after inspecting project scripts

## Notes / Decisions
- Task created 2026-01-24.

## Status
- Plan approved 2026-01-24.
- Implemented UI reorder: moved Stock Price row to bottom of DCF card.

## Verification
- Not run (UI-only change; no automated frontend test command identified).

## Execution Plan (Proposed)
1. Inspect `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx` to locate the Stock Price row markup and identify the desired target position.
2. Update the layout to move the Stock Price row to the bottom of the DCF card while preserving styling and behavior.
3. Verify the page locally (manual UI check) and update task notes.

## Contract Checks
- No schema or backend changes.
- UI-only change; no impact on data lineage or metric normalization.

## Rollback Strategy
- Revert the layout change in `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`.
