# Task: Fix Value Line annual P/E year alignment

## Goal / Acceptance Criteria
- Confirm the correct year-mapped values for `Avg Annual P/E Ratio` and `Relative P/E Ratio` from the uploaded Value Line document behind `/documents/578/review`.
- Compare the parsed output and stored `metric_facts` values for document `578`.
- Fix the Value Line parser so annual P/E rows map values to the correct fiscal years.
- Ensure regenerated parser output, stored facts, and the document review page show consistent values.

## Scope
**In**
- Parser logic for Value Line annual table row/year alignment.
- Focused tests or fixture updates covering the P/E row offset regression.
- Database reparse/backfill steps for document `578` if parser output changes.
- Browser verification of `http://localhost:3001/documents/578/review`.

**Out**
- Schema changes.
- PRD changes.
- One-off ticker- or document-id-specific parser behavior.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Value Line-only parsing, lineage, normalized facts.
- `AGENTS.md` -> task logging, Docker-only verification, parser fixture alignment workflow, source-of-truth facts.

## Files To Change
- `docs/tasks/2026-04-26_fix-value-line-pe-year-alignment.md`
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- Focused parser tests/fixtures as needed after confirming the affected fixture.

## Execution Plan
1. Inspect parser logic, existing fixtures, and document `578` metadata to identify the uploaded PDF/fixture.
2. Query current `metric_facts` for the annual P/E metrics and compare them to the source document/parser output.
3. Add or update a failing test that captures the year/value offset.
4. Fix parser row/year alignment generically.
5. Regenerate parser output and reparse document `578` if needed.
6. Verify with Docker commands and inspect the review page.

## Contract Checks
- Parser changes must remain generic to Value Line v1 reports.
- `metric_facts.value_numeric` remains the queryable source of truth.
- No raw SQL from user input.
- Existing lineage fields must remain present.

## Rollback Strategy
- Revert parser/test changes and restore generated fixture outputs if the generic fix causes unrelated parser regressions.

## Progress Log
- [x] Create task log.
- [x] Identify uploaded PDF and current DB values for document `578`.
- [x] Add/update failing parser test.
- [x] Implement parser fix.
- [x] Reparse/backfill document `578` if needed.
- [x] Run Docker verification.
- [x] Verify review data path.

## Notes / Decisions / Gotchas
- Initial user report: on `/documents/578/review`, 2019 appears as `Avg Annual P/E Ratio = 46.4` and `Relative P/E Ratio = 2.47`, suggesting annual table values may be shifted against the year headers.
- Document `578` is `FNV.pdf`, linked to stock `FNV` / `FRANCO-NEVADA`.
- PDF word coordinates confirm `46.4` and `2.47` sit under the 2019 column; `37.3` and `2.13` sit under 2024; 2025 and 2026 have no annual values for these two rows.
- Before the fix, `metric_facts` stored `46.4` and `2.47` at `2020-12-31`, and incorrectly stored `37.3` / `2.13` as 2025 estimate facts.
- The parser bug was in annual-table text alignment: rows with more historical columns than the selected 12-year output were trimmed against the selected year list instead of the full detected year header, and the projection-bleed heuristic could remove a legitimate first value in complete rows.
- In-app browser navigation to `/documents/578/review` redirected to `/login` because the browser session was not authenticated. Verification used the backend review payload that the page consumes and the frontend `documentReview` table builder tests.
- Reparsed document `578` after the parser fix. Current stored facts now include `val.avg_pe`: 2019=46.4, 2020=47.9, 2021=38.5, 2022=37.6, 2023=38.8, 2024=37.3; and `val.relative_pe`: 2019=2.47, 2020=2.46, 2021=2.08, 2022=2.17, 2023=2.16, 2024=2.13. No 2025/2026 FY facts are generated for those rows.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_value_line_fnv_parser_fixture.py` -> passed (`2 passed`)
- `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/FNV.pdf --out tests/fixtures/value_line/FNV_v1.parser.json` -> regenerated parser fixture
- `docker compose exec api python -m scripts.json_diff tests/fixtures/value_line/FNV_v1.expected.json tests/fixtures/value_line/FNV_v1.parser.json tests/fixtures/value_line/FNV_v1.diff.json` -> diff is `{}`
- `docker compose exec api pytest -q tests/unit/test_value_line_fnv_parser_fixture.py tests/unit/test_value_line_lrn_parser_fixture.py` -> passed (`3 passed`)
- `docker compose exec api pytest -q tests/unit/test_value_line_annual_facts.py tests/unit/test_value_line_metric_facts_time_series.py` -> passed (`8 passed`)
- `docker compose exec web node --test lib/documentReview.test.js` -> passed (`17 passed`)
- `docker compose exec api pytest -q` -> passed (`155 passed`)
