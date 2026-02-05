# 2026-02-05 DCF Latest Stock Price

## Goal / Acceptance Criteria
- DCF page uses latest stock price sourced from MarketDataService (yfinance/twelvedata) via stock_prices.
- `/api/v1/stocks/by_ticker/{ticker}` exposes latest stock price fields.
- No schema changes.

## Scope
### In Scope
- Backend: add latest stock price fields to stock-by-ticker response.
- Frontend: DCF page refreshes prices and displays latest price.
- Tests for stock-by-ticker latest price behavior.

### Out of Scope
- New providers or schema migrations.

## Files To Change
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-02-05_dcf-latest-stock-price.md`

## Test Plan (Docker)
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec api pytest -q`

## Progress Update
- Added latest stock price fields to stock-by-ticker response using `stock_prices`.
- DCF page now refreshes prices via MarketDataService and displays the latest price.
- Added regression test coverage for latest price lookup.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec api pytest -q`

## Contract Checklist
- [x] No schema changes.
- [x] DCF uses latest market price.
