# Task: Metric facts period_type, dedupe, and text/json storage

## Goal / Acceptance Criteria
- metric_facts store Q vs FY using `period_type` (Q/FY/AS_OF) so quarterly and annual values are distinguishable.
- Dedupe within a document: no duplicate rows for the same (stock_id, metric_key, period_type, period_end_date, source_document_id).
- Text/structured facts are stored in `value_text` and/or JSONB (no longer silently empty).
- Schema updated with `value_text`, JSONB for structured values, and `source_document_id` for per-document uniqueness.
- Ingestion uses upsert to avoid duplicates and keeps `is_current` semantics intact.
- period_type semantics are explicit and consistent across metrics (Q, FY, AS_OF; EVENT/RANGE reserved).

## Scope
### In Scope
- DB migration for new columns + unique constraint.
- Model updates and ingestion adjustments.
- Tests for dedupe and period_type usage.

### Out of Scope
- UI changes.
- Re-parsing historical documents (manual reparse only).

## PRD References
- Data lineage requirements (metric_extractions immutable).
- Metric normalization rules.

## Files To Change
- `backend/alembic/versions/*` (new migration)
- `backend/app/models/facts.py`
- `backend/app/services/ingestion_service.py`
- `backend/tests/unit/*`
- `docs/tasks/2026-01-20_metric-facts-period-type-text.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q`
- `docker compose exec -T api alembic upgrade head`

## Execution Plan
1. Add migration:
   - Add `value_text` (TEXT), convert `value_json` to JSONB (or add JSONB column), add `source_document_id` FK.
   - Add unique constraint on `(stock_id, metric_key, period_type, period_end_date, source_document_id)`.
2. Update models and ingestion:
   - Set `period_type` for AS_OF metrics; keep FY/Q for time series.
   - Define period_type mapping rules:
     - Q: quarterly financials
     - FY: full-year financials
     - AS_OF: point-in-time values (ratings, prices, market cap)
     - EVENT: dated rating changes (future)
   - Store text/structured payloads in `value_text`/`value_json`.
   - Use upsert on the unique key and preserve `is_current` semantics.
   - When both annual tables and non-table FY metrics exist in the same document:
     - Prefer table-derived FY metrics.
     - Skip header/narrative FY metrics with same metric_key and year.
3. Add tests for period_type and dedupe behavior.
4. Run migrations + pytest; record results here.

## Notes / Decisions
- Dedupe is per-document only: multiple documents may legitimately produce the same `(metric_key, period_type, period_end_date)` over time.
- period_type mapping applied: Q/FY for time series, AS_OF for point-in-time metrics, EVENT for rating changes, RANGE for projections/targets.
- FY metrics from annual tables are skipped when `tables_time_series` is present to prevent duplicate facts.

## Verification
- `docker compose exec -T api alembic upgrade head`
- `docker compose exec -T api pytest -q` (56 passed)

## Contract Checks
- `metric_facts` remains the only source queried by screeners; new facts use normalized `value_numeric`.
- No raw SQL or eval introduced.
- Lineage preserved via `source_ref_id` + `source_document_id` on parsed facts.

## Rollback Strategy
- Revert migration and ingestion changes; downgrade alembic if needed.
