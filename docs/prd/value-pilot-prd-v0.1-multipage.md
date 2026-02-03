# Status (2026-02-03): MERGED + FROZEN

This addendum has been merged into the single authoritative v0.1 PRD:
- `docs/prd/value-pilot-prd-v0.1.md` (see §B.4.2 “Multi-Page Value Line PDF Ingestion (V1)”)
- If section numbering changes, search in `docs/prd/value-pilot-prd-v0.1.md` for: `Multi-Page Value Line PDF Ingestion (V1)`.

This document is retained as a historical, read-only record and MUST NOT be treated as the current normative spec.

# ValuePilot v0.1 PRD Addendum: Multi-Page Value Line PDF Ingestion

Status: **APPROVED (with edits)** (implementation may begin after an approved execution plan)

## 1. Background / Problem

The current v0.1 PRD scopes Value Line ingestion to the **single-page standard layout**.
However, users may upload a PDF that contains **multiple pages**, where **each page is a separate Value Line equity report for a different company**.

This addendum defines the required behavior and data contracts to support multi-page uploads while preserving:
- the three-layer storage pattern (artifacts → lineage → facts),
- strict lineage (`document_id`, `page_number`, `original_text_snippet`),
- normalized `metric_facts.value_numeric`,
- screeners/formulas querying only `metric_facts` with `is_current = true`.

## 2. Scope

### In Scope (Addendum)

- Uploading a Value Line PDF with **1..N pages**.
- Ingestion parses **each page independently** and persists data for that page’s company.
- Partial success: some pages may parse successfully while others fail.

### Out of Scope (Still)

- Non–Value Line templates.
- “One page contains multiple companies” layouts.
- Cross-page reconciliation (e.g., merging facts across pages).
- OCR quality improvements beyond existing fallback rules.

## 3. Definitions

- **Container PDF Document**: the uploaded PDF file artifact, potentially containing multiple company pages.
- **Page Report**: the independent parsing unit corresponding to a single page within a Container PDF Document.

## 4. Functional Requirements

### 4.1 Upload + Ingestion Flow (Multi-Page)

On upload of a PDF:
1. Store the PDF as a single artifact (`pdf_documents` row) and extract per-page text into `document_pages`.
2. For each page `p` in `document_pages` (ascending `page_number`):
   - Run template validation for Value Line V1 layout.
   - Extract identity (ticker/exchange/company_name) from that page’s text.
   - Resolve stock identity (per existing rules).
   - Parse metrics from that page’s text.
   - Persist **immutable** `metric_extractions` rows with:
     - `document_id = <container document id>`
     - `page_number = p`
     - `original_text_snippet` set for each extracted field
   - Normalize and persist `metric_facts` for the resolved `stock_id`.

In other words: **multi-page ingestion is “loop over pages”; each page is treated like a standalone single-page report.**

### 4.1.1 Single-Page vs Multi-Page Stock Linkage (`pdf_documents.stock_id`)

Rules:
- If the uploaded PDF is **single-page**, `pdf_documents.stock_id` MAY be set (normal single-company ingestion).
- If the uploaded PDF is **multi-page and each page is a different company (this addendum’s v0.1 scope)**:
  - `pdf_documents.stock_id` MUST be **NULL** (multi-company container).

If the PDF happens to contain the **same ticker/exchange** on multiple pages (duplicates/reprints), the ingestion still treats each page as an independent report (see §5.5).

### 4.2 Completion / Partial Failure

- The system MUST attempt all pages even if some pages fail.
- Per-page failures MUST be recorded with enough detail to debug (e.g., stored in `pdf_documents.notes` as structured text, or logged).
- The overall `pdf_documents.parse_status` semantics:
  - `uploaded`: stored but not yet parsed
  - `parsing`: ingestion in progress
  - `parsed`: all pages parsed successfully
  - `parsed_partial`: at least 1 page parsed and at least 1 page failed
  - `failed`: 0 pages parsed successfully

Notes:
- This is a string enum contract only; it does not require a schema migration.

### 4.3 Output Contract (API)

