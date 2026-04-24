# Document Review Workbench

## Goal / Acceptance Criteria

Build a document-level review workflow for parsed Value Line report data.

- Add a `Review Extracted Data` action to each row on `/documents`.
- Open a full-page review experience at `/documents/{document_id}/review`.
- Present extracted data in Value Line report-oriented groups instead of raw JSON.
- Show each reviewed value with lineage context where available: metric key, parsed/display value, normalized value, unit, period, page number, source type, current status, and original text snippet.
- Support manual correction for an individual field without mutating immutable `metric_extractions`.
- Manual correction must insert a new `metric_facts` row with `source_type = 'manual'` and `is_current = true`, while deactivating the previous current fact for the same stock/metric/period identity.

## Scope

### In

- Backend read API for document review payloads.
- Backend correction API for review fields backed by `metric_facts`.
- Frontend `/documents` row action linking to the review page.
- Frontend `/documents/[id]/review` page.
- Review UI grouped by Value Line report modules:
  - Identity & Header
  - Ratings & Quality
  - Target & Projection
  - Capital Structure
  - Annual Rates
  - Quarterly Tables
  - Annual Financials
  - Institutional Decisions
  - Narrative
- Focused tests for API contract, correction immutability/current-fact behavior, and frontend grouping helpers.

### Out

- No PRD changes.
- No database schema changes unless implementation proves an existing contract cannot be represented.
- No parser behavior changes.
- No batch correction workflow.
- No direct editing of parser JSON.
- No mutation of existing `metric_extractions`.
- No mandatory PDF coordinate highlighting in v1; snippet/page evidence is sufficient for the first version.

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md`:
  - `B.4 Parsing Boundary (Explicit Scope)`
  - `B.4.1 Value Line Template Fields (V1)`
  - `C. Data Modeling & Storage (PostgreSQL)`
  - `metric_extractions (field-level lineage)`
  - `metric_facts (queryable facts for formulas/screeners)`
  - `Data Traceability Requirements`
  - `Appendix A: Metric Keys & Mapping Contracts (V1)`
  - `Appendix B: Normalization Layer Specification (V1)`
- `docs/prd/value-pilot-prd-v0.1-multipage.md`:
  - `4.3 Output Contract (API)`
  - `5.3 metric_extractions`
  - `5.4 metric_facts`
  - `6. Normalization`
- `docs/value_line_report_modules.md`:
  - `1. Module Index (canonical)`
  - `A. Header & Ratings (Snapshot)`
  - `B. Targets & Projections (Range/Projection)`
  - `C. Ownership & Positioning (Snapshot)`
  - `D. Financial Tables (Time-series)`
  - `E. Performance & Price History`
  - `F. Narrative (Text)`
  - `2. Canonical JSON organization (module-oriented)`

## Proposed API Contract

Backend endpoints:

- `GET /documents/{document_id}/review`
- `POST /documents/{document_id}/review/facts/{fact_id}/corrections`

Correction request shape:

```json
{
  "value": "123.4",
  "unit": "million",
  "note": "Corrected after reviewing source report."
}
```

Correction behavior:

- Validate document ownership.
- Validate fact ownership.
- Validate the target fact belongs to the reviewed document or is linked to the reviewed document through lineage.
- Reject a `fact_id` that belongs to another user, another document, or a stock not associated with the reviewed document.
- Normalize using existing normalization helpers only.
- If normalization fails, return a structured `400` response and create no rows.
- In one transaction:
  - set previous current facts for the same current fact identity to `is_current = false`;
  - insert a new manual `metric_facts` row with `source_type = 'manual'` and `is_current = true`.

## Current Fact Identity

A current fact identity is defined as:

- `user_id`
- `stock_id`
- `metric_key`
- `period_type`
- `period_end_date`
- `as_of_date`

`document_id` is treated as source lineage, not as part of the current fact identity.

## Review Payload Shape

Minimum response shape for `GET /documents/{document_id}/review`:

```json
{
  "document": {
    "id": "document-id",
    "filename": "AAPL Value Line.pdf",
    "ticker": "AAPL",
    "company_name": "Apple Inc.",
    "report_date": "2026-04-24"
  },
  "groups": [
    {
      "key": "ratings_quality",
      "label": "Ratings & Quality",
      "items": [
        {
          "metric_key": "timeliness_rank",
          "label": "Timeliness",
          "fact_id": "fact-id",
          "display_value": "2",
          "value_numeric": 2,
          "value_text": null,
          "unit": "rank",
          "period_type": "snapshot",
          "period_end_date": null,
          "as_of_date": "2026-04-24",
          "source_type": "parser",
          "is_current": true,
          "lineage_available": true,
          "lineage": {
            "extraction_id": "extraction-id",
            "document_id": "document-id",
            "page_number": 1,
            "original_text_snippet": "Timeliness 2"
          },
          "editable": true
        }
      ]
    }
  ]
}
```

## Editable Field Rules

Editable fields:

- Fields backed by a `metric_facts` row.
- Fields with a stable `fact_id`.
- Numeric, text, date, or categorical facts supported by existing normalization logic.

Non-editable fields in v1:

- Raw parser JSON.
- Existing `metric_extractions` rows.
- Narrative-only snippets without a corresponding `metric_facts` row.
- Derived or calculated display-only values.

## Lineage Resolution

Lineage should be resolved in this order:

1. Match by `metric_facts.source_ref_id = metric_extractions.id`.
2. If unavailable, match by `document_id`, `metric_key`, `period_type`, `period_end_date`, and `as_of_date`.
3. If still unavailable, return the fact without lineage and set `lineage_available = false`.

## Files To Change

Expected files:

- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/app/(dashboard)/documents/page.tsx`
- `frontend/app/(dashboard)/documents/[id]/review/page.tsx`
- `frontend/lib/documentReview.js`
- `frontend/lib/documentReview.test.js`

