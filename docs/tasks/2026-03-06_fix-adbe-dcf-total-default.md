# Task: Fix ADBE DCF total default value

## Goal / Acceptance Criteria
- On `/stocks/ADBE/dcf`, the initial `Total Value` must default from stock-specific DCF inputs instead of the static fallback that yields `$844.25`.
- DCF defaults must update correctly when stock lookup payload provides OEPS and growth-rate options.
- Ticker changes on the DCF page must not retain the previous stock's `Based on` or growth-rate defaults.

## Scope
**In**
- Frontend DCF default-state resolution.
- Frontend unit tests for DCF default resolution / math integration.

**Out**
- Backend schema/API contract changes.
- Fair Value persistence semantics.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → `UI & Query Semantics (V1)`

## Files To Change
- `frontend/lib/dcfMath.test.js`
- `frontend/lib/dcfDefaults.js` (new, if needed)
- `frontend/lib/dcfDefaults.d.ts` (new, if needed)
- `frontend/lib/dcfDefaults.test.js` (new, if needed)
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-03-06_fix-adbe-dcf-total-default.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Add a failing frontend test that reproduces stock-specific DCF defaults resolving to the wrong fallback total.
2. Extract or tighten DCF default resolution so fetched OEPS / growth options deterministically override the static fallback.
3. Reset per-ticker DCF state on ticker changes to avoid stale values carrying across stocks.
4. Verify in Docker:
   - `docker compose exec web node --test lib/dcfMath.test.js lib/dcfDefaults.test.js`
   - `docker compose exec web npm run lint`

## Contract Checks
- Frontend reads stock inputs from the existing `/api/v1/stocks/by_ticker/{ticker}` response only.
- No changes to `metric_facts`, `is_current`, normalization, raw SQL, or formula execution.

## Rollback Strategy
- Revert the frontend DCF default-state changes and the associated tests.

## Notes / Results
- Investigation: `$844.25` matches the static fallback `12 + 3 - 0.45 = 14.55` run through the current DCF defaults, so the page is falling back when it should apply stock-specific OEPS defaults.
- Implemented `resolveDcfDefaults()` to normalize OEPS / growth-rate defaults from `/api/v1/stocks/by_ticker/{ticker}` in one place.
- Updated the DCF page to:
  - reset stock-specific state when the ticker changes,
  - wait for stock lookup resolution before showing growth / terminal / total values,
  - apply the stock lookup defaults deterministically once the payload arrives.
- Added a regression test that reproduces the ADBE case and asserts the default total resolves to the stock-driven value instead of `$844.25`.

## Verification Results
- `docker compose exec web node --test lib/dcfMath.test.js lib/dcfDefaults.test.js lib/dcfInputsSeries.test.js` → pass
- `docker compose exec web npm run lint` → pass with pre-existing warnings in `frontend/app/(dashboard)/watchlist/page.tsx` only; no new DCF warnings introduced
