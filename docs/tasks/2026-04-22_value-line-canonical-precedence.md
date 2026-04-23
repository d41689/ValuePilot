# Task: Add Value Line parsed document precedence for canonical facts

## Goal / Acceptance Criteria
- Prevent an older Value Line document reparse from taking over `is_current=True` parsed facts when a newer report already exists for the same stock/metric/period.
- Keep parsed fact precedence deterministic across multiple Value Line documents for the same stock.
- Preserve current manual fact behavior and avoid schema changes.

## Scope
**In**
- Parsed-fact precedence rules inside ingestion/service write path.
- Targeted backend tests for multi-document precedence.
- Minimal helper logic needed to compare parsed document recency.

**Out**
- New tables or schema changes.
- UI changes.
- Multi-source precedence beyond Value Line parsed documents.
- Manual fact precedence changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> audit trail, normalized facts, Value Line scope
- `AGENTS.md` -> task logging, Docker-only verification, `metric_facts` as source of truth

## Files To Change
- `docs/tasks/2026-04-22_value-line-canonical-precedence.md` (this file)
- `backend/app/services/ingestion_service.py`
- `backend/tests/unit/test_reparse_existing_document.py`
- Minimal helper/service files only if needed

## Execution Plan (Assumed approved per direct request)
1. Add failing tests that encode parsed document precedence.
2. Implement precedence helper in ingestion write path.
3. Verify reparse behavior and full backend tests in Docker.

## Contract Checks
- `metric_facts` remains the only canonical query source.
- No schema changes.
- Manual facts are not deactivated by parsed-document precedence logic.
- Parsed-fact precedence uses document metadata already stored in `pdf_documents`.

## Rollback Strategy
- Revert precedence helper changes and targeted tests.

## Progress Log
- [x] Add failing tests.
- [x] Implement parsed document precedence in ingestion.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Planned precedence basis: newer `pdf_documents.report_date` wins; tie-break by higher document id.
- This step is scoped to parsed facts competing with other parsed facts on the same stock/metric/period slot.
- Implementation uses a per-slot reconcile step after parsed fact upsert instead of the previous "deactivate current then insert current" flow.
- Slot definition in this step is exact match on `stock_id + metric_key + period_type + period_end_date` for `source_type='parsed'`.
- Manual facts are untouched by this reconcile logic.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec api pytest -q`
- Result: `117 passed in 19.33s`
