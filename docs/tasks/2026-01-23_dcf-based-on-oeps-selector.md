# Task: DCF “Based on” selector using OEPS norm + last 6 FY

## Goal / Acceptance Criteria
- DCF “Based on” options show:
  - `OEPS Norm`
  - last 6 FY years (e.g., 2026–2021)
- Default selected value is OEPS Norm.
- Clicking a year uses that FY’s OEPS value as “Based on”.

## Scope
**In**
- Backend API adds OEPS series to stock lookup.
- DCF page UI uses OEPS selector.

**Out**
- OEPS derivation logic changes.
- New persistence.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)**

## Files To Change
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-01-23_dcf-based-on-oeps-selector.md` (this file)

## Execution Plan (Requires Approval)
1. Update API test to assert `oeps_series` with 6 FY values (red).
2. Extend API endpoint to return OEPS series (green).
3. Update DCF page options + selection behavior (OEPS Norm + 6 FY).
4. Verify in Docker:
   - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
   - `docker compose exec web npm run lint`

## Contract Checks
- API reads only from `metric_facts` with `is_current = true`.

## Rollback Strategy
- Revert API response + UI changes.

## Notes / Results
- Added OEPS series (last 6 FY) + growth rate options (sales/cash_flow/earnings) to stock lookup API.
- Updated DCF “Based on” selector to OEPS Norm + 6 FY values; click selects that year’s OEPS.
- Added Growth Rate options (Sales / Cash Flow / Earnings) from annual_rates estimated CAGR, defaulting to the lowest value.
- Tests:
  - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` → pass
  - `docker compose exec web npm run lint` → OK
