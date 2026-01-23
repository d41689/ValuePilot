# Task: Add DCF page + link from summary

## Goal / Acceptance Criteria
- `/stocks/{ticker}/summary` page footer shows a **DCF** link.
- Clicking **DCF** navigates to `/stocks/{ticker}/dcf`.
- `/stocks/{ticker}/dcf` page:
  - Top shows a ticker search box (Enter → navigate to `/stocks/{ticker}/dcf`).
  - Below search box displays a static DCF layout matching the provided UI screenshot.

## Scope
**In**
- Frontend route and UI changes only.
- A small route helper to build stock URLs.

**Out**
- Any backend changes.
- Any DCF calculation logic.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)** (read-only UI; no data writes)

## Files To Change
- `frontend/components/TickerSearchBox.tsx`
- `frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx` (new)
- `frontend/lib/stockRoutes.js` (new)
- `frontend/lib/stockRoutes.d.ts` (new)
- `frontend/lib/stockRoutes.test.js` (new)
- `docs/tasks/2026-01-23_add-dcf-page.md` (this file)

## Execution Plan (Requires Approval)
1. Add a route helper + unit test (Node test runner) for building stock routes (red → green).
2. Update `TickerSearchBox` to accept a destination page (`summary` or `dcf`).
3. Add DCF link to summary page footer.
4. Create DCF page with search box + static layout matching the screenshot.
5. Verify in Docker:
   - `docker compose exec web node --test lib/stockRoutes.test.js`
   - `docker compose exec web npm run lint`

## Contract Checks
- UI-only change; no backend / data contract impact.

## Rollback Strategy
- Remove DCF page route, helper, and link; revert `TickerSearchBox` changes.

## Notes / Results
- Added DCF page route and static layout; summary page now links to DCF.
- Added `stockRoutes` helper + Node test.
- Tests:
  - `docker compose exec web node --test lib/stockRoutes.test.js` → pass
  - `docker compose exec web npm run lint` → OK
