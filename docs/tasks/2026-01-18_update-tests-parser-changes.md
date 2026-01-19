# Task: Update tests for parser JSON schema changes

## Goal / Acceptance Criteria
- `docker compose exec -T api pytest -q` passes.
- Tests reflect the current Value Line parser/page JSON output schema.
- No changes to production parsing logic unless required to fix a test defect.

## Scope
### In Scope
- Update unit tests and fixtures that assert the Value Line page JSON shape.
- Regenerate diff fixtures if used by tests.

### Out of Scope
- Parser feature changes.
- Database writes / migrations.
- UI changes.

## PRD References
- Value Line Template Fields
- Data lineage requirements

## Files To Change
- `backend/tests/unit/*.py`
- `backend/tests/fixtures/value_line/*.diff.json` (if re-generated)
- `docs/tasks/2026-01-18_update-tests-parser-changes.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q`

## Execution Plan (Approved)
1. Run the full test suite to capture current failures.
2. Map each failure to the updated parser/page JSON schema and adjust test assertions.
3. Re-run failing tests until green, then run the full suite.
4. Record verification results and any fixture regenerations in this task log.

## Current Failures
- `tests/unit/test_value_line_annual_facts.py` expects legacy `tables_time_series` in the fixture.
- `tests/unit/test_value_line_axs_parser.py` expects legacy `header_ratings`, `financial_snapshot_blocks`, and `tables_time_series`.
- `tests/unit/test_value_line_smith_null_sections.py` expects legacy `financial_snapshot_blocks` and `tables_time_series`.

## Rollback Strategy
- Revert test changes and regenerated fixtures; re-run tests to confirm baseline failures.

## Notes / Decisions
- Updated tests to use the current page JSON schema (`header`, `capital_structure`, `annual_financials`, `total_return`, `historical_price_range`) instead of legacy blocks.
- Kept parser-level assertions by mapping expected JSON values to parser output where applicable.

## Verification
- `docker compose exec -T api pytest -q`
