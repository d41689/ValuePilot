# Fix Adobe Value Line Parser Review Fields

## Goal / Acceptance Criteria
- Fix Value Line parser output for `backend/tests/fixtures/value_line/Adobe202501.pdf` so document review shows:
  - `PROJECTIONS` high `GAIN` as approximately `105%`, not `1.1%`.
  - `CAPITAL STRUCTURE` long-term interest capital percentage from `LT Int. $150.0 mill. (23% Cap'l)`.
  - Non-empty values for `CURRENT POSITION`, `QUARTERLY REVENUES`, `EARNINGS PER SHARE`, and `QUARTERLY DIVIDENDS PAID` when present in the report.
- Keep parser logic generic for Value Line layouts; no Adobe-specific hardcoding.

## Scope
- In: Value Line parser extraction/mapping tests and minimal parser fixes.
- Out: PRD/schema changes, report-specific constants, unrelated frontend redesign.

## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_value_line_adobe_parser_fixture.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/lib/documentReview.js`
- `frontend/lib/documentReview.test.js`
- `frontend/app/(dashboard)/documents/[id]/review/page.tsx`
- `backend/tests/fixtures/value_line/coco_v1.expected.json`
- `backend/tests/fixtures/value_line/coco_v1.parser.json`
- `backend/tests/fixtures/value_line/Adobe202501.pdf`
- `backend/tests/fixtures/value_line/Adobe202501_v1.parser.json` (generated verification artifact)

## Test Plan (Docker)
- Generate parser JSON:
  - `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/Adobe202501.pdf --out tests/fixtures/value_line/Adobe202501_v1.parser.json`
- Run focused parser and frontend regression tests:
  - `docker compose exec api pytest -q tests/unit/test_value_line_adobe_parser_fixture.py`
  - `docker compose exec web node --test lib/documentReview.test.js`
- Run existing Value Line parser fixture suite:
  - `docker compose exec api pytest -q tests/unit/test_value_line_adobe_parser_fixture.py tests/unit/test_value_line_parser_fixture.py tests/unit/test_value_line_smith_parser.py tests/unit/test_value_line_calm_parser_fixture.py tests/unit/test_value_line_coco_parser_fixture.py tests/unit/test_value_line_bti_parser_fixture.py tests/unit/test_value_line_alibaba_parser_fixture.py tests/unit/test_value_line_fnv_parser_fixture.py tests/unit/test_value_line_lrn_parser_fixture.py tests/unit/test_value_line_empa_to_parser_fixture.py tests/unit/test_value_line_bud_parser_fixture.py tests/unit/test_value_line_axs_parser.py tests/unit/test_value_line_axs_parser_time_fields.py`
- Run full backend tests:
  - `docker compose exec api pytest -q`

## Progress Notes
- 2026-05-04: Task opened. Initial investigation pending.
- 2026-05-04: Confirmed Adobe parser JSON already carries `+105%`/`1.05` for high gain; frontend projection formatting was treating ratio values greater than 1 as literal percentages.
- 2026-05-04: Added Adobe PDF regression test for projections, capital structure, current position, quarterly revenues, EPS, and no-cash dividends note.
- 2026-05-04: Parser fix is generic:
  - accepts `LTInt.` as a long-term interest label;
  - accepts `(23%Cap'l)` as a capital percentage without requiring `of`;
  - parses current-position rows with singular `Cash Asset` and `--` placeholders;
  - falls back to word-layout extraction for left-column quarterly revenues and EPS tables when the text layer splits heading letters across columns.
- 2026-05-04: Updated COCO fixture expected/parser JSON because the generic `-- -- 5.0` current-position parser now correctly captures 2025 debt due.
- 2026-05-04: Frontend projection formatting now formats `unit: ratio` values by multiplying by 100, so `1.05` displays as `105.0%`.
- 2026-05-04: Review API now exposes `quarterly_revenues` separately from `quarterly_sales`, and the review page titles the table `QUARTERLY REVENUES` when that block exists.
- 2026-05-04: Review API now builds the no-cash-dividends block from raw report text even when there are no numeric dividend rows.
- 2026-05-04: Reparsed local document `2655` with the updated parser; review builders now return `LT Interest $150.0 mill`, `23%`, populated current position, quarterly revenues, EPS, and the no-cash-dividends note.
- 2026-05-04: Verification passed:
  - `docker compose exec api pytest -q tests/unit/test_value_line_adobe_parser_fixture.py` -> 2 passed.
  - `docker compose exec api pytest -q tests/unit/test_documents_api.py::test_document_review_endpoint_returns_parser_quarterly_revenues_block` -> 1 passed.
  - `docker compose exec web node --test lib/documentReview.test.js` -> 20 passed.
  - Value Line parser fixture suite -> 28 passed.
  - `docker compose exec api pytest -q` -> 200 passed.

## Contract Checklist
- [x] No raw SQL from user input introduced.
- [x] No formula `eval`/`exec` introduced.
- [x] `metric_facts` query/source semantics unaffected.
- [x] Parser remains generic to Value Line templates.
- [x] Verification recorded.
