# Task: DCF Growth Rate fallback (sales -> revenues)

## Goal / Acceptance Criteria
- On `http://localhost:3001/stocks/<TICKER>/dcf`, the **Growth Stage → Growth Rate** options include a "Sales" growth rate even when the underlying Value Line annual rates section uses `revenues` instead of `sales`.
- Behavior:
  - Prefer `rates.sales.cagr_est` when present.
  - Otherwise fall back to `rates.revenues.cagr_est`.
  - If the fallback is used, the UI label should be **Revenues** (not Sales) to match the source.
- All tests pass in Docker.

## Scope
### In
- Backend `/api/v1/stocks/by_ticker/{ticker}` response shaping (`growth_rate_options`).
- Unit test coverage for the fallback behavior.

### Out
- Schema changes.
- Parser changes (we accept the page JSON may emit either `sales` or `revenues`).

## Files To Change
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`

## Test Plan (Docker)
- `docker compose exec api pytest -q backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec api pytest -q`

## Notes
- Observed in `SPOT20260123` fixture: `annual_rates.metrics[].metric_key` uses `revenues` (not `sales`), so the DB facts become `rates.revenues.cagr_est` instead of `rates.sales.cagr_est`.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` ✅
- `docker compose exec api pytest -q` ✅ (90 passed)
