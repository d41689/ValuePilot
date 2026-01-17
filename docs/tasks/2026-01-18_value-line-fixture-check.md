# Task: Create regression test for Value Line Smith fixture

## Goal / Acceptance Criteria

- Run the existing Value Line V1 parsing pipeline on the supplied fixture PDF `tests/fixtures/value_line/smith ao.pdf`.
- Compare the parser output (raw + structured sections that we currently cover) against `tests/fixtures/value_line/ao_smith_v1.expected.json` and flag which canonical fields match/miss.
- The regression test should clearly call out which expected metrics were parsed, which are missing, and which numeric values differ.

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md`:
  - B.4 Parsing Boundary (Value Line templates only)
  - Appendix A (field mappings)
  - Appendix B (normalization base units)

## Scope

### In Scope

- Add a unit test under `backend/tests/unit/` that uses `PdfExtractor` + `ValueLineV1Parser` to materialize parsed metrics for the Smith fixture PDF.
- Load `ao_smith_v1.expected.json` and compare each supported field (header ratings, target ranges, capital structure, current position, tables, institutional decisions, narrative meta) for presence and value agreement.
- Explicitly list which fields are parsed versus missing/mismatched in the test failure message.

### Out of Scope

- Implementing a complete canonical JSON serializer for Value Line reports (only the test is required for now).
- Parsing additional templates or pdf files beyond the provided Smith fixture.

## Files To Change

- `backend/tests/unit/test_value_line_parser_fixture.py` (new test adding comparison logic)
- Possibly helper file/section under `backend/tests/unit/__init__.py` if shared utilities are needed.

## Test Plan (Docker Only)

- `docker compose exec api pytest -q backend/tests/unit/test_value_line_parser_fixture.py`
- (If broader regression suite is triggered) `docker compose exec api pytest -q`

## Notes / Decisions / Gotchas

- The fixture PDF may not include certain header values (e.g., Safety rating is missing from the native text extraction), so the test should treat those keys as expected misses and report them accordingly.
- Normalized values should be compared using `Scaler.normalize` or parser-provided `parsed_value_json` when available.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_value_line_parser_fixture.py` (pass, `business_description` match via normalized comparator; no missing keys reported)
