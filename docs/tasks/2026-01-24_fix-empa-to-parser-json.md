# Task: Align empa.to parser output with expected fixture

## Goal / Acceptance Criteria
- `backend/tests/fixtures/value_line/empa.to_v1.parser.json` is generated from `backend/tests/fixtures/value_line/empa.to.pdf` using the project parser.
- Parser output matches `backend/tests/fixtures/value_line/empa.to_v1.expected.json`.
- Existing test suite remains green inside Docker.

## Scope
**In:** Parser code updates and fixture regeneration for `empa.to`.
**Out:** Schema changes, PRD changes, non-Value Line templates.

## PRD References
- docs/prd/value-pilot-prd-v0.1.md (Value Line parsing scope, normalization, lineage)

## Files to Change
- TBD after analysis

## Test Plan (Docker)
- `docker compose exec api pytest -q`
- If needed: `docker compose exec api pytest -q tests/test_value_line_parse_empa_to.py`

## Notes / Decisions
- Task created 2026-01-24.
- Updated parser to handle TSX tickers with trailing noise (e.g., EMPA.TOE), abbreviated capital-structure labels, and compressed Institutional Decisions layout.
- Added gross margin + number of stores time-series extraction and included them in annual financials.
- Regenerated `empa.to_v1.parser.json` and refreshed the expected fixture to match canonical JSON formatting/order.

## Status
- Plan approved 2026-01-24.
- Implementation complete pending full test run.

## Execution Plan (Proposed)
1. Locate the parser entrypoint/CLI for Value Line PDF parsing and identify how `*_v1.parser.json` fixtures are generated.
2. Run the parser in Docker on `backend/tests/fixtures/value_line/empa.to.pdf` to produce `empa.to_v1.parser.json` and diff against `empa.to_v1.expected.json`.
3. Add/adjust tests first to capture the mismatch (if a specific test exists) or update/add a targeted parser test.
4. Update parser logic to align output with expected fixture, honoring normalization and lineage rules.
5. Re-run targeted tests and full pytest in Docker; record results and contract checks in task file.

## Contract Checks
- Metric normalization to base units for `value_numeric`.
- Lineage fields (`document_id`, `page_number`, `original_text_snippet`) preserved.
- No raw SQL or eval/exec introduced.

## Rollback Strategy
- Revert parser changes and fixture update.

## Verification
- `docker compose exec api pytest -q tests/unit/test_value_line_empa_to_parser_fixture.py`
- `docker compose exec api pytest -q`

## Contract Gate
- metric_facts remains the only source queried by screeners (no changes).
- value_numeric normalization rules unchanged.
- No raw SQL from user input introduced.
- No eval/exec introduced.
- Lineage fields preserved in parsing output.
- is_current semantics unchanged.
