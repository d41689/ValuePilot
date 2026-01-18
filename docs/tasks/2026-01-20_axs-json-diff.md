# Task: Nil handling + JSON diff helper

## Goal / Acceptance Criteria
- Treat `Nil` tokens as null (not 0) in parser outputs.
- Provide a CLI script to diff two JSON files and output only mismatched keys with `[left, right]` values.

## Scope
### In Scope
- Parser `_coerce_value` change for `Nil`.
- New JSON diff script.

### Out of Scope
- Parser accuracy improvements beyond Nil handling.
- UI changes.

## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/scripts/json_diff.py`
- `docs/tasks/2026-01-20_axs-json-diff.md`

## Test Plan (Docker)
- `docker compose exec -T api pytest -q`

## Notes / Decisions
- `Nil` tokens now map to `null` (not `0.0`) during value coercion.
- Added a JSON diff helper script for quick comparisons.

## Verification
- `docker compose exec -T api pytest -q`
- Results: 41 passed, 1 warning (FastAPI deprecation).
