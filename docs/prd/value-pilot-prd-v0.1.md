**Note**: This document is the consolidated **schema and execution PRD** for ValuePilot v0.1.  
> It focuses on parsing boundaries, data models, and execution semantics.  
> Higher-level product narrative (Background, Milestones) may live in a separate overview doc.

## A. Contract Sources & Precedence (V1)

This PRD intentionally separates “system behavior + storage contracts” from “metric semantics”.

If any inconsistencies exist, the following precedence order MUST be applied:
1) `docs/metric_facts_mapping_spec.yml` (metric semantics: `metric_key`, units, `period_type`, `period_end_date` derivations)
2) `docs/prd/value-pilot-prd-v0.1.md` (system behavior, schema, ingestion/API contracts)
3) Historical addendums / decision records (read-only reference; not normative)

This PRD MUST NOT be used to redefine metric semantics outside `docs/metric_facts_mapping_spec.yml`.
Any PRD text about metrics is descriptive and MUST defer to the mapping spec for canonical keys, units, and period rules.

## B.4 Parsing Boundary (Explicit Scope)

- V1 parsing is **template‑based**, not generic.
- **V1 supports Value Line equity report PDFs only** (each parsed page must match the single‑page standard layout).
- V1 supports both:
  - single-page PDFs (one company), and
  - multi-page “container PDFs” where each page is an independent Value Line report for a different company (see §B.4.2).
- Non‑Value Line pages can still be uploaded/stored; ingestion reports `unsupported_template` at the page level and the overall document status may be `failed` if 0 company pages parse successfully.

### B.4.1 Value Line Template Fields (V1)

The V1 parser MUST extract (at minimum) the following fields when present:

**Header / Ratings**
- company_name, ticker, exchange
- recent_price
- pe_ratio (recent / trailing), relative_pe_ratio
- dividend_yield
- timeliness, safety, technical, beta
- report_date (Value Line issue date)

**Target Price Ranges**
- 18_month_target_low, 18_month_target_high, 18_month_target_midpoint, midpoint_pct_to_mid
- long_term_projection_high_price, long_term_projection_low_price
- long_term_projection_high_total_return_pct, long_term_projection_low_total_return_pct
- long_term_projection_year_range (e.g. "2028-2030")

**Tables (time series)**
- quarterly_sales (by quarter + full year totals)
- earnings_per_share (by quarter + full year totals)
- quarterly_dividends (by quarter + full year totals)

**Financial snapshot blocks**
- capital_structure (debt, leases, pension assets/obligations, shares outstanding, market cap)
- current_position (current assets/liabilities breakdown)
- annual_rates_of_change (sales/cash flow/earnings/dividends/book value; 10yr/5yr/est.)

**Narrative**
- business_description (Value Line “BUSINESS” paragraph)
- analyst_name

### B.4.2 Multi-Page Value Line PDF Ingestion (V1)

The system MUST support PDFs with 1..N pages where each page is parsed independently.

Definitions:
- **Container PDF Document**: the uploaded PDF artifact (may contain multiple company pages).
- **Page Report**: the independent parsing unit corresponding to a single page within a Container PDF Document.
- **Company Page**: a page that passes the Value Line V1 template validation (page-level).

In Scope:
- Loop over pages (ascending `page_number`) and parse each page as a standalone Value Line report.
- Partial success: some pages may parse successfully while others fail or are skipped as non-company pages.

Out of Scope (v0.1):
- Non–Value Line templates.
- “One page contains multiple companies” layouts.
- Cross-page reconciliation (merging facts across pages).

Upload + ingestion flow:
1) Store the PDF as one `pdf_documents` row and extract per-page text into `document_pages`.
2) For each page `p`:
   - Validate Value Line V1 template (page-level).
   - Extract identity (ticker/exchange/company_name) from that page.
   - Resolve stock identity per §Stock Identity Resolution.
   - Parse metrics and persist immutable `metric_extractions` with:
     - `document_id = <container document id>`
     - `page_number = p`
     - `original_text_snippet` set for each extracted field
   - Map parsed page JSON to `metric_facts` using `docs/metric_facts_mapping_spec.yml`.

