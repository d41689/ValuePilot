# Task: Fix DCF inputs following "Based on" selection

## Goal / Acceptance Criteria
- On `/stocks/{ticker}/dcf`, the three component inputs below `Based on` must change with the selected `OEPS Norm` / FY year.
- The displayed `Based on` value must match `net profit / sh + depreciation / sh - capital spending / sh` for the selected default input set.
- GOOG must no longer show the static fallback `12.00 / 3.00 / 0.45` after stock data loads.

## Scope
**In**
- Backend stock lookup response enrichment for DCF component inputs.
- Frontend DCF page state wiring for `Based on` selection and input synchronization.
- Backend/frontend unit tests for the new response and selection behavior.

**Out**
- OEPS derivation rule changes.
- Schema changes or persistence changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → `UI & Query Semantics (V1)`
- `docs/prd/value-pilot-prd-v0.1.md` → `Normalization (V1)`

## Files To Change
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/lib/dcfInputsSeries.test.js`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-03-13_fix-dcf-inputs-follow-based-on.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Add/update tests to require stock lookup payload to expose DCF component inputs for `norm` and FY series.
2. Extend `/api/v1/stocks/by_ticker/{ticker}` to return those DCF component inputs from `metric_facts`.
3. Wire the DCF page so `Based on` selection hydrates and switches the three component inputs, and clears the manual override when selection-driven inputs are applied.
4. Verify in Docker:
   - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
   - `docker compose exec web node --test lib/dcfMath.test.js lib/dcfDefaults.test.js lib/dcfInputsSeries.test.js`
   - `docker compose exec web npm run lint`

## Contract Checks
- API reads only from `metric_facts` with `is_current = true`.
- DCF component values are derived from existing normalized facts:
  - `per_share.eps`
  - `is.depreciation / equity.shares_outstanding`
  - `per_share.capital_spending`
- No changes to `metric_facts`, `is_current`, raw SQL, or formula execution.

## Rollback Strategy
- Revert stock lookup payload enrichment and DCF page input synchronization changes.

## Notes / Results
- Investigation: current DCF page still hard-codes `12.00 / 3.00 / 0.45`; the existing `dcfInputsSeries` helper is unused, and `/api/v1/stocks/by_ticker/{ticker}` does not yet return `dcf_inputs` or `dcf_inputs_series`.
- Extended `/api/v1/stocks/by_ticker/{ticker}` to return:
  - `dcf_inputs`: the component input set for `OEPS Norm`, sourced from the FY whose OEPS value is the median-used normalized value
  - `dcf_inputs_series`: per-FY component input sets aligned with `oeps_series`
- Wired the DCF page to apply `dcf_inputs` / `dcf_inputs_series` whenever the `Based on` selection changes.
- Component input edits now clear the manual `Based on` override so the displayed `Based on` value falls back to the formula-driven sum again.
- Manual spot check:
  - `GOOG` now returns `dcf_inputs.net_profit_per_share = 11.25`
  - `dcf_inputs.depreciation_per_share = 2.195945945945946`
  - `dcf_inputs.capital_spending_per_share = 8.75`
  - Sum = `4.695945945945946`, matching `oeps_normalized`

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` → pass (`3 passed`)
- `docker compose exec web node --test lib/dcfMath.test.js lib/dcfDefaults.test.js lib/dcfInputsSeries.test.js` → pass
- `curl -s http://localhost:8001/api/v1/stocks/by_ticker/GOOG | jq ...` → `dcf_inputs` present and matches `oeps_normalized`
- `docker compose exec web npm run lint` → pass with pre-existing warnings in `frontend/app/(dashboard)/watchlist/page.tsx` only; no new DCF warnings introduced
