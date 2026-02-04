# 2026-02-04 Align LLY Parser Output

## Goal / Acceptance Criteria
- `tests/fixtures/value_line/lly_v1.parser.json` matches `tests/fixtures/value_line/lly_v1.expected.json`.
- `tests/fixtures/value_line/lly_v1.diff.json` is `{}` after alignment.

## Scope
### In Scope
- Parser adjustments within the Value Line v1 parser to align LLY fixture output.
- Regenerate `lly_v1.parser.json` and update diff JSON via canonical scripts.

### Out of Scope
- Schema changes or migrations.
- Modifying expected fixture unless explicitly requested.

## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/*`
- `tests/fixtures/value_line/lly_v1.parser.json`
- `tests/fixtures/value_line/lly_v1.diff.json`
- `docs/tasks/2026-02-04_align-lly-parser-expected.md`

## Test Plan (Docker)
- `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/lly.pdf --out tests/fixtures/value_line/lly_v1.parser.json`
- `docker compose exec api python -m scripts.json_diff tests/fixtures/value_line/lly_v1.expected.json tests/fixtures/value_line/lly_v1.parser.json tests/fixtures/value_line/lly_v1.diff.json`
- If parser code changes: `docker compose exec api pytest -q` (or targeted parser tests)

## Progress Update
- Updated recent price parsing to handle OCR-merged tokens like `RECEN1T062.19`.
- Reworked institutional decisions parsing to correctly segment quarter columns, derive year from row tokens, and normalize invalid year fallbacks.
- Fixed long-term projection low total return percent handling to avoid double `%`.
- Adjusted valuation series alignment heuristic to preserve expected year offsets while handling trailing placeholder years.
- Regenerated parser output and diff; current diff is `{}`.

## Verification Results
- `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/lly.pdf --out tests/fixtures/value_line/lly_v1.parser.json`
- `docker compose exec api python -m scripts.json_diff tests/fixtures/value_line/lly_v1.expected.json tests/fixtures/value_line/lly_v1.parser.json tests/fixtures/value_line/lly_v1.diff.json`
- `docker compose exec api pytest -q`

## Contract Checklist
- [x] No schema changes.
- [x] Parser output aligned with expected fixture.
- [x] Full test suite.
