# Task: Add single-source actual conflict detection across Value Line report versions

## Goal / Acceptance Criteria
- Detect conflicts where the same stock / metric / period has different `actual` parsed values across different Value Line documents.
- Expose conflict metadata in `/api/v1/stocks/by_ticker/{ticker}`.
- Ignore non-actual facts and same-value repetitions.

## Scope
**In**
- Backend conflict detection helper/service.
- Stock-by-ticker response additions for conflict count and details.
- Targeted backend tests using synthetic same-stock multi-document data.

**Out**
- New schema.
- Frontend conflict UI.
- Cross-source conflict resolution.
- Automatic conflict adjudication.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> lineage, normalized facts, auditability
- `AGENTS.md` -> Docker-only verification, task logging

## Files To Change
- `docs/tasks/2026-04-22_actual-conflict-detector-v1.md` (this file)
- `backend/app/services/actual_conflict_service.py`
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`

## Execution Plan (Assumed approved per direct request)
1. Add failing tests for single-source cross-report actual conflicts.
2. Implement conflict detection helper.
3. Wire conflict summary into stock-by-ticker payload.
4. Run Docker verification and record results.

## Contract Checks
- Only parsed facts participate.
- Only `fact_nature = actual` participates.
- Grouping key is `stock_id + metric_key + period_type + period_end_date`.
- No schema changes.

## Rollback Strategy
- Revert conflict helper and stock API payload additions.

## Progress Log
- [x] Add failing tests.
- [x] Implement conflict helper and API wiring.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Current fixtures do not include multiple reports for the same ticker, so this step uses synthetic test setup.
- Conflict detection is intentionally limited to `source_type='parsed'` and `fact_nature='actual'`.
- Same-value repetitions across different report versions are treated as non-conflicts.
- API exposure is additive on `/api/v1/stocks/by_ticker/{ticker}` via `actual_conflict_count` and `actual_conflicts`.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
  - `5 passed in 0.10s`
- `docker compose exec api pytest -q`
  - `120 passed in 20.55s`
