# Task: Align CALM parser output to expected fixture

## Goal / Acceptance Criteria
- `backend/tests/fixtures/value_line/calm_v1.parser.json` matches `calm_v1.expected.json` (diff empty).
- Parser changes are template-generic (no ticker-specific logic).
- AXS/BUD/Smith AO fixture tests pass in Docker.

## Scope
**In**
- Update Value Line v1 parser to handle CALM capital structure + long-term projection edge cases.
- Regenerate CALM parser fixture + diff.

**Out**
- Schema changes or PRD changes.
- Any ticker-specific parsing rules.

## PRD References
- Value Line template parsing boundary.
- Normalization rules for numeric fields.
- Capital structure extraction requirements.

## Files to Change (Expected)
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/tests/fixtures/value_line/calm_v1.parser.json`
- `backend/tests/fixtures/value_line/calm_v1.diff.json`

## Test Plan (Docker)
- `docker compose exec api pytest -q tests/unit/test_value_line_parser_fixture.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_bud_parser_fixture.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_axs_parser.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_axs_parser_time_fields.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_smith_null_sections.py`

## Execution Plan
1. Update parser capital-structure extraction to accept "Nil" and compact "CommonStock48.4mill.shs" patterns.
2. Update long-term projection regex to allow negative price gain percentages.
3. Regenerate CALM parser fixture + diff; verify empty diff.
4. Run AXS/BUD/Smith AO tests in Docker and record results.

## Rollback Strategy
- Revert parser changes and fixture regen if regressions occur.

## Contract Checklist (Fill During Verification)
- [ ] No schema migrations
- [ ] No ticker-specific logic added
- [ ] Parser remains Value Line v1 template-scoped
- [ ] No eval/exec or raw SQL introduced

## Verification
- `docker compose exec api pytest -q tests/unit/test_value_line_parser_fixture.py tests/unit/test_value_line_bud_parser_fixture.py tests/unit/test_value_line_axs_parser.py tests/unit/test_value_line_axs_parser_time_fields.py tests/unit/test_value_line_smith_null_sections.py tests/unit/test_value_line_calm_parser_fixture.py`
  - Result: **19 passed**

## Result
- `calm_v1.diff.json` is empty (parser output matches expected).
