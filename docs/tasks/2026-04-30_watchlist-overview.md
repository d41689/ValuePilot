# Watchlist Overview

## Goal / Acceptance Criteria

- Add an `Overview` option to the `/watchlist` dropdown.
- `Overview` shows the union of all stocks in the current user's watchlists.
- Duplicate stocks across multiple watchlists appear once.
- `Overview` is read-only for membership: users cannot add, remove, or delete stocks from it.
- User-created watchlists keep their existing add, remove, delete, refresh, Fair Value, DCF, and F-Score behavior.

## Scope

In:
- Backend read-only overview members endpoint.
- Frontend watchlist selection state and read-only Overview UI.
- Unit/API tests for the overview behavior.

Out:
- Database schema changes.
- F-Score calculation changes.
- Production deployment.

## Files To Change

- `backend/app/api/v1/endpoints/stock_pools.py`
- `backend/tests/unit/test_stock_pools_api.py`
- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/lib/watchlistState.js`
- `frontend/lib/watchlistState.d.ts`
- `frontend/lib/watchlistState.test.js`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py`
- `docker compose exec web node --test lib/watchlistState.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Branched from `codex/watchlist-toolbar-layout` because this feature builds on the dropdown toolbar UI.
- Added a read-only `/stock_pools/overview/members` endpoint before the parameterized members route to avoid `{pool_id}` route conflicts.
- Reused the existing watchlist row serialization path so Overview returns the same shape as ordinary watchlist members.
- Updated the `/watchlist` UI to default to Overview, fetch the overview endpoint, and hide/disable add, remove, and delete membership controls for the virtual list.

## Verification

- `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py` passed.
- `docker compose exec web node --test lib/watchlistState.test.js` passed.
- `docker compose exec web npm run lint` passed.

## Contract Checklist

- `metric_facts` remains the only source for F-Score and Fair Value facts.
- Overview is a read-only virtual API/UI view; no schema changes or synthetic `stock_pools` row.
- Overview members are scoped by `current_user.id` and deduplicated by `stock_id`.
- No raw SQL or eval/exec added.
