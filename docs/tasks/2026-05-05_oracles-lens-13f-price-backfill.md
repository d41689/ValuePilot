# Oracle's Lens 13F Price Backfill

## Goal / Acceptance Criteria

- Add a controlled EOD price backfill path for 13F-linked stocks.
- Backfill targets distinct linked `stock_id` + 13F period pairs.
- Period-end dates that fall on weekends use the most recent prior business day.
- Existing `stock_prices` rows are not duplicated.
- Provider failures are reported per stock/date without aborting the full backfill.
- Implementation uses the existing market-data provider abstraction and is testable without network calls.

## Scope

In:
- `MarketDataService` backfill method.
- Unit tests with fake provider.
- Optional script entrypoint for Docker-run backfill.

Out:
- New provider integration.
- Scheduler/automation.
- Schema changes.
- Frontend changes.

## Files To Change

- `backend/app/services/market_data_service.py`
- `backend/tests/unit/test_market_data_refresh.py`
- `backend/scripts/backfill_13f_period_prices.py`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_market_data_refresh.py`
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec api pytest -q`

## Notes

- This service may call configured providers when run manually, but tests must use fake providers.
- The script should be explicit and opt-in; no automatic network calls during dashboard rendering.

## Implementation Notes

- Added `MarketDataService.backfill_13f_linked_period_prices`.
- Backfill query targets distinct linked stocks from latest 13F filings with confirmed CIK-backed managers.
- Default scope is superinvestors only; callers can opt into all managers.
- Weekend 13F period dates map to the most recent prior business day.
- Existing `stock_prices` rows for the target stock/date are skipped.
- Provider failures are returned per stock/date as `failed`.
- Added `backend/scripts/backfill_13f_period_prices.py` as an explicit Docker-run entrypoint.

Example:

```bash
docker compose exec api python -m scripts.backfill_13f_period_prices --period 2024-03-31 --limit 50
```

## Verification

- `docker compose exec api pytest -q tests/unit/test_market_data_refresh.py::test_backfill_13f_linked_period_prices_skips_existing_and_uses_period_business_day tests/unit/test_market_data_refresh.py::test_backfill_13f_linked_period_prices_excludes_non_superinvestors_by_default` - 2 passed
- `docker compose exec api pytest -q tests/unit/test_market_data_refresh.py` - 8 passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 6 passed
- `docker compose exec api python -m scripts.backfill_13f_period_prices --help` - passed
- `docker compose exec api pytest -q` - 209 passed
- `git diff --check` - passed

## Contract Checklist

- [x] Dashboard rendering does not trigger provider/network calls.
- [x] Backfill is explicit and opt-in.
- [x] Stored prices use existing `stock_prices` table.
- [x] No schema migration.
- [x] No raw SQL from user input.
