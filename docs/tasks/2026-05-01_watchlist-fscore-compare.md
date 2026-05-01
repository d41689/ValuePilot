# Watchlist F-Score Compare

## Goal / Acceptance Criteria

- `/watchlist` has an `F-Score Compare` button immediately beside the Watchlist select.
- Clicking the button opens a dedicated comparison page with the currently selected watchlist preselected.
- The comparison page has a top watchlist select that can switch between watchlists.
- The comparison table shows each stock in the selected watchlist and F-Score totals across recent years: 5 actual years plus 2 estimate years when available.
- Estimate values are visually marked.
- Empty/loading states are handled without layout jumps.

## Scope

In:
- Watchlist toolbar UI.
- New frontend comparison route.
- Backend comparison endpoint for watchlist F-Score totals.
- Focused backend and frontend tests.

Out:
- Changes to Piotroski calculation formulas.
- Parser changes.
- Database schema changes.
- Recalculation/backfill jobs.

## Files to Change

- `backend/app/api/v1/endpoints/stock_pools.py`
- `backend/tests/unit/test_stock_pools_api.py`
- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/app/(dashboard)/watchlist/f-score-compare/page.tsx`
- `frontend/lib/watchlistFScoreCompare.js`
- `frontend/lib/watchlistFScoreCompare.test.js`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py`
- `docker compose exec web node --test lib/watchlistFScoreCompare.test.js`
- `docker compose exec web node --test lib/watchlistState.test.js`
- `docker compose exec web node --test lib/uiStandard.test.js`
- `docker compose exec web npm run lint`

## Notes

- 2026-05-01: Started implementation. Existing watchlist rows intentionally return only 3 historical non-estimate F-Scores, so the comparison page needs a dedicated endpoint/model.
- 2026-05-01: Added backend compare endpoints for pool and Overview selections. The endpoint returns each row aligned to the union of selected comparison years.
- 2026-05-01: Added `/watchlist/f-score-compare` with a watchlist selector, F-Score legend, sticky ticker/company columns, and estimate markers.
- 2026-05-01: Added an `F-Score Compare` button beside the Watchlist selector on `/watchlist`.
- 2026-05-01: Verification passed:
  - `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py`
  - `docker compose exec web node --test lib/watchlistFScoreCompare.test.js`
  - `docker compose exec web node --test lib/watchlistState.test.js`
  - `docker compose exec web node --test lib/uiStandard.test.js`
  - `docker compose exec web npm run lint`

## Contract Checklist

- [x] `metric_facts` remains the source of F-Score totals.
- [x] Numeric display uses stored normalized `value_numeric` / calculated fact JSON.
- [x] No raw SQL from user input.
- [x] No eval/exec formula execution.
- [x] Lineage and `is_current` semantics are unchanged.
