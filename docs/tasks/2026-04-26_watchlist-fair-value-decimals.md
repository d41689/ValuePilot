# Task: Format watchlist Fair Value decimals

## Goal / Acceptance Criteria
- On `/watchlist`, the `Fair Value` column displays saved fair value numbers with exactly two decimal places.
- Preserve editing and save behavior for Fair Value inputs.

## Scope
**In**
- Watchlist frontend display state for Fair Value values.
- Focused frontend unit test.
- Browser verification on `http://localhost:3001/watchlist`.

**Out**
- Backend API/schema changes.
- Fair Value calculation semantics.
- Parser changes.

## Files To Change
- `docs/tasks/2026-04-26_watchlist-fair-value-decimals.md`
- `frontend/lib/watchlistState.js`
- `frontend/lib/watchlistState.test.js`

## Test Plan
- `docker compose exec web node --test lib/watchlistState.test.js`
- Browser check on `/watchlist`.

## Progress Log
- [x] Create task log.
- [x] Locate Fair Value display state.
- [x] Add failing frontend test.
- [x] Implement two-decimal formatting.
- [x] Run Docker verification.
- [x] Verify in browser.

## Notes / Decisions / Gotchas
- The Fair Value table cell is an editable input; the initial edit state should be formatted without changing backend numeric values.

## Verification Results
- Red test confirmed `buildFairValueEdits` previously returned raw numeric strings such as `120.5` and `98.4567`.
- `docker compose exec web node --test lib/watchlistState.test.js` passed after the fix: 3 tests passed.
- Browser check on `http://localhost:3001/watchlist` loaded successfully and confirmed the `Fair Value` table header is present. The current account has no watchlist rows, so there were no Fair Value input values to inspect visually.
