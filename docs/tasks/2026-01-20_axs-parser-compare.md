# Task: Generate parser-output JSON for AXS fixture comparison

## Goal / Acceptance Criteria
- Use the current ValueLine parser to parse `backend/tests/fixtures/value_line/axs.pdf`.
- Generate a JSON file that mirrors the key structure of `backend/tests/fixtures/value_line/axs_v1.expected.json`.
- Populate values with parser outputs where available; leave missing values as null/empty to highlight gaps.

## Scope
### In Scope
- Scripted extraction using existing parser.
- Output file generation for comparison.

### Out of Scope
- Parser improvements or extraction logic changes.
- UI changes.

## Files To Change
- `backend/tests/fixtures/value_line/axs_v1.parser.json`
- `docs/tasks/2026-01-20_axs-parser-compare.md`

## Test Plan (Docker)
- N/A (data extraction script only)

## Notes / Decisions
- Generated parser-output comparison file by mirroring `axs_v1.expected.json` keys and filling from parser results.
- Missing parser outputs are represented as `null` (or null-filled arrays) to highlight gaps.

## Output
- `backend/tests/fixtures/value_line/axs_v1.parser.json`