Single-page vs multi-page stock linkage (`pdf_documents.stock_id`):
- If the uploaded PDF is single-page and represents a single company, `pdf_documents.stock_id` MAY be set.
- If the uploaded PDF is multi-page and contains multiple companies, `pdf_documents.stock_id` MUST be NULL (multi-company container).

Completion status (`pdf_documents.parse_status`, v0.1):
- `uploaded`: stored but not yet parsed
- `parsing`: ingestion in progress
- `parsed`: all company pages parsed successfully (non-company pages may be skipped)
- `parsed_partial`: at least 1 company page parsed and at least 1 company page failed (e.g., identity unresolved / parse error)
- `failed`: 0 company pages parsed successfully

Output contract (API):
- The upload response MUST include `page_reports[]` even for single-page PDFs (length = 1).
- Each entry MUST include `page_number`, `status`, and `parser_version`.
- `page_number` is 1-indexed (matches PDF page numbering).

Note:
- `pdf_documents.parse_status` is document-level.
- `page_reports[].status` is page-level and may include `unsupported_template` even when `pdf_documents.parse_status` is `parsed` or `parsed_partial`.

Example (schema shape, not exhaustive):

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
      "status": "unsupported_template",
      "parser_version": "v1",
      "error_code": "unsupported_template",
      "error_message": "Non-company page skipped."
    },
    {
      "page_number": 3,
      "status": "failed",
      "parser_version": "v1",
      "error_code": "identity_unresolved",
      "error_message": "Could not resolve ticker/exchange for page."
    }
  ]
}
```

Recommended `error_code` enum values (v0.1):
- `unsupported_template`
- `identity_unresolved`
- `parse_error`
- `normalization_error`

Non-normative reference: see multi-page behavior tests in `backend/tests/unit/test_multipage_value_line_upload.py`.

### Canonical Metric Key Rules (V1)

- All `metric_key` values MUST:
  - use dotted namespaces with `snake_case` segments (e.g., `mkt.price`, `val.pe`, `per_share.eps`)
  - NOT start with a number
- Metric keys MUST NOT encode units (no `_usd`, `_pct`, `_millions` in the key); units live in `metric_facts.unit` and are defined in `docs/metric_facts_mapping_spec.yml`.
- Only canonical keys are exposed to formulas and screeners.
See Appendix A.2 for the canonical regex form.

---

## C. Data Modeling & Storage (PostgreSQL)

### Core Tables (V1 Schema Draft)

> Principle: store both (1) **document artifacts** (file/pages/text), (2) **field-level extractions with lineage**, and (3) **metric facts** that power formulas/screeners.

#### users
- id
- email
- created_at

#### stocks
- id
- ticker
- exchange
- company_name
- is_active
- created_at

Note:
- Stocks are **global master data**, not user-owned.
- User-specific views (pools, alerts, metrics) reference `stock_id`.

### Stock Identity Resolution (V1)

- The Value Line parser MUST extract `ticker` and `exchange` when available.
- On PDF ingestion:
  - If (ticker, exchange) exists in `stocks`, reuse its `id`.
  - Otherwise, auto-create a new `stocks` record.
- After resolving by (ticker, exchange), the system MUST compare `company_name` from the PDF to `stocks.company_name`.
- If ticker/exchange matches but company name similarity is below a threshold, set `pdf_documents.identity_needs_review = true` and do NOT auto-link without user confirmation.
- `pdf_documents` and downstream metrics are linked to stocks via `stock_id`.

#### pdf_documents
- id
- user_id
- file_name
- source (e.g. Value Line)
- upload_time
- file_storage_key (store original PDF; text can be regenerated)
- parse_status (uploaded / parsing / parsed / parsed_partial / failed)
- parser_template_id (nullable)
- parser_version
- raw_text (optional cache)
- notes
- stock_id (nullable; resolved via Stock Identity Resolution)
- identity_needs_review (bool; default false)

#### parser_templates
- id
- name (e.g. "value_line_equity_report_v1")
- vendor (Value Line)
- version
- description
- is_active

#### document_pages
- id
- document_id
- page_number
- page_text
- page_image_key (optional, for calibration UI)
- text_extraction_method (native_text; `ocr` reserved for future)

Text Extraction Strategy (V1):
- v0.1 implementation uses native text-layer extraction.
- OCR fallback is reserved for a future revision; when introduced it MUST be expressed via `document_pages.text_extraction_method = ocr` (and must not break lineage contracts).

#### metric_extractions (field-level lineage)
- id
- user_id
- document_id
- page_number
- field_key (e.g. "recent_price", "timeliness", "quarterly_sales")
- raw_value_text
- original_text_snippet (explicit snippet used for traceability; may duplicate raw_value_text)
- parsed_value_json (typed value; supports number/string/percent + units)
- unit (nullable)
- currency (nullable)
- period (nullable; FY2024/TTM/2024-03-31/etc.)
- period_type (FY / Q / TTM)
- period_end_date (YYYY-MM-DD)
- as_of_date (nullable; YYYY-MM-DD)
- confidence_score (0–1)
- bbox_json (optional: {x0,y0,x1,y1} for highlighting in calibration UI)
- parser_template_id
- parser_version
- created_at
- corrected_by_user (bool)
- corrected_at (nullable)
- target_year_range (nullable; e.g. "2028-2030" for rolling projections)

Correction Semantics (V1):
- `parsed_value_json` stores the latest parsed value produced by the parser.
- When a user corrects a value:
  - The corrected value is written into `metric_facts` (source_type = manual).
  - The original extraction in `metric_extractions` is preserved for auditability.
- V1 does NOT overwrite historical parser output.

UI & Query Semantics (V1):
- UI MUST show both: Parsed Value (from metric_extractions) and Active Value (from metric_facts where is_current = true).
- Screeners and formulas MUST read only the Active Value.

#### metric_facts (queryable facts for formulas/screeners)
- id
- user_id
- stock_id
- metric_key (canonical name, e.g. `mkt.price`, `val.pe`, `val.dividend_yield`, `per_share.eps`)
- value_json (typed value; number/string/percent)
- value_numeric (nullable; numeric projection of value_json for indexing/filtering)
- unit (nullable)
- currency (nullable)
- period (nullable)
- period_type (FY / Q / TTM)
- period_end_date (YYYY-MM-DD)
- as_of_date (nullable)
- source_type (parsed / calculated / manual)
- source_ref_id (nullable; points to metric_extractions.id when parsed)
- is_current (bool; indicates the active value for a given (user_id, stock_id, metric_key, period_end_date))
- created_at
- updated_at

Note:
- `value_numeric` MUST be populated when the metric is inherently numeric.
- Screeners SHOULD rely on `value_numeric` for SQL filtering and indexes.

Normalization (V1):
- `value_numeric` MUST be stored in a normalized base unit for correct screening (e.g., USD, not “millions of USD”).
- The ingestion pipeline MUST include a normalization layer that converts Value Line display units/scales into the chosen base units before writing `metric_facts`.

#### formulas
- id
- user_id
- name
- expression
- dependencies_json (list of metric_keys referenced)
- compiled_ast_json (optional)
- created_at
- updated_at

Recalculation Triggers (V1):
- Formulas form a dependency DAG via `dependencies_json`.
- When `metric_facts` receives new/updated facts for a dependency key (parsed or manual), dependent formulas SHOULD be marked dirty and recalculated.

#### calculated_runs
- id
- user_id
- formula_id
- stock_id
- period (nullable)
- as_of_date (nullable)
- result_value_json
- is_dirty (bool)
- created_at
- updated_at

Note:
- `calculated_runs` represents execution history and recalculation state.
- The **authoritative, queryable output** of a formula MUST be written into `metric_facts` with:
  - source_type = calculated
  - metric_key = formula-defined output key
- Screeners MUST operate on `metric_facts`, not directly on `calculated_runs`.

#### stock_pools
- id
- user_id
- name
- description
- created_at

#### pool_memberships
- id
- user_id
- pool_id
- stock_id
- inclusion_type (manual / rule)
- rule_id (nullable)
- created_at

#### screening_rules
- id
- user_id
- name
- rule_json (validated rule AST; compiled to SQLAlchemy expressions, never raw SQL)
- created_at
- updated_at

#### stock_prices
- id
- stock_id
- price_date (YYYY-MM-DD)
- open
- high
- low
- close
- adj_close (nullable)
- volume (nullable)
- source
- created_at

#### price_alerts
- id
- user_id
- pool_id (nullable)
- stock_id
- target_price
- tolerance_pct
- cooldown_hours
- last_notified_at (nullable)
- is_active
- created_at
- updated_at

#### notification_settings
- id
- user_id
- channel (email)
- frequency (daily_summary)
- send_time_local (HH:MM)
- timezone
- is_enabled
- created_at
- updated_at

#### notification_events (audit log)
- id
- user_id
- event_type (daily_summary / threshold_hit)
- payload_json
- created_at

---

### Data Traceability Requirements

For every parsed metric, the system MUST store:
- document_id
- page_number
- original_text_snippet
- parser_template_id
- parser_version
- confidence_score (0–1)

This ensures full field‑level auditability and explainability.  
In V1 (Value Line only), most traceability can be satisfied by (document_id, page_number, original_text_snippet) and optional bbox_json for UI highlighting.

`original_text_snippet` is the canonical traceability field; `raw_value_text` is treated as parser output and may differ after user correction.

Confidence Strategy (V1):
- `confidence_score` is heuristic in early versions.
- The system MAY use self-consistency (multiple extraction passes) and/or a verifier step that checks extracted values against `original_text_snippet` to adjust confidence and flag items for review.

---

### F.3 Price Semantics (V1)

- Alerts are triggered using `close` price (not adj_close) unless explicitly configured.

### F.4 Alert Trigger Logic (V1)

- An alert is triggered when:
  abs(close - target_price) <= target_price * tolerance_pct
- `cooldown_hours` suppresses repeated alerts for the same stock after a trigger.
- `daily_summary` emails include:
  - all stocks currently within alert range
  - regardless of whether a threshold alert was triggered that day

---

## Appendix A: Metric Keys & Mapping Contracts (V1)

This appendix defines the authoritative contract for mapping parsed Value Line output into `metric_facts`.

### A.1 Authoritative Source

The authoritative mapping and metric semantics live in:

```
docs/metric_facts_mapping_spec.yml
```

This mapping spec MUST be treated as versioned contract code. If PRD text and the mapping spec diverge on metric semantics, the mapping spec wins (see §A).

### A.2 Metric Key Naming (Canonical)

- `metric_key` uses dotted namespaces with `snake_case` segments (e.g., `mkt.price`, `val.pe`, `per_share.eps`).
- Each segment MUST match `[a-z][a-z0-9_]*`.
- Full regex form: `^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$`.
- `metric_key` MUST NOT encode units (no `_usd`, `_pct`, `_millions`, etc.); units are expressed via `metric_facts.unit`.

### A.3 What the Mapping Spec Defines

`docs/metric_facts_mapping_spec.yml` defines (non-exhaustive):
- which parsed page JSON paths map to which canonical `metric_key`
- `period_type` and `period_end_date` sourcing/derivation rules
- unit/value normalization rules (as specified in the mapping spec)
- which value form is preferred (`value_numeric` vs `value_text` vs `value_json`)

### A.4 Template Field Keys vs Canonical Metric Keys

- The parser emits template-facing keys into `metric_extractions.field_key`.
- Ingestion builds a stable page JSON payload and maps it to `metric_facts.metric_key` via `docs/metric_facts_mapping_spec.yml`.

Legacy note:
- Earlier drafts referenced a `value_line_v1_field_map.json` approach. This is deprecated for v0.1; do not introduce new metric semantics outside the mapping spec.
---

## Appendix B: Normalization Layer Specification (V1)

This appendix defines how Value Line extracted values are normalized before being written into `metric_facts.value_numeric`.
The goal is to ensure screeners and formulas compare **like with like**, regardless of display scale (e.g., “millions”) or formatting.

### B.1 Core Rule

- `metric_facts.value_numeric` MUST be stored in a **normalized base unit** suitable for correct SQL filtering and indexing.
- Original display context is preserved via:
  - `metric_extractions.raw_value_text` / `original_text_snippet`
  - `metric_extractions.parsed_value_json` (typed, may include display scale)
  - `metric_facts.value_json` (typed, may include display metadata)

### B.2 Base Units (V1 Defaults)

**Money amounts (USD)**
- Base unit for `value_numeric`: **USD (absolute dollars)**.
- Examples:
  - “$1.2 bil.” → 1,200,000,000
  - “350 mil.” → 350,000,000

**Per-share money (USD/share)**
- Base unit for `value_numeric`: **USD per share**.
- Examples:
  - EPS “3.25” → 3.25
  - Dividend/share “0.28” → 0.28

**Shares**
- Base unit for `value_numeric`: **shares (absolute count)**.

**Market cap**
- Base unit for `value_numeric`: **USD (absolute dollars)**.

**Percentages**
- Base unit for `value_numeric`: **ratio in [0, 1]** (not 0–100).
- Example:
  - “5.2%” → 0.052

**Ratios / Multiples**
- Base unit for `value_numeric`: raw ratio number.
- Example:
  - PE “18.5” → 18.5

### B.3 Scale Detection (Display → Base)

The normalization layer MUST detect display scales from either:
- explicit unit tokens near the number (preferred), or
- known Value Line section/table conventions when tokens are absent.

Supported scale tokens (case-insensitive):
- `k`, `thousand` → × 1,000
- `m`, `mil`, `million` → × 1,000,000
- `b`, `bil`, `billion` → × 1,000,000,000
- `t`, `tril`, `trillion` → × 1,000,000,000,000

Currency tokens:
- `$` → currency = USD
- If currency is not explicitly present in the source, default to USD for Value Line (V1 assumption) and store this as metadata in `value_json`.

### B.4 Typed Value JSON Contract

The parser SHOULD emit a consistent `parsed_value_json` and `value_json` format, for example:

```json
{
  "display_value": "1.2",
  "display_unit": "bil",
  "normalized_value": 1200000000,
  "base_unit": "USD",
  "currency": "USD"
}
```

Notes:
- `metric_facts.value_numeric` MUST equal `normalized_value` for numeric metrics.
- `metric_facts.unit` SHOULD store `base_unit` (e.g., "USD", "USD/share", "ratio").
- If a metric is non-numeric (e.g., analyst name), `value_numeric` MUST be NULL.

### B.5 Screening / Query Guidance (V1)

- Screeners MUST filter on `metric_facts.value_numeric`.
- For percentage metrics, comparisons are done using the ratio base:
  - Example: val.dividend_yield > 0.03 (for > 3%)

### B.6 Validation & Guardrails

The ingestion pipeline MUST enforce guardrails:
- If a numeric metric has missing scale and cannot be inferred, mark:
  - `metric_extractions.confidence_score` lower, and/or
  - `pdf_documents.identity_needs_review = true` (if widespread ambiguity is detected)
- Store a normalization error reason in `value_json` if normalization fails.

### B.7 Future Extensions (Out of Scope for V1)

- Multi-currency normalization and FX conversion
- GAAP vs Adjusted metric reconciliation
- Unit-aware formula evaluation (dimensional analysis)
