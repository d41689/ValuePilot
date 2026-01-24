# Task: DCF Stock Price + Total Value row + Safe Margin

## Goal / Acceptance Criteria
- DCF page shows Stock Price and Total Value on the same row.
- Show Safe Margin = `100 * (1 - Stock Price / Total Value)` on that row.

## Scope
**In**
- Frontend layout + computed Safe Margin.

**Out**
- API or calculation logic changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)**

## Files To Change
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-01-23_dcf-safe-margin.md` (this file)

## Execution Plan (Requires Approval)
1. Update DCF layout and add Safe Margin calculation.
2. Verify with `docker compose exec web npm run lint`.

## Notes / Results
- Stock Price and Total Value merged into one row with Safe Margin.
- Tests:
  - `docker compose exec web npm run lint` → OK
