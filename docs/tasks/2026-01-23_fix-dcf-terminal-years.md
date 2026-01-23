# Task: DCF large terminal years stability + defaults

## Goal / Acceptance Criteria
- Terminal Stage `Years` default is **1000**.
- Setting Terminal Stage `Years` to **100000** does not produce `NaN`.
- Growth/Terminal/Total values still match the example for the provided inputs.

## Scope
**In**
- Frontend math helper improvements for numeric stability.
- DCF UI default updates.
- Unit test coverage for large-year stability.

**Out**
- Backend changes.
- Persistence or data storage.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)** (read-only UI)

## Files To Change
- `frontend/lib/dcfMath.test.js`
- `frontend/lib/dcfMath.js`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-01-23_fix-dcf-terminal-years.md` (this file)

## Execution Plan (Requires Approval)
1. Add math test for large terminal years (red).
2. Update `dcfMath` to use stable closed-form calculations (green).
3. Update DCF page default terminal years to 1000.
4. Verify in Docker:
   - `docker compose exec web node --test lib/dcfMath.test.js`
   - `docker compose exec web npm run lint`

## Contract Checks
- UI-only change; no backend/data-contract impact.

## Rollback Strategy
- Revert helper changes and default year update.

## Notes / Results
- Terminal Stage `Years` default set to 1000.
- `dcfMath` uses stable closed-form formulas; large terminal years no longer produce `NaN`.
- Tests:
  - `docker compose exec web node --test lib/dcfMath.test.js` → pass
  - `docker compose exec web npm run lint` → OK
