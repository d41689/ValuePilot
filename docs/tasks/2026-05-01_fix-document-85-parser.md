# Fix Document 85 Parser

## Goal / Acceptance Criteria

- Identify why report page `/documents/85` parses incorrectly.
- Add or update parser tests that reproduce the incorrect output.
- Fix the Value Line parser with minimal changes so document 85 parses correctly.
- Keep data lineage and normalization contracts intact.

## Scope

In:
- Document 85 investigation through stored PDF/text/parser output.
- Value Line parser behavior for the affected report pattern.
- Focused parser tests and fixture updates as needed.

Out:
- PRD/schema changes.
- Screener or formula behavior changes.
- Broad parser refactors unrelated to document 85.

## Files to Change

- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/tests/unit/test_value_line_mtdr_identity.py`
- `backend/tests/fixtures/value_line/mtdr.pdf`

## Test Plan

- `docker compose up -d --build`
- `docker compose run --rm api alembic upgrade head`
- `docker compose run --rm api pytest -q tests/unit/test_value_line_mtdr_identity.py`
- `docker compose run --rm api pytest -q`

## Notes

- 2026-05-01: Started on branch `codex/fix-document-85-parser`.
- 2026-05-01: `docker compose up -d --build` built images and started DB, but API port `8101` was already bound by the local production API container. Continued verification with Docker Compose one-off `api` containers to avoid disrupting the running prod service.
- 2026-05-01: Investigation plan: find document 85 metadata/PDF, reproduce parser output, compare incorrect fields against source evidence, then write a focused failing test before changing parser code.
- 2026-05-01: Document 85 is `MTDR.pdf` with header text `MATADOR RESOURCES ...` and `NYSE-MTDRPRICE RATIO ...`. Current parser reproduces the bad identity as `ticker=PRICE`, `exchange=NYSE`, `company_name=None`.
- 2026-05-01: Root cause: PDF word coordinates put `NYSE` and `PRICE` in the same rounded top bucket, while the actual `-MTDR` ticker token is 1.58 points lower and lands in a neighboring bucket. The word-layout identity fallback chooses `PRICE` before seeing `-MTDR`.
- 2026-05-01: Plan: add a focused failing identity test with MTDR-like word coordinates, then adjust `_identity_from_words` to inspect visually adjacent words within a small vertical tolerance before metric header words such as `PRICE`.
- 2026-05-01: Added real `mtdr.pdf` fixture test. Red result reproduced `PRICE` vs `MTDR`.
- 2026-05-01: Updated word-layout identity detection to inspect visually adjacent words near the exchange token, skip header artifact tokens, and derive company name from the `RECENT` header line when word fallback supplies the ticker.
- 2026-05-01: Verified generated MTDR page JSON identity is `MATADOR RESOURCES / MTDR / NYSE`.
- 2026-05-01: Verification passed:
  - `docker compose run --rm api alembic upgrade head`
  - `docker compose run --rm api pytest -q tests/unit/test_value_line_mtdr_identity.py`
  - `docker compose run --rm api pytest -q tests/unit/test_value_line_mtdr_identity.py tests/unit/test_ingestion.py tests/unit/test_value_line_smith_parser.py`
  - `docker compose run --rm api pytest -q tests/unit/test_value_line_parser_fixture.py tests/unit/test_value_line_axs_parser.py tests/unit/test_value_line_bti_parser_fixture.py tests/unit/test_value_line_fnv_parser_fixture.py`
  - `docker compose run --rm api pytest -q`

## Contract Checklist

- [x] `metric_facts` remains the queryable source of truth for screeners.
- [x] Numeric comparisons continue to use normalized `value_numeric`.
- [x] No raw SQL from user input.
- [x] No eval/exec formula execution.
- [x] Parsed metrics retain lineage fields.
- [x] `is_current` semantics are preserved.
