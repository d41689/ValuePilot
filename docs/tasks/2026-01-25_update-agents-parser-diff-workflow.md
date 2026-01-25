# Task: Update AGENTS workflow for parser fixture alignment

## Goal / Acceptance Criteria
- Update `AGENTS.md` to instruct agents to use:
  - `backend/scripts/value_line_dump.py` to generate `*.parser.json` from a given Value Line PDF fixture.
  - `backend/scripts/json_diff.py` to compare `*.parser.json` vs `*.expected.json` by key (instead of OS `diff`).
- No functional/code behavior changes required.

## Scope
### In
- Documentation-only change to `AGENTS.md`.

### Out
- Parser logic changes.
- Test/fixture changes.

## Files To Change
- `AGENTS.md`
- `docs/tasks/2026-01-25_update-agents-parser-diff-workflow.md`

## Test Plan (Docker)
- N/A (documentation-only).

## Progress Log
- 2026-01-25: Task created.
- 2026-01-25: Updated `AGENTS.md` to require `scripts.value_line_dump` + `scripts.json_diff` for fixture alignment tasks (no OS `diff`).