Possible supporting files:

- `frontend/types/api.ts`
- `frontend/types/extraction.ts`
- `docs/api_reference.md`

## Execution Plan

Docker only:

- `docker compose up -d --build`
- `docker compose exec api pytest -q backend/tests/unit/test_documents_api.py`
- `docker compose exec api pytest -q`
- Frontend tests if available in container:
  - `docker compose exec frontend npm test -- documentReview.test.js`
  - or the repository's existing frontend test command if different

## Progress Notes

- 2026-04-24: Product design approved by user. Full-page route `/documents/{document_id}/review` is the approved UX direction.
- 2026-04-24: Implemented backend review payload endpoint and correction endpoint.
- 2026-04-24: Implemented `/documents/[id]/review` full-page frontend with grouped fact cards, lineage snippets, raw report text panel, and single-field correction form.
- 2026-04-24: Added `/documents` row action linking to the review page.
- 2026-04-24: Added API and frontend helper tests for grouping, lineage, ownership, manual correction immutability, current fact semantics, and normalization-failure no-write behavior.

## Verification Results

- `docker compose up -d --build` -> pass.
- `docker compose exec -T api pytest -q tests/unit/test_documents_api.py -q` -> pass (`12 passed`).
- `docker compose exec -T api pytest -q` -> pass (`150 passed`).
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass (`3 passed`).
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` -> pass (`31 passed`).
- `docker compose exec -T web npm run lint` -> pass.
- `docker compose exec -T web npm run build` -> fails on existing `/404` prerender issue: `<Html> should not be imported outside of pages/_document`; after fixing this task's `useParams` type error, the remaining build failure does not point to the new review files.

## Status

- Implemented; ready for human review.

## Contract Checks

- `metric_extractions` remains immutable except existing correction markers only if a legacy endpoint is intentionally reused; preferred implementation does not edit extractions.
- Manual corrections create new `metric_facts` rows with `source_type = 'manual'`.
- Previous current facts for the same user, stock, metric, period type, period end date, and as-of date are set to `is_current = false`.
- Correction creation and previous-current deactivation happen in the same transaction.
- Correction fails with no database writes if normalization fails.
- `document_id` is not part of current fact identity; it is source lineage only.
- Screeners continue to read from `metric_facts` and compare with `value_numeric`.
- No raw SQL from user input.
- No formula `eval` or `exec`.
- Normalized values stay in base units.
- Review payload includes lineage fields where available: `document_id`, `page_number`, and `original_text_snippet`.

## Execution Plan

1. Write backend API tests first for:
   - `GET /documents/{document_id}/review`
   - authorization boundary for another user's document
   - grouped review payload shape
   - correction creates manual current fact and does not modify `metric_extractions`
   - correction deactivates the previous current fact for the same stock/metric/period identity
2. Implement backend review payload assembly from current `metric_facts` plus lineage from `metric_extractions` using the lineage resolution order defined above.
3. Implement backend correction endpoint with strict contract checks:
   - require document ownership
   - require target fact belongs to the document/user
   - normalize only through existing normalization helpers
   - update current fact semantics in one transaction
4. Write frontend helper tests for grouping/formatting document review data into report modules and table-oriented sections.
5. Add `/documents/[id]/review` UI:
   - full-page layout
   - document header with filename, report date, ticker/company
   - grouped cards and tables
   - original snippet panel per value
   - edit action for eligible fact-backed fields
6. Add `/documents` row action linking to the review page.
7. Update this task file with implementation notes, decisions, and verification results.
