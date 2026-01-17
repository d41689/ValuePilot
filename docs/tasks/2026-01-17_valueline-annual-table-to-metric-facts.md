# Task: Value Line Annual Table -> Metric Facts (Latest Actual FY)

## Goal / Acceptance Criteria
- Parse Value Line V1 annual table rows for:
  - `net_profit_usd_millions`
  - `depreciation_usd_millions`
  - `capital_spending_per_share_usd`
  - `avg_annual_dividend_yield_pct`
  - `company_financial_strength`
  - `stock_price_stability`
  - `price_growth_persistence`
  - `earnings_predictability`
  - `safety` (if missing)
- Write `metric_facts` with:
  - `period_type = FY`
  - `period_end_date = YYYY-12-31`
  - `value_numeric` normalized to base units
  - `value_json.is_estimate` set for estimated year values
- Screener defaults to Latest Actual FY by filtering out `is_estimate = true` in SQL.
- Reparse existing documents to backfill facts after code changes.

## Scope
- In scope:
  - ValueLineV1Parser regex expansion for annual table + header ratings.
  - Ingestion normalization updates to set FY period fields and is_estimate metadata.
  - Screener query filter to exclude estimated facts by default.
  - Tests (fixture parsing + metric_facts assertions).
- Out of scope:
  - Schema migrations.
  - UI changes.
  - Parsing non-Value Line templates.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md`:
  - Parsing boundary (Value Line V1 only)
  - Normalization (V1) + Appendix B
  - `metric_facts` period fields + `is_current` semantics
  - Screeners MUST use `metric_facts.value_numeric`

## Files to change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/ingestion/normalization/scaler.py`
- `backend/app/services/screener_service.py`
- `backend/tests/unit/test_value_line_parser_fixture.py`
- `backend/tests/unit/test_ingestion.py`
- `backend/tests/unit/test_value_line_annual_facts.py`

## Plan
1. Add failing tests for new annual metrics + header ratings and metric_facts period/is_estimate fields.
2. Extend ValueLineV1Parser to extract annual table rows + ratings.
3. Update normalization and ingestion to set FY period fields and preserve is_estimate.
4. Update screener query to exclude estimated facts by default.
5. Run tests in Docker; update task notes with results.
6. Reparse existing documents via API to backfill facts.

## Rollback Strategy
- Revert parser/ingestion/screener changes and remove new tests if failures cannot be resolved.

## Test Plan (Docker)
- `docker compose exec api pytest -q tests/unit/test_value_line_parser_fixture.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_annual_facts.py`
- `docker compose exec api pytest -q tests/unit/test_ingestion.py`
- `docker compose exec api pytest -q`

## Notes / Decisions
- Latest Actual FY is the default for screener; estimated year facts are stored with `value_json.is_estimate = true`.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_value_line_parser_fixture.py`
- `docker compose exec -T api pytest -q tests/unit/test_value_line_annual_facts.py`
- `docker compose exec -T api pytest -q tests/unit/test_ingestion.py`
- `docker compose exec -T api pytest -q`

## Reparse
- Reparsed documents 11 and 12 for user_id 1 with `reextract_pdf=True` via `IngestionService` (API not running on localhost).
- Skipped document 71 (multi-page) pending multi-page reparse behavior updates.
