# Task: Generate BTI Value Line parser fixture JSON

## Goal / Acceptance Criteria
- Run the project Value Line v1 parser on `backend/tests/fixtures/value_line/bti.pdf`.
- Persist the resulting parsed page JSON to `backend/tests/fixtures/value_line/bti_v1.parser.json`.
- Generation runs inside Docker Compose (no host Python).

## Scope
### In
- Invoking the existing `scripts/value_line_dump.py` pipeline to generate the fixture JSON.

### Out
- Parser logic changes.
- Schema changes.

## Files To Change
- `backend/tests/fixtures/value_line/bti_v1.parser.json` (new)
- `docs/tasks/2026-01-25_generate-bti-parser-json.md` (this file)

## Test Plan (Docker)
- `docker compose run --rm --no-deps api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/bti.pdf --out tests/fixtures/value_line/bti_v1.parser.json`

## Progress Log
- 2026-01-25: Task created.
- 2026-01-25: Generated `backend/tests/fixtures/value_line/bti_v1.parser.json` via `docker compose run --rm --no-deps api python -m scripts.value_line_dump ...`.
