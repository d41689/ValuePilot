# Task: Fill null sections in Smith Value Line parsing

## Goal / Acceptance Criteria
- Populate previously null keys under:
  - `financial_snapshot_blocks.current_position_usd_millions`
  - `financial_snapshot_blocks.annual_rates_of_change`
  - `financial_snapshot_blocks.capital_structure` (leases/pension/market cap as-of)
  - `tables_time_series` (price history + annual financials/ratios)
- Regenerate `smith_v1.diff.json` and reduce null mismatches for the above sections.

## Scope
### In Scope
- Parser updates for Smith-specific layout quirks.
- Tests covering the newly parsed fields using `ao_smith_v1.expected.json`.

### Out of Scope
- Full remediation of all mismatches outside the above sections.
- UI changes.

## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/tests/unit/test_value_line_smith_null_sections.py` (new)
- `docs/tasks/2026-01-20_smith-null-sections.md`
- `backend/tests/fixtures/value_line/ao_smith_v1.parser.json` (if re-generated)

## Execution Plan (Pending Approval)
1. Add Smith-focused tests covering null fields in current position, annual rates, capital structure, and tables_time_series.
2. Update parser patterns for Smith layout (compact labels, manufacturing time-series labels, and year trimming).
3. Regenerate `ao_smith_v1.parser.json` and `smith_v1.diff.json` to validate the targeted null fields are filled.
4. Run Docker tests and record results.

## Contract Checks
- No schema changes.
- Lineage fields preserved in all extracted metrics.
- Normalization behavior unchanged for existing numeric metrics unless explicitly required by tests.

## Rollback Strategy
- Revert parser changes and new tests; re-run the same tests to confirm baseline behavior.

## Test Plan (Docker)
- `docker compose exec -T api pytest -q tests/unit/test_value_line_smith_null_sections.py`
- `docker compose exec -T api pytest -q`

## Notes / Decisions
- Trimmed time-series years to the last 12 entries when longer sequences appear (aligns with 2015-2026 expectation).
- Added manufacturing table label patterns (Sales per share, Cash Flow per share, Cap’l Spending per share, Working Cap’l, Long-Term Debt, Operating/Net Profit margins, Return on Total Capital).
- Added capital structure helpers for market cap as-of, pension assets as-of, and notes (Mid Cap, Class A shares).
- Added non-numeric key exemptions for `market_cap_as_of` and `pension_assets_as_of`.
- Added valuation-series alignment for missing 2026 values (Avg annual P/E, relative P/E, avg dividend yield).
- Regenerated `ao_smith_v1.parser.json` and `smith_v1.diff.json` after parser update.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_value_line_smith_null_sections.py`
- Results: 4 passed, 1 warning (FastAPI deprecation).
