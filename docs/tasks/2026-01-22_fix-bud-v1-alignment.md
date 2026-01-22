# Task: Fix BUD v1 parser alignment

## Tech Lead Review (Actionable Feedback)
- Tighten the “done” definition: treat this as a **golden fixture** change. The primary acceptance gate should be a test that asserts `actual == expected` for BUD (not only “diff is empty”). Keep the diff file as a secondary diagnostic artifact.
- Add explicit non-regression gates: run the existing AO Smith / AXS fixture tests (or any v1 parser unit tests) to ensure the BUD-specific fixes don’t regress other PDFs.
- Be explicit about *structure vs value* alignment:
  - Many current diffs are “expected has object, parser has null” which likely means **missing section emission** (keys absent / sections set to `None`) rather than parse failure.
  - Some diffs are **misalignment/offset bugs** (e.g., `avg_annual_pe_ratio` year shifting; `quarterly_sales` containing EPS-like values; ADR vs share unit selection). These need targeted fixes with focused tests.
- Prefer minimal, deterministic fixes:
  - If expected JSON includes keys with `null`, ensure the parser emits those keys consistently (don’t omit sections conditionally unless the expected does).
  - Preserve ordering semantics for arrays (`by_year` lists) to match fixture expectations (stable sort by calendar year ascending, etc.).
- Practical note: `backend/scripts/diff_outputs.py` currently fails in-container due to `ModuleNotFoundError: scripts` when invoked as `python scripts/diff_outputs.py`. For verification, use `python scripts/json_diff.py ...` (works) or adjust `diff_outputs.py` later (optional / separate task).

## Goal / Acceptance Criteria
- Primary: A new/updated unit test asserts BUD v1 parser output **exactly equals** `backend/tests/fixtures/value_line/bud_v1.expected.json`.
- Secondary: Re-generated `backend/tests/fixtures/value_line/bud_v1.parser.json` diffs cleanly against expected (0 diffs) using `backend/scripts/json_diff.py`.
- Must fix:
  - The 50 currently-missing items (present in expected, absent/null in parser output).
  - Alignment issues for:
    - `annual_financials.valuation_metrics.avg_annual_pe_ratio` (year/value offsets)
    - `earnings_per_share` presence/shape
    - `quarterly_dividends_paid` year ordering / estimated flags / notes behavior
    - `quarterly_sales` data source correctness (must be sales, not EPS)

## Scope
**In**
- Update Value Line v1 parser/mapping logic to align BUD fixture output to expected JSON.
- Update/extend tests that assert the fixture output (TDD).

**Out**
- Schema changes.
- Non-Value Line templates.
- Changes unrelated to BUD alignment.

## PRD References
- B.4 Parsing Boundary (Value Line only)
- B.4.1 Value Line Template Fields (V1)
- Normalization (V1) requirements for numeric fields
- Narrative extraction requirements (business_description, analyst_name)

## Files to Change (Expected)
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/ingestion/parsers/v1_value_line/page_json.py`
- `backend/tests/fixtures/value_line/bud_v1.expected.json` (reference only; no edits expected)
- `backend/tests/unit/test_value_line_parser_fixture.py` and/or a new BUD-specific fixture test (recommended: `backend/tests/unit/test_value_line_bud_parser_fixture.py`)

## Test Plan (Docker)
- Focused (during iteration):
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_bud_parser_fixture.py`
- Non-regression (before declaring done):
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_parser_fixture.py`
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_axs_parser.py`
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_axs_parser_time_fields.py`

## Execution Plan (Pending Approval)
1. Add a BUD fixture test that loads `bud.pdf` and compares against `bud_v1.expected.json` (red).
2. Identify missing/misaligned sections in Value Line v1 parser output for BUD.
3. Update parsing/mapping logic to populate missing fields and fix alignment for the specified sections (green).
4. Add/adjust unit-level tests for the specific alignment issues (PE ratio year mapping; quarterly tables; ADR/share selection) to prevent regressions (keep tests small and local when possible).
5. Re-run fixture test(s) and regenerate `bud_v1.parser.json`, then produce a diff artifact:
   - Generate parser JSON:
     - `docker compose exec api python - <<'PY' ... PY` (or add a small `backend/scripts/value_line_dump_bud.py` similar to `value_line_dump_axs.py`)
   - Generate diff:
     - `docker compose exec api python scripts/json_diff.py tests/fixtures/value_line/bud_v1.expected.json tests/fixtures/value_line/bud_v1.parser.json tests/fixtures/value_line/bud_v1.diff.json`
6. Record verification results and contract checklist in this task file.

## Rollback Strategy
- Keep changes isolated to v1 Value Line parser/page JSON code paths.
- If regressions appear on AXS/AO Smith fixtures, revert the smallest offending change and replace with a BUD-conditional parsing rule only if it generalizes safely (prefer general fixes, but avoid breaking other fixtures).

## Contract Checklist (Fill During Verification)
- [x] No schema changes
- [x] Parser remains Value Line v1 template-scoped
- [x] No eval/exec and no raw SQL introduced
- [x] Traceability preserved in parser output structures (page_number, source snippets/bbox where applicable)
- [x] Numeric normalization rules unchanged (percent/currency scales handled consistently)

## Notes
- Keep extraction consistent with Value Line template semantics; no schema changes.

## Verification
- `docker compose exec api pytest -q tests/unit/test_value_line_bud_parser_fixture.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_parser_fixture.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_axs_parser.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_axs_parser_time_fields.py`

## Result
- `bud_v1.parser.json` regenerated; `bud_v1.diff.json` is empty (0 diffs).
