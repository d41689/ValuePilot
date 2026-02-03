# 2026-02-03 Market Data Provider Fallback (V1)

## Goal / Acceptance Criteria

- Add env-driven primary/secondary market data providers with fallback behavior.
- Support `twelvedata` (API key) and `yfinance` (best-effort) providers.
- Preserve existing service semantics: empty provider results still return `provider_no_data`.
- No DB schema changes.

## Scope

### In Scope
- Provider implementations and selection logic inside `backend/app/services/market_data_service.py`.
- Fallback logic: primary first, secondary for missing symbols.
- Minimal fixes for real-world provider pitfalls (timezone handling, response shape compatibility).

### Out of Scope
- New API endpoints or UI changes.
- Migrations or schema changes.
- Production-grade exchange calendar handling.

## Files To Change

- `backend/app/services/market_data_service.py`

## Test Plan (Docker)

- `docker compose exec api pytest -q tests/unit/test_market_data_refresh.py`

## Progress Update

- 2026-02-03: Implemented provider selection + fallback; tests passed (`docker compose exec api pytest -q tests/unit/test_market_data_refresh.py`).
