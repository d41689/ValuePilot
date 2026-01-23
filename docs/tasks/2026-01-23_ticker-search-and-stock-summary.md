# Task: Ticker search + stock summary page

## Goal / Acceptance Criteria
- On `http://localhost:3001/home`, show a ticker search box:
  - User types a ticker and presses Enter → navigates to `/stocks/{ticker}/summary`.
- On `http://localhost:3001/stocks/{ticker}/summary`, show:
  - A ticker search box at the top with the same Enter → navigate behavior.
  - A card under the search box that displays:
    - Company name
    - `{exchange}:{ticker}`
    - Recent price
    - P/E

## Scope
**In**
- Frontend (Next.js) UI changes for `/home` and new `/stocks/[ticker]/summary` route.
- Backend API support to resolve a stock by ticker and provide the fields needed by the UI.

**Out**
- Any schema changes.
- Any changes to parsing / ingestion behavior.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)** (Active Value reads from `metric_facts`)

## Files To Change
- Backend:
  - `backend/app/api/v1/endpoints/stocks.py`
  - `backend/tests/unit/test_stocks_lookup_by_ticker.py` (new)
- Frontend:
  - `frontend/app/(dashboard)/home/page.tsx`
  - `frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx` (new)
  - `frontend/components/TickerSearchBox.tsx` (new)
  - `frontend/components/StockSummaryCard.tsx` (new)

## Execution Plan (Requires Approval)
1. Add backend API endpoint: `GET /api/v1/stocks/by_ticker/{ticker}` returning stock identity + latest `mkt.price` and `val.pe` facts (from `metric_facts` where `is_current = true`).
2. Write a backend test that inserts a `User`, `Stock`, and two `MetricFact`s and asserts the endpoint returns the expected payload.
3. Implement frontend `TickerSearchBox` component used on `/home` and `/stocks/[ticker]/summary` (Enter → navigate).
4. Implement frontend summary page that calls the new API and renders the card (with loading + not-found states).
5. Verify in Docker:
   - `docker compose exec api pytest -q`
   - `docker compose exec web npm run lint` (or equivalent) if available

## Contract Checks
- Screen/UI reads active values via `metric_facts` only (`is_current = true`).
- No raw SQL; SQLAlchemy `select()` only.

## Rollback Strategy
- Revert the added route/components and remove the new API endpoint + test.

## Notes / Results
- Added `GET /api/v1/stocks/by_ticker/{ticker}` (case-insensitive) returning stock identity + active `mkt.price` and `val.pe`.
- Added UI search on `/home` and `/stocks/[ticker]/summary` + summary card.
- Tests:
  - `docker compose exec api pytest -q` → `83 passed` (2026-01-23)
  - `docker compose exec web npm run lint` → OK
