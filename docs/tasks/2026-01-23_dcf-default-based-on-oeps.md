# Task: DCF “Based on” default from normalized OEPS

## Goal / Acceptance Criteria
- DCF page default “Based on” value reads from `owners_earnings_per_share_normalized`.
- Backend exposes normalized OEPS on `/api/v1/stocks/by_ticker/{ticker}`.
- If OEPS is missing, UI keeps current computed fallback.

## Scope
**In**
- Backend API response enrichment (no schema changes).
- Frontend DCF page defaulting logic.
- Unit test for API response.

**Out**
- Any changes to OEPS derivation logic.
- Any persistence changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)** (Active Value reads from `metric_facts`)

## Files To Change
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-01-23_dcf-default-based-on-oeps.md` (this file)

## Execution Plan (Requires Approval)
1. Update stock lookup API test to expect `oeps_normalized` (red).
2. Extend API endpoint to return normalized OEPS (green).
3. Update DCF page to fetch and set default “Based on”.
4. Verify in Docker:
   - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
   - `docker compose exec web npm run lint`

## Contract Checks
- UI reads from `metric_facts` only via API.

## Rollback Strategy
- Revert API response + UI changes.

## Notes / Results
- Added `oeps_normalized` to stock lookup API response.
- DCF page now uses `owners_earnings_per_share_normalized` as default “Based on” when available.
- Tests:
  - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` → pass
  - `docker compose exec web npm run lint` → OK
