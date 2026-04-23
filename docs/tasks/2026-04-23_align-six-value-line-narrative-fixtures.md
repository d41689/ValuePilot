# Task: Align six Value Line narrative fixtures with generic bottom-page extraction

## Goal / Acceptance Criteria
- Reconcile the remaining six Value Line fixture mismatches caused by improved narrative extraction:
  - `ao_smith`
  - `alibaba`
  - `bti`
  - `coco`
  - `empa.to`
  - `lrn`
- Improve parser behavior generically so business description and analyst commentary extraction is more accurate across fixed-layout Value Line PDFs.
- Keep the solution layout-driven and reusable; no ticker-specific branches.
- Bring the targeted fixture tests back to green.

## Scope
**In**
- Parser changes for narrative extraction.
- Expected/parser/diff fixture updates for the six affected reports.
- Targeted regression tests and Docker verification.

**Out**
- Schema changes.
- Non-Value-Line templates.
- Manual one-off overrides for a specific company.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Value Line-only scope, lineage, normalized facts
- `AGENTS.md` -> Docker-only verification, task logging, parser fixture alignment workflow

## Files To Change
- `docs/tasks/2026-04-23_align-six-value-line-narrative-fixtures.md`
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/ingestion/pdf_extractor.py` if extraction configuration needs further tuning
- `backend/tests/fixtures/value_line/*_v1.expected.json`
- `backend/tests/fixtures/value_line/*_v1.parser.json`
- `backend/tests/fixtures/value_line/*_v1.diff.json`
- relevant unit tests if assertions need to encode the intended generic behavior

## Execution Plan
1. Inspect the six affected PDFs and current parser outputs, focusing on the lower narrative region.
2. Identify stable layout zones for business description and analyst commentary on Value Line pages.
3. Adjust parser extraction so each zone uses the most reliable input path:
   - text layer where ordering is good
   - word coordinates for fixed layout region slicing
   - visual/OCR spot checks only where text-layer order is ambiguous
4. Regenerate parser fixtures and canonical diffs for the affected reports.
5. Update expected fixtures to the corrected generic parser outputs.
6. Run targeted and then broader Docker verification.

## Contract Checks
- No ticker-specific hard-coding.
- Continue using `scripts.value_line_dump` and `scripts.json_diff` for canonical fixture alignment.
- Preserve lineage fields and page JSON schema.

## Rollback Strategy
- Revert parser/fixture changes if the generic extraction quality regresses on unrelated Value Line samples.

## Progress Log
- [x] Inspect affected reports and current outputs.
- [x] Improve generic narrative extraction.
- [x] Regenerate parser/diff fixtures.
- [x] Update expected fixtures.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Initial hypothesis confirmed: Value Line’s fixed lower-page narrative area is more stable when sliced into smaller layout regions (`business`, `commentary`, `signature/date`) before text normalization.
- For narrative extraction, the most reliable generic path was:
  - `pdfplumber` word coordinates with `use_text_flow=True` for page words
  - fixed-layout region slicing for the lower narrative block
  - explicit two-column reading order (`left column -> right column`) inside the lower narrative region
  - text normalization on top of the region output to repair common PDF word-splitting artifacts
- Signature-line detection had to change from "first matching month/day/year line" to "last matching line" because some reports mention dates inside the body text.
- The broader parser improvement surfaced stale `expected.json` fixtures for `ao_smith`, `alibaba`, `bti`, `coco`, `empa.to`, `lrn`, and `calm`; those fixtures were updated to the corrected generic parser output.
- OCR was not required for the final fix set because the text layer plus layout-aware block extraction was sufficient. OCR remains a fallback if a future fixture has an unusable text layer.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_value_line_parser_fixture.py tests/unit/test_value_line_alibaba_parser_fixture.py tests/unit/test_value_line_bti_parser_fixture.py tests/unit/test_value_line_coco_parser_fixture.py tests/unit/test_value_line_empa_to_parser_fixture.py tests/unit/test_value_line_lrn_parser_fixture.py` -> passed (`6 passed`)
- `docker compose exec api pytest -q tests/unit/test_value_line_fnv_parser_fixture.py tests/unit/test_value_line_calm_parser_fixture.py` -> passed
- `docker compose exec api pytest -q` -> passed (`123 passed in 20.63s`)
