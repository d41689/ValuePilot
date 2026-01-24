# Task: Align lrn parser output with expected fixture

## Goal / Acceptance Criteria
- `backend/tests/fixtures/value_line/lrn_v1.parser.json` is generated from `backend/tests/fixtures/value_line/lrn.pdf` using the project parser.
- Parser output matches `backend/tests/fixtures/value_line/lrn_v1.expected.json`.
- Existing test suite remains green inside Docker.

## Scope
**In:** Parser code updates and fixture regeneration for `lrn`.
**Out:** Schema changes, PRD changes, non-Value Line templates.

## PRD References
- docs/prd/value-pilot-prd-v0.1.md (Value Line parsing scope, normalization, lineage)

## Files to Change
- TBD after analysis

## Test Plan (Docker)
- `docker compose exec api pytest -q`
- If needed: `docker compose exec api pytest -q tests/unit/test_value_line_lrn_parser_fixture.py`

## Notes / Decisions
- Task created 2026-01-24.
- Added support for Revenues-based templates (annual rates, per-share, income statement) and Quarterly Revenues blocks.
- Adjusted quarter column ordering based on detected month headers; fiscal-year end inference keeps LRN 2025 full-year as actual.
- Current Position year correction now emits a note when header years repeat.
- Normalized dividend-related null series for Revenues layouts only; updated LRN expected to align with PDF text (AllDiv’ds row is Nil).

## Status
- Plan approved 2026-01-24.
- Implementation complete.

## Verification
- `docker compose exec api pytest -q tests/unit/test_value_line_lrn_parser_fixture.py`
- `docker compose exec api pytest -q`

## Contract Gate
- metric_facts remains the only source queried by screeners (no changes).
- value_numeric normalization rules unchanged.
- No raw SQL from user input introduced.
- No eval/exec introduced.
- Lineage fields preserved in parsing output.
- is_current semantics unchanged.

## Execution Plan (Proposed)
1. Run the parser in Docker on `backend/tests/fixtures/value_line/lrn.pdf` to produce `lrn_v1.parser.json`.
2. Use `backend/scripts/json_diff.py` to diff actual vs expected and identify mismatches.
3. Add/adjust tests first to capture the mismatch (if a specific fixture test doesn’t exist, add one).
4. Update parser logic to align output with expected fixture, honoring normalization and lineage rules.
5. Re-run targeted tests and full pytest in Docker; record results and contract checks in task file.

## Contract Checks
- Metric normalization to base units for `value_numeric`.
- Lineage fields (`document_id`, `page_number`, `original_text_snippet`) preserved.
- No raw SQL or eval/exec introduced.

## Rollback Strategy
- Revert parser changes and fixture update.
