# Project Context
**ValuePilot v0.1** is a financial analysis engine designed to parse, store, and analyze equity reports.
The v0.1 scope is strictly limited to **Value Line equity report PDFs** (single-page standard layout).
The system focuses on precise data extraction, strict data lineage (audit trails), and normalized storage for screening and formulas.

# Tech Stack
- **Language**: Python 3.10+
- **Database**: PostgreSQL (Relational, strictly typed)
- **ORM**: SQLAlchemy (Screening rules are compiled to SQLAlchemy expressions)
- **Parsing**: Template-based extraction (PDF text layer first, OCR fallback)
- **Data Exchange**: JSON for semi-structured data (`parsed_value_json`, `rule_json`)

# Architecture & Data Modeling Principles

## 1. The "Three-Layer" Storage Pattern
We strictly separate raw artifacts, extraction lineage, and queryable facts.
1.  **`pdf_documents`**: Stores the file and metadata.
2.  **`metric_extractions`**: The **Audit Trail**. Stores exactly what the parser found (raw text, snippets, page numbers). **NEVER** query this table for screeners.
3.  **`metric_facts`**: The **Source of Truth**. Stores normalized, queryable data (numeric values, canonical keys). **ALWAYS** use this table for screeners, formulas, and UI display.

## 2. Stock Identity Resolution
- **Stocks are Global Master Data**.
- **Ingestion Logic**:
  1. Match by `ticker` + `exchange`.
  2. If matched, compare `company_name` similarity.
  3. If similarity is low, set `pdf_documents.identity_needs_review = true`. **DO NOT** auto-link without confirmation.

## 3. Metric Normalization (Critical)
All data written to `metric_facts.value_numeric` MUST be normalized to base units.
- **Currency**: Absolute amounts (e.g., "1.2 bil" -> `1,200,000,000`).
- **Percentages**: Ratios between 0 and 1 (e.g., "5.2%" -> `0.052`).
- **Prices/Per Share**: Absolute currency (e.g., EPS 3.25 -> `3.25`).
- **Scale Tokens**: Handle `k`, `m`/`mil`, `b`/`bil`, `t`/`tril` case-insensitively.

# Business Rules & Constraints

## Parsing Logic
- **Scope**: Only support "Value Line" templates for v0.1. Mark others as `unsupported_template`.
- **Strategy**: Try Native Text Layer -> If density low -> Fallback to OCR.
- **Mapping**: Map template-specific field names (e.g., `18_month_target_low`) to **Canonical Metric Keys** (e.g., `target_18m_low`).
  - Refer to `value_line_v1_field_map.json` for authoritative mappings.

## Data Integrity
- **Immutability**: parsed records in `metric_extractions` are **immutable**.
- **Corrections**: If a user corrects a value:
  1. DO NOT update `metric_extractions`.
  2. Insert a NEW row into `metric_facts` with `source_type = 'manual'` and `is_current = true`.
  3. Set previous fact's `is_current = false`.

## Formulas & Screeners
- **Dependency**: Formulas form a DAG (Directed Acyclic Graph).
- **Trigger**: When a `metric_fact` is updated/inserted, trigger recalculation for dependent formulas.
- **Filtering**: Screeners MUST use `value_numeric` fields, not JSON fields.

# Coding Standards

## Naming Conventions
- **Metric Keys**: `snake_case` ONLY. NO leading numbers. (e.g., `target_18m_low`, not `18m_target`).
- **Tables**: `snake_case` plural (e.g., `metric_facts`, `stock_pools`).

## Error Handling
- **Normalization Failures**: If a value cannot be normalized (e.g., unknown unit), store the `raw_value` in JSON but leave `value_numeric` as `NULL`. Flag specific error metadata.
- **Traceability**: Every parsed metric MUST include `document_id`, `page_number`, and `original_text_snippet`.

# Interactive Verification (Agent Instructions)
- When generating SQL queries for screeners, ALWAYS verify you are querying `metric_facts` and filtering on `is_current = true`.
- When writing parsing logic, ALWAYS double-check if the extracted value contains scale suffixes (mil, bil) before saving to the database.