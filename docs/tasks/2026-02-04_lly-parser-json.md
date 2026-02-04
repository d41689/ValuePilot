# 2026-02-04 Generate LLY Parser JSON

## Goal / Acceptance Criteria
- Generate `tests/fixtures/value_line/lly_v1.parser.json` from `tests/fixtures/value_line/lly.pdf` using the canonical parser script.

## Scope
### In Scope
- Run `scripts.value_line_dump` inside Docker to generate the parser JSON.

### Out of Scope
- Parser code changes
- Fixture diff/realignment

## Files To Change
- `tests/fixtures/value_line/lly_v1.parser.json`
- `docs/tasks/2026-02-04_lly-parser-json.md`

## Test Plan (Docker)
- `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/lly.pdf --out tests/fixtures/value_line/lly_v1.parser.json`

## Progress Update (2026-02-04)
- Generated `tests/fixtures/value_line/lly_v1.parser.json` via `scripts.value_line_dump`.

## Verification (Docker)
- `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/lly.pdf --out tests/fixtures/value_line/lly_v1.parser.json`
