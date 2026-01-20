# Task: Fix metric_facts mapping for ratings/as-of/time-series/commentary/projection range

## Goal / Acceptance Criteria
- Ratings facts (`timeliness`, `safety`, `technical`) use `event.date` as `period_end_date`.
- Capital structure metrics use the correct `as_of` dates:
  - `capital_structure_as_of` for debt/interest/preferred/obligations.
  - `pension_assets_as_of` for `pension_assets`.
  - `market_cap_as_of` for `market_cap`.
  - `common_stock_shares_outstanding` uses its own `as_of`.
- Time series tables are expanded into per-period metric_facts with proper `period_end_date` and normalized `value_numeric`:
  - quarterly sales / earnings per share / quarterly dividends
  - financial position table
  - annual_financials (historical years)
- `analyst_commentary` is stored as non-numeric (no `value_numeric`).
- `long_term_projection_year_range` is stored as non-numeric text (no numeric truncation).

## Scope
### In Scope
- Ingestion pipeline mapping logic for the above.
- New/updated tests covering the mapping rules.

### Out of Scope
- Schema migrations.
- UI changes.

## PRD References
- Data lineage requirements
- Metric normalization rules

## Files To Change
- `backend/app/services/ingestion_service.py`
- `backend/tests/unit/*`
- `docs/tasks/2026-01-19_fix-facts-mapping.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q`

## Execution Plan
1. Add tests to assert:
   - ratings period_end_date uses event.date
   - capital_structure metrics use correct as_of dates
   - time series expansion creates per-period facts with correct normalization
   - analyst_commentary is non-numeric
   - long_term_projection_year_range is non-numeric
2. Implement mapping changes in ingestion_service:
   - derive period_end_date for ratings and capital_structure fields
   - expand time series from parsed tables into MetricFact rows
   - mark analyst_commentary + projection range as non-numeric
3. Run pytest and iterate until green.
4. Record verification results in this task file.

## Notes / Decisions
- Time-series extractions write per-period facts; base metric_fact rows for table carriers are skipped to avoid null `value_numeric` rows.
- Annual financials map USD millions to `*_usd_millions` keys and normalize percent/ratio fields per table layout.

## Verification
- `docker compose exec -T api pytest -q` (55 passed)

## Contract Checks
- `metric_facts` remains the source of truth for screeners; new facts use normalized `value_numeric`.
- No raw SQL or eval introduced.
- Lineage preserved via `source_ref_id` for derived facts.

## Rollback Strategy
- Revert mapping/test changes and re-run tests.
