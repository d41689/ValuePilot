# Task: Align AXS parser output with new expected format (phase 1)

## Goal / Acceptance Criteria
- Parser output JSON matches `backend/tests/fixtures/value_line/axs_v1.expected.json` (phase 1 only).
- `meta.report_date` is parsed and present.
- Parsed output includes time/period fields where required by the new expected format.
- Generate a new `backend/tests/fixtures/value_line/axs_v1.parser.json` from parser output.
- Produce a diff JSON using `backend/scripts/json_diff.py` and confirm remaining mismatches.
- `meta.report_date` parsing is deterministic (ISO `YYYY-MM-DD`) and derived from the Value Line report header date (not file upload time).
- No duplicate top-level keys are emitted in the parser JSON (guarded by fixture diff).
- `annual_financials.meta.historical_years` covers the full continuous historical range present in the specific Value Line report (range is report-dependent, e.g., 2015–2026 for a 2026 report, or 2013–2024 for a 2024 report), and projections are kept exclusively in projection_year_range (not split into multiple blocks).

## Scope
### In Scope
- Parser updates to emit time-aware fields (report_date, period_end_date/as_of where required by expected JSON).
- Tests that validate the time-aware fields in the new expected JSON.
- Regenerating `axs_v1.parser.json` and `axs_v1.diff.json` for comparison.
- Updating/normalizing the AXS JSON module structure to match value_line_page_v1.schema.json where time fields are required (without adding new modules).

### Out of Scope
- Writing metric_facts to the database (phase 2).
- Schema migrations.
- UI changes.

## PRD References
- B.4.1 Value Line Template Fields (report_date)
- Tables (time series) and Financial snapshot blocks (time-aware fields)
- Data Modeling & Storage (period_end_date / as_of_date)


## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/ingestion/parsers/v1_value_line/page_json.py`
- `backend/scripts/value_line_dump_axs.py`
- `backend/tests/unit/test_value_line_axs_parser_time_fields.py` (new)
- `backend/tests/fixtures/value_line/axs_v1.parser.json`
- `backend/tests/fixtures/value_line/axs_v1.diff.json`
- `docs/tasks/2026-01-18_axs-parser-report-date.md`

## Environment / How to Run Commands (Docker Compose)
This repo runs via Docker Compose. All test and script commands below should be executed inside the correct service container.

- API container: `docker compose exec -T api <command>`
- If you need a shell: `docker compose exec api sh`

Notes:
- Prefer `-T` for non-interactive CI-style runs.
- When regenerating fixtures, run the generator scripts inside the `api` container so paths and deps are consistent.

## Test Plan (Docker)
- `docker compose exec -T api pytest -q tests/unit/test_value_line_axs_parser_time_fields.py`
- `docker compose exec -T api pytest -q`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/value_line_dump_axs.py --out tests/fixtures/value_line/axs_v1.parser.json'`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/json_diff.py tests/fixtures/value_line/axs_v1.expected.json tests/fixtures/value_line/axs_v1.parser.json tests/fixtures/value_line/axs_v1.diff.json'`

## Execution Plan (Approved)
1. Create/adjust unit tests to assert all required time fields per `axs_v1.expected.json`:
   - `meta.report_date`
   - any `period_end_date` / `as_of` fields required by snapshot/time-series blocks
2. Update the parser to emit the required time fields and normalize module shapes per schema.
3. Run the unit test file only until green.
4. Regenerate `axs_v1.parser.json` from the real parser output (inside Docker).
5. Generate `axs_v1.diff.json` using `backend/scripts/json_diff.py` and verify remaining mismatches are expected/intentional.
6. Run full unit test suite in Docker and record results in this task log.

## Progress Notes
- Added a page JSON builder (`build_value_line_page_json`) to assemble the time-aware page payload.
- Extended annual rates parsing to cover insurance-specific rows (premium/investment income) and handle non-numeric tokens.
- Expanded quarterly parsing to support NET PREMIUMS EARNED and negative/annotated values.
- Normalized narrative extraction with word-layout parsing and post-processing to match expected prose.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_value_line_axs_parser_time_fields.py`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/value_line_dump_axs.py --out tests/fixtures/value_line/axs_v1.parser.json'`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/json_diff.py tests/fixtures/value_line/axs_v1.expected.json tests/fixtures/value_line/axs_v1.parser.json tests/fixtures/value_line/axs_v1.diff.json'`

Result:
- `tests/fixtures/value_line/axs_v1.diff.json` is empty (no mismatches).

## Rollback Strategy
- Revert parser/test changes and regenerated fixtures; re-run the same tests to confirm baseline behavior.

## Notes / Common Failure Modes
- If `report_date` is missing or ambiguous in the PDF text layer, fail fast in the unit test with a clear assertion message.
- If `json_diff` shows large, noisy diffs, check for accidental key renames or duplicated top-level keys in emitted JSON.
- If a time-series metric is missing `period_end_date`, ensure the extractor attaches it at extraction time (not later in fact materialization).

- Do not hard-code historical year ranges. The parser must infer the start and end years dynamically from the report content; unit tests should assert continuity, not specific calendar years.
