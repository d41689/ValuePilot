# Fix F-Score Input Value Precision Display

## Goal / Acceptance Criteria
- F-score tooltip input values should display enough precision to explain calculations such as `liquidity.current_ratio`.
- Preserve compact score-cell display.
- Do not change calculation semantics; only display precision unless tests reveal backend rounding.

## Scope
- In: Dynamic F-score frontend formatting/tests.
- Out: Parser changes, formula changes, schema changes.

## Files To Change
- `frontend/lib/dynamicFScoreCard.js`
- `frontend/lib/dynamicFScoreCard.d.ts`
- `frontend/lib/dynamicFScoreCard.test.js`
- `frontend/components/DynamicFScoreCard.tsx`

## Test Plan (Docker)
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js`
- `docker compose exec api pytest -q` if backend touched or before final handoff.

## Progress Notes
- 2026-05-04: Confirmed backend stores full current ratio values for ADBE; one-decimal values are frontend tooltip formatting only.
- 2026-05-04: Added separate tooltip input formatter that preserves up to 4 decimal places while keeping score cells compact.
- 2026-05-04: Verification passed:
  - `docker compose exec web node --test lib/dynamicFScoreCard.test.js` -> 6 passed.

## Contract Checklist
- [x] No calculation semantics changed.
- [x] No raw SQL from user input introduced.
- [x] Verification recorded.
