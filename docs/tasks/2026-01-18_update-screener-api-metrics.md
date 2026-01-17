# Task: Align screener API response with frontend columns

## Goal / Acceptance Criteria

- Update the screener API (`POST /api/v1/screener/run`) so the response includes metric values needed by the screener table columns in `frontend/app/(dashboard)/screener/page.tsx`.
- Return a `metrics` object per stock containing:
  - `net_profit_usd_millions`
  - `depreciation_usd_millions`
  - `capital_spending_per_share_usd`
  - `common_shares_outstanding_millions`
  - `timeliness`
  - `safety`
  - `avg_annual_dividend_yield_pct`
  - `company_financial_strength`
  - `stock_price_stability`
  - `price_growth_persistence`
  - `earnings_predictability`
- Keep screeners using `metric_facts` only, with `is_current = true`.

## Frontend Context (Existing Change)

- Screener UI added columns and expects the above fields (see `frontend/app/(dashboard)/screener/page.tsx`).

## Scope (In / Out)

### In Scope

- Backend API response shape update for `/screener/run`.
- Query current `metric_facts` for the listed metrics and return them under `metrics`.
- Add tests for the API response structure.

### Out of Scope

- Changes to the frontend (already done by user).
- New parsing logic to populate missing metrics (handled elsewhere).

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md`: Screeners must read only `metric_facts` and filter on `value_numeric`.

## Files To Change

- `backend/app/api/v1/endpoints/screener.py`
- `backend/app/services/screener_service.py`
- `backend/tests/unit/test_screener_api_metrics.py` (new)

## Test Plan (Docker Only)

- `docker compose exec api pytest -q tests/unit/test_screener_api_metrics.py`
- `docker compose exec api pytest -q`

## Notes / Decisions

- If a metric is missing for a stock, the field may be omitted or set to null in `metrics`.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_screener_api_metrics.py`
- `docker compose exec api pytest -q`
