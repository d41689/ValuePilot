# Task: Reingest with report-date and rating event timestamps

## Goal / Acceptance Criteria
- Clear existing parsed data so re-ingest starts from a clean state.
- Header metrics use `report_date` as `period_end_date` (data attribution time).
- Ratings metrics use `ratings.*.event.date` as `period_end_date`.
- `quality_metrics`, `target_price_18m`, and `long_term_projection` use `report_date` as `period_end_date`.
- `historical_price_range` is not written to the database.
- If `narrative.commentary_date` is missing, treat the parse as failed.

## Scope
### In Scope
- Ingestion pipeline logic for timestamp attribution and parse-failure rules.
- Data purge (parsed artifacts) per confirmed scope.
- Tests for the new attribution rules.

### Out of Scope
- Schema migrations (unless explicitly requested).
- UI changes.

## PRD References
- Data lineage requirements
- Parsing logic for Value Line v0.1

## Files To Change
- `backend/app/services/ingestion_service.py` (or relevant ingest pipeline)
- `backend/app/ingestion/*`
- `backend/tests/unit/*`
- `docs/tasks/2026-01-18_reingest-report-date-mappings.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q`

## Execution Plan (Approved)
1. Clarify purge scope (tables and rows) and implement safe purge via SQL or service-level cleanup.
2. Update ingestion logic to map period_end_date for header/ratings/quality/targets/projections per rules.
3. Skip inserting `historical_price_range` metrics.
4. Enforce parse failure when `narrative.commentary_date` is missing.
5. Add/adjust tests for these rules.
6. Run full test suite and record results.

## Clarifications
- Purge `metric_facts`, `metric_extractions`, and `pdf_documents`.
- Missing `narrative.commentary_date` should fail the page (page-level failure).

## Rollback Strategy
- Revert code changes and re-run tests.

## Notes / Decisions
- Purged `metric_facts`, `metric_extractions`, and `pdf_documents` via `TRUNCATE ... CASCADE` (document pages removed via FK).
- Report date is required; missing report date marks the page as failed.
- Derived period_end_date (header/ratings/quality/targets/projections) deactivates prior current facts without date filtering.

## Verification
- `docker compose exec -T api pytest -q`
