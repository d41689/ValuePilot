# Task: DCF interactive calculator on stock DCF page

## Goal / Acceptance Criteria
- `/stocks/{ticker}/dcf` shows editable inputs for:
  - Stock Price (input)
  - Based on value (input, default computed from inputs)
  - Discount Rate (default 10%, +/- buttons + direct edit)
  - Growth Stage: Years (default 10), Growth Rate (default 20%)
  - Terminal Stage: Years (default 10), Growth Rate (default 4%)
- Values update in real time:
  - Growth Value
  - Terminal Value
  - Total Value = Growth Value + Terminal Value
- Example numbers produce:
  - Growth Value = 229.04
  - Terminal Value = 225.65
  - Total Value = 454.69

## Scope
**In**
- Frontend-only calculations + UI interactivity.
- Small math helper with unit tests.

**Out**
- Backend changes.
- Data persistence.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)** (read-only UI)

## Files To Change
- `frontend/lib/dcfMath.test.js` (new)
- `frontend/lib/dcfMath.js` (new)
- `frontend/lib/dcfMath.d.ts` (new)
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-01-23_dcf-interactive-calculator.md` (this file)

## Execution Plan (Requires Approval)
1. Write math unit tests for growth/terminal/total values (red).
2. Implement `dcfMath` helper (green).
3. Update DCF page to use the helper and add interactive inputs.
4. Verify in Docker:
   - `docker compose exec web node --test lib/dcfMath.test.js`
   - `docker compose exec web npm run lint`

## Contract Checks
- UI-only change; no backend or data-contract impact.

## Rollback Strategy
- Revert helper + DCF page changes; keep static DCF layout.

## Notes / Results
- Implemented interactive DCF inputs with live Growth/Terminal/Total values.
- Added `dcfMath` helper + Node test that matches the example values.
- Tests:
  - `docker compose exec web node --test lib/dcfMath.test.js` → pass
  - `docker compose exec web npm run lint` → OK
