# Stock Identity Market Country

## Goal / Acceptance Criteria

- Make stock identity use `ticker + market_country` instead of `ticker + source-specific exchange`.
- Preserve specific listing exchange metadata from sources like Value Line without splitting stock identity.
- Ensure Value Line `GOOG / NDQ` resolves to the existing 13F `GOOG / US` stock.
- Repair existing duplicate stock rows that only differ by US-listed exchange aliases where safe.

## Scope

In:
- Stock model and migration for `market_country`, `listing_exchange`, and `raw_exchange`.
- Identity resolution normalization for Value Line report ingestion.
- 13F/CUSIP stock creation and holding backfill alignment with `market_country`.
- Unit tests for identity normalization and duplicate repair behavior.

Out:
- Paid or network-dependent exchange backfill integrations.
- Broad security master redesign beyond the stock identity columns.
- UI redesign.

## Files to Change

- `backend/app/models/stocks.py`
- `backend/app/core/stock_identity.py`
- `backend/app/services/identity_service.py`
- `backend/app/services/cusip_enrichment.py`
- `backend/alembic/versions/*`
- Relevant backend unit tests.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_stock_identity_market_country.py`
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q`
- `git diff --check`

## Progress Notes

- 2026-05-06: Started after Google Value Line upload created `GOOG/NDQ` while 13F holdings use `GOOG/US`.
- 2026-05-06: Added `market_country`, `listing_exchange`, and `raw_exchange` to `stocks`.
- 2026-05-06: Added `stock_identity` normalization so US-listed exchange aliases map to `market_country=US`, while specific exchanges remain display/listing metadata.
- 2026-05-06: Updated `IdentityService` so Value Line `GOOG/NDQ` reuses existing `GOOG/US` by `ticker + market_country`.
- 2026-05-06: Updated 13F/CUSIP stock bootstrap and holding backfill to target `market_country=US`.
- 2026-05-06: Migration safely moved duplicate stock references to canonical active stocks and deactivated duplicates.
- 2026-05-06: Confirmed local `google.pdf` now points to canonical `GOOG` stock and Oracle's Lens shows Value Line coverage/provenance for `GOOG`.

## Verification

- `docker compose exec api alembic upgrade head` - passed.
- `docker compose exec api pytest -q tests/unit/test_stock_identity_market_country.py` - passed.
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` - passed.
- `docker compose exec api pytest -q tests/unit/test_documents_api.py` - passed.
- `docker compose exec api pytest -q tests/unit/test_stock_pools_api.py` - passed.
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - passed.
- `docker compose exec api pytest -q` - passed, 211 tests.
- `git diff --check` - passed.
