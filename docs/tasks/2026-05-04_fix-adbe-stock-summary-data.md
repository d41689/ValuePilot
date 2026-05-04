# Fix ADBE Stock Summary Data

## Goal / Acceptance Criteria
- `/stocks/ADBE/summary` shows valid stock summary data after the Adobe Value Line report is parsed.
- Diagnose whether the issue is API lookup, active report selection, fact mapping, or frontend rendering.
- Keep fixes generic; do not hardcode ADBE-specific values.

## Scope
- In: stock summary API/frontend and supporting data mappings as needed.
- Out: unrelated parser changes, schema/PRD changes, unrelated UI redesign.

## Files To Change
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`

## Test Plan (Docker)
- Run focused backend tests for stock summary/API behavior.
- Run frontend tests if summary formatting/rendering helpers change.
- Run `docker compose exec api pytest -q` before final handoff.

## Progress Notes
- 2026-05-04: Task opened. Investigation pending.
- 2026-05-04: Root cause found: local DB has two `ADBE` stocks. The old `ADBE/US` row has no documents/facts, while `ADBE/NDQ` has the parsed Adobe reports and metric facts. `/api/v1/stocks/by_ticker/ADBE` selected the lowest stock id, so the page rendered empty data.
- 2026-05-04: Added regression coverage for duplicate ticker lookup. The API now selects the duplicate with an active report first, then latest report date/current fact count, preserving existing lowest-id fallback for otherwise equivalent rows.
- 2026-05-04: Confirmed local ADBE lookup now returns `id=4333`, `exchange=NDQ`, active report `2654`, `price=248.63`, `pe=11.2`.
- 2026-05-04: Verification passed:
  - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py::test_lookup_stock_by_ticker_prefers_duplicate_with_active_report` -> 1 passed.
  - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` -> 7 passed.
  - `docker compose exec api pytest -q` -> 201 passed.

## Contract Checklist
- [x] Stock summary reads queryable facts from `metric_facts`, not extraction JSON.
- [x] Numeric comparisons/values use normalized `value_numeric` where applicable.
- [x] No raw SQL from user input introduced.
- [x] Parser/report-specific values are not hardcoded.
- [x] Verification recorded.