The upload response MUST include per-page results and MUST always include `page_reports[]` (even for single-page PDFs, where length = 1):

```json
{
  "document_id": 123,
  "page_count": 7,
  "status": "parsed_partial",
  "page_reports": [
    {
      "page_number": 1,
      "status": "parsed",
      "parser_version": "v1",
      "stock_id": 10,
      "ticker": "AOS",
      "exchange": "NYSE"
    },
    {
      "page_number": 2,
      "status": "parsed",
      "parser_version": "v1",
      "stock_id": 11,
      "ticker": "MSFT",
      "exchange": "NDQ"
    },
    {
      "page_number": 3,
      "status": "failed",
      "parser_version": "v1",
      "error_code": "unsupported_template",
      "error_message": "Page did not match Value Line V1 template."
    }
  ]
}
```

Notes:
- `page_reports` is required for all uploads and is the primary UI/debugging surface.

Recommended v0.1 `error_code` enum values:
- `unsupported_template`
- `identity_unresolved`
- `parse_error`
- `normalization_error`

## 5. Data Model / Contracts (No Schema Change Version)

This addendum is written to work with the existing v0.1 schema without migrations.

### 5.1 `pdf_documents`

- A multi-page upload produces **one** `pdf_documents` row (the container artifact).
- `pdf_documents.stock_id` MUST be **NULL** when the upload contains multiple companies (this addendum’s v0.1 scope).
- `identity_needs_review` MAY be set to true for multi-page uploads (since `stock_id` is intentionally unset); this is a UI decision.

### 5.2 `document_pages`

- One row per page, with the real `page_number` from the PDF.
- `page_text` is the page’s extracted text (native text, OCR fallback if required).

### 5.3 `metric_extractions`

- For each parsed page report, rows use:
  - `document_id = container pdf_documents.id`
  - `page_number = actual page number`
  - all other lineage fields as per base PRD

### 5.4 `metric_facts`

- Facts are written using the **page-resolved** `stock_id`.
- `source_ref_id` points to the `metric_extractions.id` row for lineage.
- `is_current` semantics remain: for a given `(stock_id, metric_key, period_end_date)`, the latest parsed/manual entry is current.

### 5.5 Same Ticker Appearing on Multiple Pages

If a multi-page upload contains the **same ticker/exchange** on multiple pages (e.g., duplicates or reprints):
- The system MUST still parse pages independently.
- For facts, for the same `(stock_id, metric_key, period_end_date)` written multiple times during this container ingestion run:
  - The **last successfully written** value MUST be `is_current = true` (by ingestion order / later created_at).

## 6. Normalization

Unchanged from base PRD:
- USD amounts -> absolute USD in `value_numeric`
- percentages -> ratio [0,1] in `value_numeric`
- other metrics -> as defined in Appendix B

## 7. Testing Requirements (Post-Approval Implementation Gate)

Once this PRD is approved and implementation begins, tests MUST cover:
- Multi-page PDF with 2+ pages mapping to different tickers produces:
  - per-page `metric_extractions` with correct `page_number`
  - `metric_facts` for each correct `stock_id`
  - `pdf_documents.stock_id` remains NULL for multi-company container
  - `parse_status` is `parsed`/`parsed_partial` as appropriate
- Single-page PDF behavior remains unchanged.

## 8. Idempotency / Re-Run Semantics (v0.1)

Multi-page ingestion is likely to be retried. For a re-run against the same `document_id`:
- The system MUST NOT overwrite existing `metric_extractions` rows (immutability contract).
- The system MUST insert new `metric_extractions` and new `metric_facts` rows for the re-run.
- `metric_facts.is_current` MUST be updated so the latest successful parsed values become current (previous parsed current facts for the same `metric_key` are deactivated).

## 9. Open Questions for Review

1. Should multi-page container uploads set `identity_needs_review = true` by default, or introduce a separate flag to indicate “multi-company container”?
2. Should the UI treat `pdf_documents` as a container and show a list of “page reports”, or should ingestion materialize separate “child documents” (would require schema or conventions)?
