# Task: PRD for multi-page Value Line PDF ingestion

## Goal / Acceptance Criteria

- Define PRD changes needed to support uploading a PDF with **1..N pages**, where **each page is an independent Value Line equity report for a different company**.
- Define end-to-end ingestion semantics: extract pages → parse each page independently → persist lineage (`metric_extractions`) and facts (`metric_facts`) for the correct stock per page.
- Define partial success behavior (some pages parse, others fail) and the API contract for returning per-page results.

## Scope (In / Out)

### In Scope

- PRD addendum for multi-page upload + ingestion semantics.
- Data contract updates required for page-level identity/fact linkage.
- API response contract for per-page results.

### Out of Scope

- Implementation (must wait for PRD review approval).
- Schema changes (will be explicitly proposed in PRD if required).

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md` (current constraint: single-page Value Line layout only)

## Files To Change

- `docs/prd/value-pilot-prd-v0.1-multipage.md` (new PRD addendum)

## Test Plan (Docker Only)

- N/A (PRD-only change)

## Notes

- Current PRD explicitly scopes v0.1 Value Line parsing to **single-page** reports; this task introduces a new “multi-page = multi-company” ingestion mode and therefore needs PRD approval first.

## Review Outcome

- 2026-01-17: Approved by human reviewer with required edits:
  - Multi-page multi-company containers MUST keep `pdf_documents.stock_id = NULL`
  - Add `parse_status` enum values including `parsed_partial`
  - API MUST always return `page_reports[]` (single-page included), plus `parser_version` and `error_code`/`error_message`
  - Define “same ticker on multiple pages” + `is_current` last-write-wins semantics
  - Define idempotent re-run semantics (append-only extractions; newest facts become current)

## Next: Implementation Plan (Requires Human Approval Before Coding)

1. Add unit tests for multi-page ingestion behavior (red):
   - Mock `PdfExtractor.extract_pages_with_words()` to return 2+ pages with different tickers.
   - Assert the API returns `page_reports[]` for all pages.
   - Assert `pdf_documents.stock_id` remains NULL for multi-company container.
   - Assert `metric_extractions.page_number` and `document_id` are correct per page.
   - Assert `parse_status` becomes `parsed` / `parsed_partial` / `failed` based on per-page outcomes.
2. Refactor ingestion to loop over pages (green):
   - Parse each page independently (per-page `ValueLineV1Parser` instance).
   - Resolve `stock_id` per page without mutating `pdf_documents.stock_id` for multi-company containers.
   - Persist extractions/facts per page; keep `metric_extractions` immutable; deactivate prior parsed current facts per `metric_key`.
3. Update upload endpoint response contract:
   - Always include `page_reports[]` (single-page included), with `parser_version` and `error_code`/`error_message` for failures.
4. Verify in Docker:
   - `docker compose exec api pytest -q`

## Implementation Notes (Progress)

- Added multi-page parsing loop: each `document_pages.page_text` is parsed independently and facts are written per-page resolved `stock_id`.
- For multi-page multi-company uploads, `pdf_documents.stock_id` remains NULL (contract).
- For single-page uploads, `pdf_documents.stock_id` is set to the resolved stock (backward compatible behavior).
- Upload endpoint now always returns `page_reports[]` (single-page length 1), including `parser_version` and per-page errors.

## Verification Results

- `docker compose exec api pytest -q` (green)
