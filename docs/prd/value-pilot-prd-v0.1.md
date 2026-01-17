> **Note**: This document is the consolidated PRD for ValuePilot v0.1.  
> Sections A–G, database schema, and milestones are intentionally kept in a single file for execution clarity.

## B.4 Parsing Boundary (Explicit Scope)

- V1 parsing is **template‑based**, not generic.
- **V1 supports Value Line equity report PDFs only** (the single‑page standard layout).
- Any non‑Value Line PDFs can still be uploaded and stored but will be marked as `unsupported_template`.

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
- 2028_2030_projection_high_price, projection_low_price
- 2028_2030_projection_high_total_return_pct, projection_low_total_return_pct

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

### Canonical Metric Key Rules (V1)

- All `metric_key` values MUST:
  - use `snake_case`
  - NOT start with a number
- Template field names are mapped to canonical keys, e.g.:
  - `18_month_target_low` → `target_18m_low`
  - `18_month_target_high` → `target_18m_high`
  - `relative_pe_ratio` → `pe_ratio_relative`
- Only canonical keys are exposed to formulas and screeners.

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
- `pdf_documents` and downstream metrics are linked to stocks via `stock_id`.

#### pdf_documents
- id
- user_id
- file_name
- source (e.g. Value Line)
- upload_time
- file_storage_key (store original PDF; text can be regenerated)
- parse_status (pending / parsed / failed / unsupported_template / requires_ocr)
- parser_template_id (nullable)
- parser_version
- raw_text (optional cache)
- notes

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
- text_extraction_method (native_text / ocr)

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

#### metric_facts (queryable facts for formulas/screeners)
- id
- user_id
- stock_id
- metric_key (canonical name, e.g. "pe_ratio", "dividend_yield", "sales", "eps")
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
- created_at
- updated_at

Note:
- `value_numeric` MUST be populated when the metric is inherently numeric.
- Screeners SHOULD rely on `value_numeric` for SQL filtering and indexes.

#### formulas
- id
- user_id
- name
- expression
- dependencies_json (list of metric_keys referenced)
- compiled_ast_json (optional)
- created_at
- updated_at

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

---

### F.3 Price Semantics (V1)

- Alerts are triggered using `close` price (not adj_close) unless explicitly configured.