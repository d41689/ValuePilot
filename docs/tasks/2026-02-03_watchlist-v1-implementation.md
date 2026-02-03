# 2026-02-03 Watchlist V1 Implementation

Status: Approved (2026-02-03)

## Goal / Acceptance Criteria

- Provide a V1 Watchlist UI that lets a user:
  - create/delete watchlists
  - add/remove stocks in a watchlist
  - edit Fair Value per (user, stock) and see Margin of Safety (MOS)
  - view EOD close price (and optional Δ Today)
- Reuse existing schema tables (`stock_pools`, `pool_memberships`, `metric_facts`, `stock_prices`).
- Do not introduce schema migrations in V1.
- Preserve v0.1 contract governance:
  - Metric semantics live in `docs/metric_facts_mapping_spec.yml`.
  - Watchlist PRD MUST NOT redefine metric semantics.

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/prd/README.md` (Contract Sources & Precedence)
- `docs/prd/watchlist/watchlist-v1.md`

## Scope

### In Scope
- Backend APIs for `stock_pools` + `pool_memberships` (CRUD minimal set for Watchlist)
- Backend API to upsert a manual Fair Value metric fact
- Watchlist frontend page (list + table)
- Integrate existing EOD price refresh endpoint:
  - `POST /api/v1/stocks/prices/refresh`

### Out of Scope
- Real-time quotes / intraday data
- Creating “stub stocks” by ticker (V1 only supports existing `stocks`)
- Trading calendar tables / holiday correctness beyond current heuristics
- Alerts / notifications / portfolios

## Execution Plan (Needs Human Approval)

### Step 1: Contract / Semantics
- Add a mapping-spec entry for “user fair value”:
  - `metric_key`: to be decided in mapping spec (dotted namespace; no unit encoding)
  - `unit`: USD
  - `period_type`: AS_OF
- Confirm Fair Value display precedence:
  1) manual Fair Value metric fact (`is_current=true`)
  2) `target.price_18m.mid` parsed fact (`is_current=true`)
  3) null

### Step 2: Backend APIs (FastAPI)
- `stock_pools` endpoints (user-owned; `user_id` query param):
  - GET `/api/v1/stock_pools?user_id=...`
  - POST `/api/v1/stock_pools?user_id=...`
  - DELETE `/api/v1/stock_pools/{pool_id}?user_id=...`
- `pool_memberships` endpoints:
  - GET `/api/v1/stock_pools/{pool_id}/members?user_id=...`
  - POST `/api/v1/stock_pools/{pool_id}/members?user_id=...` (body includes `stock_id`)
  - DELETE `/api/v1/stock_pools/{pool_id}/members/{membership_id}?user_id=...`
- Metric facts write endpoint (extend stocks):
  - PUT `/api/v1/stocks/{stock_id}/facts?user_id=...`
  - Enforce v0.1 correction semantics:
    - insert a new `metric_facts` row (`source_type=manual`, `is_current=true`)
    - set previous current row(s) for the same (user_id, stock_id, metric_key) to `is_current=false`
  - Notes (V1):
    - This endpoint is intentionally generic to match the existing `GET /api/v1/stocks/{stock_id}/facts`.
    - Optional (future): add a semantic alias like `PUT /api/v1/stocks/{stock_id}/facts/fair-value` that calls the same implementation.

Ownership enforcement (MUST):
- The backend MUST enforce ownership server-side; `user_id` MUST NOT be “trusted” to imply authorization by itself.
- For any pool/membership operation, validate:
  - `stock_pools.user_id == user_id`
  - `pool_memberships.pool_id` belongs to that pool and `pool_memberships.user_id == user_id`
- For Fair Value writes, always write `metric_facts.user_id = user_id`, and reject any attempt to write facts for another user.
- If/when auth/session is introduced, migrate from `user_id` query params to server-derived identity (do not duplicate authorization logic in the client).

### Step 3: Frontend Watchlist Page
- Sidebar for watchlists (list + create)
- Main table for members with:
  - Price (EOD close)
  - Fair Value (editable)
  - MOS computed client-side
  - optional Δ Today (only when two EOD prices exist)
- On page load:
  - render cached data
  - call refresh (`POST /api/v1/stocks/prices/refresh`) in background
  - re-fetch table data after refresh completes

Deterministic read rules (implementation guidance):
- Price (EOD):
  - `SELECT close FROM stock_prices WHERE stock_id = :id AND price_date = :target_date ORDER BY created_at DESC LIMIT 1`
- Δ Today (optional, EOD):
  - `prev_price_date = SELECT max(price_date) FROM stock_prices WHERE stock_id = :id AND price_date < :target_date`
  - If either close is missing, return null for Δ Today.

### Step 4: Tests
- Backend unit tests:
  - `stock_pools` CRUD + membership CRUD
  - Fair Value write uses `metric_facts` current semantics
  - Watchlist table read assembles price + fair value fallback correctly
- Frontend tests: optional for V1 (define after UI stack confirmation)

## Files To Change (Expected)

- Backend:
  - `backend/app/api/v1/endpoints/stocks.py` (extend facts write)
  - `backend/app/api/v1/endpoints/` (new `stock_pools` endpoints module)
  - `backend/app/models/stocks.py` (no schema change; only if relationships need exposure)
- Docs:
  - `docs/metric_facts_mapping_spec.yml` (add fair value mapping entry)
- Frontend:
  - (TBD based on existing frontend structure)

## Test Plan (Docker)

- `docker compose exec api pytest -q`
- If tests added:
  - `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py`
  - `docker compose exec api pytest -q tests/unit/test_metric_facts_manual_fair_value.py`

## Progress Update (2026-02-03)
- Added `val.fair_value` manual metric entry to `docs/metric_facts_mapping_spec.yml`.
- Implemented `stock_pools` + `pool_memberships` endpoints with ownership enforcement and deterministic price reads.
- Added Fair Value write endpoint: `PUT /api/v1/stocks/{stock_id}/facts?user_id=...` (manual only).
- Built Watchlist UI page (sidebar + table + inline Fair Value edit + refresh hook).
- Added backend unit tests for watchlist APIs and Fair Value writes.

## Verification (Docker)
- `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py tests/unit/test_metric_facts_manual_fair_value.py`

## Contract Checklist (Status)

- [x] No new DB tables or migrations in V1
- [x] Watchlist uses `stock_pools` + `pool_memberships`
- [x] Price reads are from `stock_prices` (EOD close)
- [x] Any numeric comparisons are against normalized numeric fields (`metric_facts.value_numeric`)
- [x] Metric semantics are defined only in `docs/metric_facts_mapping_spec.yml`
- [x] Manual corrections are insert-only with `is_current` flipping
