# Task: Add provenance metadata to stock and DCF API responses

## Goal / Acceptance Criteria
- Expose source metadata for current stock/DCF values returned by `/api/v1/stocks/by_ticker/{ticker}`.
- Provenance must at least identify parsed document lineage when available:
  - `source_type`
  - `source_document_id`
  - `source_report_date`
  - `period_end_date`
  - whether the source document is the active report
- Existing numeric fields must remain backward-compatible.

## Scope
**In**
- Backend response metadata for stock summary values and DCF inputs/series.
- Targeted backend tests.

**Out**
- Frontend rendering changes.
- New schema.
- Multi-source conflict resolution changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> lineage, normalized facts, auditability
- `AGENTS.md` -> Docker-only verification, source-of-truth contracts

## Files To Change
- `docs/tasks/2026-04-22_stock-api-provenance-metadata.md` (this file)
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`

## Execution Plan (Assumed approved per direct request)
1. Add failing tests for provenance fields on stock-by-ticker payload.
2. Implement minimal provenance helpers and response wiring.
3. Run Docker verification and record results.

## Contract Checks
- Existing value fields stay intact.
- Provenance metadata is additive.
- Lineage is derived from persisted `metric_facts` and `pdf_documents` only.

## Rollback Strategy
- Revert payload field additions and tests.

## Progress Log
- [x] Add failing tests.
- [x] Implement provenance helpers and payload wiring.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Planned scope: top-level summary metrics, OEPS series, DCF current inputs, DCF input series, and growth rate options.
- Provenance is additive and leaves existing numeric fields unchanged.
- For computed `depreciation_per_share`, provenance is expressed as `inputs`, since the displayed value depends on both depreciation and shares outstanding facts.
- When a parsed fact has no `source_document_id`, provenance still carries `source_type` and `period_end_date`, with document fields left `null`.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec api pytest -q`
- Result: `119 passed in 19.47s`
