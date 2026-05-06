# Oracle's Lens Historical Price Context

## Goal / Acceptance Criteria

- Add Milestone 5 historical snapshot price context for Oracle's Lens.
- When a historical 13F period is selected, valuation and owner earnings yield use local EOD price data at or before the selected period end.
- When the latest complete period is selected, the dashboard continues using the latest local EOD price.
- API exposes price context metadata so the UI can distinguish latest price from historical snapshot price.
- Missing historical price data is explicit.

## Scope

In:
- Backend Oracle's Lens dashboard service.
- Backend unit tests for historical period price selection.
- Minimal frontend display of price context.

Out:
- External market-data backfill job.
- Provider/network calls.
- New database schema.
- Historical chart visualization.

## Files To Change

- `backend/app/services/oracles_lens/dashboard.py`
- `backend/tests/unit/test_oracles_lens.py`
- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec api pytest -q`

## Notes

- This step consumes already-stored `stock_prices`; it does not fetch external data.
- The next slice can add a controlled backfill command/service using the existing provider abstraction.

## Implementation Notes

- Added historical price context selection to Oracle's Lens.
- Latest complete period continues to use the latest local `stock_prices` row.
- Older selected periods use the latest local `stock_prices` row with `price_date <= selected period end`.
- Quality overlay owner earnings yield now uses the same selected price context.
- Valuation reference payload now includes:
  - `current_price_date`
  - `price_context`
- Frontend displays whether the price is a latest local price or historical snapshot.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_adds_value_line_quality_overlay tests/unit/test_oracles_lens.py::test_oracles_lens_adds_conservative_valuation_reference tests/unit/test_oracles_lens.py::test_oracles_lens_uses_period_price_for_historical_snapshot` - 3 passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 6 passed
- `docker compose exec web node --test lib/oraclesLens.test.js` - 9 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q` - 207 passed
- `git diff --check` - passed

## Contract Checklist

- [x] `stock_prices` is used as stored local EOD price data.
- [x] No external provider/network calls were added.
- [x] No schema migration.
- [x] Missing historical price remains explicit through existing price coverage and unavailable reasons.
- [x] UI labels historical prices as snapshots.
