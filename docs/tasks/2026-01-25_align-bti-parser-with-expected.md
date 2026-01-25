# Task: Align BTI parser output with expected fixture

## Goal / Acceptance Criteria
- Generate `tests/fixtures/value_line/bti_v1.parser.json` from `tests/fixtures/value_line/bti.pdf` using `scripts.value_line_dump`.
- Produce a key-by-key diff via `scripts.json_diff` against `tests/fixtures/value_line/bti_v1.expected.json`.
- Update parser-related code so the generated `bti_v1.parser.json` matches `bti_v1.expected.json`.
- All tests pass in Docker after changes.

## Scope
### In
- Parser + page-json shaping changes required to satisfy the BTI expected fixture.
- Add a regression unit test asserting BTI fixture matches expected JSON.

### Out
- Schema changes / migrations.
- PRD changes.
- Unrelated refactors.

## Files To Change (initial)
- `backend/tests/unit/test_value_line_bti_parser_fixture.py` (new)
- Parser code under `backend/app/ingestion/parsers/v1_value_line/` (as needed)
- `docs/tasks/2026-01-25_align-bti-parser-with-expected.md` (this file)

## Canonical Commands (Docker)
- Generate parser JSON:
  - `docker compose run --rm --no-deps api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/bti.pdf --out tests/fixtures/value_line/bti_v1.parser.json`
- Diff JSON by key:
  - `docker compose run --rm --no-deps api python -m scripts.json_diff tests/fixtures/value_line/bti_v1.expected.json tests/fixtures/value_line/bti_v1.parser.json tests/fixtures/value_line/bti_v1.diff.json`
- Verify tests:
  - `docker compose run --rm --no-deps api pytest -q`

## Contract Checks
- Preserve v1.1 page JSON schema shape.
- Preserve normalization semantics (percent ratios, scale tokens, etc.).

## Progress Log
- 2026-01-25: Task created.
- 2026-01-25: Generated `backend/tests/fixtures/value_line/bti_v1.parser.json` via `scripts.value_line_dump`.
- 2026-01-25: Produced `backend/tests/fixtures/value_line/bti_v1.diff.json` via `scripts.json_diff` and iterated until diff was `{}`.
- 2026-01-25: Added regression test `backend/tests/unit/test_value_line_bti_parser_fixture.py`.
- 2026-01-25: Verified in Docker: `docker compose run --rm --no-deps api pytest -q` (88 passed).

## Expected Fixture Issues Found
- `bti_v1.expected.json` had several inconsistencies vs the parser schema used by other fixtures:
  - Used `gross_dividends_declared` instead of the canonical `dividends_declared`.
  - Included an extra `common_shares_outstanding_millions.label` field (not emitted by v1.1 fixtures).
  - Included a synthetic 2026 row in `quarterly_dividends_paid` (the source table only contains 2022–2025).
  - Marked 2025 dividend full-year as estimated (report date is 2026-01-09).
  - Used `"ADR"` instead of `"ADRs"` for `capital_structure.common_stock.shares_outstanding.unit`.
  - These were corrected by regenerating the expected fixture from the canonical parser output.
