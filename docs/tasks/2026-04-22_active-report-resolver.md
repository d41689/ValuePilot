# Task: Add active report resolver semantics for Value Line documents

## Goal / Acceptance Criteria
- Define an explicit active parsed report for each stock without adding schema.
- Expose active-report semantics to backend consumers so the current report is not only implicit in `metric_facts.is_current`.
- Default active report selection must be deterministic: latest `report_date`, tie-break by higher document id.

## Scope
**In**
- Resolver/helper for active parsed report selection.
- Backend API responses that benefit directly from active-report metadata:
  - `/api/v1/documents`
  - `/api/v1/stocks/by_ticker/{ticker}`
- Targeted tests for resolver-driven behavior.

**Out**
- Manual promote/override actions.
- New database tables or columns.
- Frontend changes beyond consuming existing API fields.
- Multi-source resolver logic beyond current Value Line parsed documents.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> lineage, audit trail, normalized fact consumption
- `AGENTS.md` -> Docker verification, task logging, minimal safe implementation

## Files To Change
- `docs/tasks/2026-04-22_active-report-resolver.md` (this file)
- `backend/app/services/active_report_resolver.py`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/app/api/v1/endpoints/stocks.py`
- Targeted backend tests

## Execution Plan (Assumed approved per direct request)
1. Add failing tests for active report metadata.
2. Implement active report resolver helper.
3. Wire resolver into document list and stock-by-ticker responses.
4. Run Docker verification and record results.

## Contract Checks
- No schema changes.
- Resolver uses document metadata already persisted in `pdf_documents`.
- Existing `metric_facts` read paths continue to work; this step adds explicit report metadata, not a new fact store.

## Rollback Strategy
- Revert resolver helper and API response field additions.

## Progress Log
- [x] Add failing tests.
- [x] Implement resolver + API response wiring.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Active report is defined per stock across parsed documents visible in the current workspace.
- The first consumer contract will be metadata only: `is_active_report`, `active_report_document_id`, and related dates.
- Resolver is based on parsed-document participation in `metric_facts` (`source_type='parsed'` and `source_document_id` set), not just `pdf_documents.stock_id`, so multi-company container documents are handled correctly.
- Documents list exposes active-report semantics as `is_active_report` plus `active_for_tickers`, since one document can be active for multiple stocks.
- Stock-by-ticker exposes `active_report_document_id` and `active_report_date`.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_documents_api.py tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec api pytest -q`
- Result: `119 passed in 18.75s`
