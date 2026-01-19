# Task: Align AO Smith parser JSON with expected fixture

## Goal / Acceptance Criteria
- `backend/tests/fixtures/value_line/ao_smith_v1.parser.json` is JSON-equal to `backend/tests/fixtures/value_line/ao_smith_v1.expected.json` after stable formatting.
- `backend/tests/fixtures/value_line/ao_smith_v1.diff.json` must be empty (no mismatches).
- `financial_snapshot_blocks.capital_structure`:
  - Emits only fields present in the AO Smith report.
  - Uses the key `lt_interest_percent_of_capital` (not legacy variants).
- Exactly one of `current_position` or `financial_position` is present:
  - If the report page contains a “CURRENT POSITION ($MILL.)” table → populate `current_position` and omit `financial_position`.
  - If the report page contains a “FINANCIAL POSITION” table → populate `financial_position` and omit `current_position`.
- `annual_financials` must match the expected fixture’s metric set exactly (no extra or missing keys).
- Optional blocks/fields must follow the expected fixture semantics exactly (omit vs `null`).
- `narrative.business` and `narrative.analyst_commentary` are not parsed and must match expected fixture behavior (omitted or null as specified).

## Report Modules Expected (AO Smith)
- Header / Identity
- Ratings and Quality Metrics
- Capital Structure (including leases, pension assets/obligations, dual-class share notes if present)
- Current Position (not Financial Position)
- Annual Financials and Ratios (industrial company template only)
- Total Return
- Narrative sections are intentionally excluded

## Scope
### In Scope
- Parser adjustments and JSON builder updates to match the AO Smith expected fixture.
- Regenerate `ao_smith_v1.parser.json` via Docker.
- Diff output using `backend/scripts/json_diff.py`.

### Out of Scope
- Database writes / metric_facts population.
- Schema migrations.
- UI changes.
- Schema changes (`value_line_page_v1.schema.json` remains unchanged).

## PRD References
- Value Line Template Fields
- Data lineage requirements

## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/ingestion/parsers/v1_value_line/page_json.py`
- `backend/tests/fixtures/value_line/ao_smith_v1.parser.json`
- `backend/tests/fixtures/value_line/ao_smith_v1.diff.json`
- `docs/tasks/2026-01-18_ao-smith-parser-align.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q tests/unit/test_value_line_parser_fixture.py`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/value_line_dump_axs.py --pdf "tests/fixtures/value_line/smith ao.pdf" --out tests/fixtures/value_line/ao_smith_v1.parser.json'`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/json_diff.py tests/fixtures/value_line/ao_smith_v1.expected.json tests/fixtures/value_line/ao_smith_v1.parser.json tests/fixtures/value_line/ao_smith_v1.diff.json'`

## Debug Checklist
- Run parser dump and quickly inspect `ao_smith_v1.parser.json` for missing or extra blocks.
- Run `json_diff.py` and prioritize mismatches by JSON path.
- Verify numeric scaling ($mill vs per-share), percent normalization, and negative values.
- Confirm `as_of` dates and quarter-end mappings align with the report.

## Execution Plan (Approved)
1. Generate a diff between AO Smith expected and parser JSON to identify mismatches.
2. Update parser extraction or JSON assembly logic for the requested modules.
3. Regenerate `ao_smith_v1.parser.json` from the parser output in Docker.
4. Re-run the diff to confirm zero mismatches.
5. Run targeted unit tests and record results here.

## Rollback Strategy
- Revert parser/JSON changes and regenerated fixtures; re-run the diff to confirm baseline behavior.

## Notes / Decisions
- Added insurance vs industrial layout detection to drive annual rates, annual financials, quarterly table naming, and price history year alignment.
- Capital structure now emits only present fields; renamed `% of capital` to `lt_interest_percent_of_capital`, added leases/pension/obligations, and normalized common stock metadata.
- Current position table maps to `current_position` periods with explicit period_end_date labels.
- Narrative business/commentary output suppressed when the extracted text contains table artifacts.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_value_line_parser_fixture.py tests/unit/test_value_line_axs_parser_time_fields.py`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/value_line_dump_axs.py --pdf "tests/fixtures/value_line/smith ao.pdf" --out tests/fixtures/value_line/ao_smith_v1.parser.json'`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/json_diff.py tests/fixtures/value_line/ao_smith_v1.expected.json tests/fixtures/value_line/ao_smith_v1.parser.json tests/fixtures/value_line/ao_smith_v1.diff.json'`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/value_line_dump_axs.py --pdf "tests/fixtures/value_line/axs.pdf" --out tests/fixtures/value_line/axs_v1.parser.json'`
- `docker compose exec -T api sh -lc 'PYTHONPATH=/code python scripts/json_diff.py tests/fixtures/value_line/axs_v1.expected.json tests/fixtures/value_line/axs_v1.parser.json tests/fixtures/value_line/axs_v1.diff.json'`

## Contract Check
- Screeners still read `metric_facts` only; no changes to querying logic.
- No raw SQL or eval/exec added.
- Lineage fields unchanged (parser/JSON-only changes).
