# Clarify Historical Value Conflicts

## Goal / Acceptance Criteria
- Keep the existing current-fact selection rule unchanged: for the same stock, metric, period type, and period end date, the latest parsed report wins; older report-only years remain usable.
- Make stock summary conflict responses explicit about which value is currently used and why.
- Update the stock summary UI copy so historical restatements are understandable to users.

## Scope
- In:
  - Backend conflict metadata returned by `/api/v1/stocks/by_ticker/{ticker}`.
  - Frontend conflict display item formatting and summary card copy.
  - Focused tests for API response and display formatting.
- Out:
  - Database schema changes.
  - Changes to `metric_facts.is_current` semantics.
  - Full historical series resolver or calculated-metric input provenance.

## Files to Change
- `backend/app/services/actual_conflict_service.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/lib/actualConflicts.js`
- `frontend/lib/actualConflicts.test.js`
- `frontend/components/StockSummaryCard.tsx`

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec web node --test lib/actualConflicts.test.js`
- Broader backend/frontend tests if the focused tests reveal shared-contract risk.

## Notes
- 2026-05-04: Starting with a minimal explanation-layer change. The data selection rule remains latest-per-period with older-year backfill.
- 2026-05-04: Added explicit conflict payload metadata:
  - `selection_rule`
  - current value/report fields
  - previous value/report fields
- 2026-05-04: Updated summary copy from generic conflicts to historical value restatements, with explicit current-used and previous-report labels.
- 2026-05-04: Contract check: no schema change, no `is_current` semantic change, no screener/formula query change.

## Verification
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py::test_lookup_stock_by_ticker_returns_actual_conflicts` passed.
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` passed: 7 passed.
- `docker compose exec web node --test lib/actualConflicts.test.js` passed: 2 passed.
- `docker compose exec web npm run lint` passed.
- `docker compose exec api pytest -q` passed: 201 passed.
- `git diff --check` passed.
