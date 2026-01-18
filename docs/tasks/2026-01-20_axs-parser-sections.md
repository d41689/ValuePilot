# Task: Extract AXS sections for recent price, tables, snapshot, and returns

## Goal / Acceptance Criteria
- Parser extracts:
  - `header_ratings.recent_price` (RECENT PRICE).
  - `tables_time_series` (core time series tables for AXS).
  - `financial_snapshot_blocks.capital_structure_as_of` (CAPITAL STRUCTURE as of ...).
  - `financial_snapshot_blocks.capital_structure.preferred_stock`.
  - `financial_snapshot_blocks.capital_structure.preferred_dividend`.
  - `financial_snapshot_blocks.capital_structure.common_stock_shares_outstanding`.
  - `financial_snapshot_blocks.financial_position_usd_millions` (FINANCIAL POSITION block).
  - `price_semantics_and_returns` (% TOT. RETURN block).
- Generate a new `backend/tests/fixtures/value_line/axs_v1.parser.json` for comparison.

## Scope
### In Scope
- Regex/table parsing updates in the ValueLine parser.
- Unit tests covering the above extractions using the AXS fixture.

### Out of Scope
- UI changes.
- Schema migrations.

## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/tests/unit/test_value_line_parser_fixture.py` (or a new AXS-focused test)
- `backend/tests/fixtures/value_line/axs_v1.parser.json`
- `docs/tasks/2026-01-20_axs-parser-sections.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q tests/unit/test_value_line_parser_fixture.py`
- `docker compose exec -T api pytest -q`

## Execution Plan
1. Add unit tests for AXS fixture to cover recent price, capital structure fields, financial position, price returns, and time series.
2. Extend ValueLine parser:
   - Word-based extraction for `RECENT` price.
   - Capital structure `as of`, preferred stock/dividend, and common shares.
   - Financial position block parsing.
   - `% TOT. RETURN` block parsing from words.
   - Time series parsing (price history + annual financials/ratios + projections).
3. Update ingestion non-numeric keys for new JSON metric outputs.
4. Re-run tests in Docker and regenerate `axs_v1.parser.json`.

## Rollback Strategy
- Revert parser/test changes and remove `axs_v1.parser.json` if extraction quality regresses.

## Notes / Decisions
- Added word-based parsing for `RECENT` price and `% TOT. RETURN`.
- Added structured extraction for capital structure (as-of, preferred stock/dividend, common shares) and financial position block.
- Added time series extraction covering price history and annual financials/ratios, with projection values.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_value_line_axs_parser.py`
- `docker compose exec -T api pytest -q`
- Results: 41 passed, 1 warning (FastAPI deprecation).
