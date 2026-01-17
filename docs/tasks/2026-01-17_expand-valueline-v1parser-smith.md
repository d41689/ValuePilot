# Task: Expand ValueLineV1Parser to match Smith sample dataset

## Goal / Acceptance Criteria

- Given uploaded PDF `pdf_documents.id = 12` (AOS / NYSE), the parsed output in the database should cover the Value Line V1 minimum field set in the PRD and align with `docs/value_line_smith.json` (header ratings, target price ranges, financial snapshot blocks, institutional decisions, quarterly tables, narrative).
- `metric_extractions` must retain full lineage: `document_id`, `page_number`, and `original_text_snippet` for every emitted field.
- Numeric facts must be normalized into base units (`metric_facts.value_numeric`) per PRD Appendix B (USD absolute amounts, percent as ratio 0–1, etc.).
- Screeners/formulas must continue to read only from `metric_facts` and filter using `value_numeric` + `is_current = true`.

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md`:
  - B.4.1 Value Line Template Fields (V1)
  - C. Data Modeling & Storage: `metric_extractions`, `metric_facts`
  - Appendix A: Value Line V1 Field → Metric Mapping Specification
  - Appendix B: Normalization Layer Specification (V1)

## Scope

### In Scope

- Expand `ValueLineV1Parser` to extract the missing Value Line V1 fields present in the Smith sample raw text:
  - Header / Ratings (including trailing/median PE, relative PE, timeliness/safety/technical, beta, report_date, analyst_name, etc.)
  - Target price ranges (18-month and long-term projections + year range)
  - Tables: quarterly sales, EPS, quarterly dividends
  - Financial snapshot blocks: capital structure, current position, annual rates of change
  - Institutional decisions (buy/sell/holds table)
  - Narrative: business description + footnotes blocks (as text fields where needed)
- Add/adjust tests to encode acceptance criteria using the Smith sample raw text layout.

### Out of Scope

- Schema changes / migrations (unless explicitly approved in a follow-up)
- OCR improvements / template detection beyond Value Line V1
- UI changes (unless required to avoid regressions)

## Current State (Observed)

- Upload shows `Document ID: 12` and `pdf_documents.parse_status = 'parsed'`.
- DB currently contains only 3 extractions/facts for doc 12 / stock 20:
  - `recent_price`, `pe_ratio`, `dividend_yield`
- The Smith sample expected dataset in `docs/value_line_smith.json` includes many additional fields (targets, snapshot blocks, quarterly tables, narrative, etc.) that are currently missing from DB for doc 12.

## Files To Change (Expected)

- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/services/ingestion_service.py` (if period/as-of metadata or mapping is required)
- `backend/tests/unit/` (new/updated tests for the Smith layout)
- Optional: add a Smith raw-text fixture under `backend/tests/fixtures/` (if needed for stable tests)

## Execution Plan (Requires Human Approval Before Implementation)

1. Add tests for Smith layout extraction (red):
   - Verify parser extracts the PRD V1 minimum fields present in Smith sample text.
   - Verify normalization expectations for USD/percent/ratio.
2. Implement minimal parser expansions (green):
   - Add regexes tuned to the Smith raw-text layout (including `\\n` tokens and squashed spacing).
   - Ensure each extraction includes an `original_text_snippet`.
3. Wire period/as-of metadata for quarterly tables (if required by tests).
4. Refactor for maintainability (keep tests green).
5. Verify in Docker and record results below.

## Plan Approval

- 2026-01-17: Human approved execution plan (“确认plan”).

## Test Plan (Docker Only)

- `docker compose exec api pytest -q`
- `docker compose exec api pytest -q backend/tests/unit/test_ingestion.py`
- (If adding Smith-specific tests) `docker compose exec api pytest -q backend/tests/unit/test_value_line_smith.py`

## Notes / Decisions / Gotchas

- Smith raw text includes literal `\\n` tokens and squashed table spacing; regexes must tolerate both.
- `metric_facts` currently uses `metric_key = field_key` and a heuristic `value_type`; PRD Appendix A expects a mapping layer. If mapping is added, ensure downstream screeners/formulas remain consistent.
- Running the current `ValueLineV1Parser` against `document_pages.page_text` for doc 12 yields ~16 fields (including target ranges and some snapshot fields), but doc 12 was ingested earlier and only persisted 3 facts; aligning DB likely requires a re-parse/re-ingest path (or re-upload).
- Normalization risk: values like `MARKETCAP:$9.5billion` and `TotalDebt$185.8mill.` have scale tokens adjacent to numbers; current `Scaler.normalize()` relies on word boundaries and may miss the scale unless either parser includes spaces or scaler is made more robust.
- Safety rating appears missing in the native extracted text for doc 12 (`SAFETY Lowered1/2/26` without a digit). Avoid guessing; treat as “not present in text-layer” unless OCR/layout extraction recovers it.

## Verification Results

- `docker compose exec api pytest -q` (green)
- Reparsed existing `pdf_documents.id=12` via `IngestionService.reparse_existing_document(..., reextract_pdf=true)`:
  - `metric_extractions` for doc 12: 3 → 43 → 83 (after second reparse to capture improved annual-rates parsing)
  - `metric_facts` current keys for stock 20: now includes header ratings, targets, capital structure, quarterly tables (JSON), annual rates (JSON), current position (JSON), institutional decisions (JSON), narrative date/analyst.

## Contract Gate (Self-Check)

- Screeners read from `metric_facts` and require `is_current = true` (unchanged).
- Numeric comparisons are on `metric_facts.value_numeric` (unchanged).
- No raw SQL is generated from user input in rule evaluation (unchanged).
- No `eval/exec` is used for formulas (unchanged; restricted AST).
- New parsing emits lineage via `original_text_snippet` (for each ExtractionResult).
- Reparse inserts new rows; prior `metric_extractions` remain immutable; prior parsed `metric_facts` are deactivated per `metric_key`.
