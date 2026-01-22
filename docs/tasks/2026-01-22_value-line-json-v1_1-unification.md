# Task: Value Line JSON v1.1 Breaking Unification

## Goal / Acceptance Criteria
- Unify Value Line page JSON output across AXS / AO Smith / BUD with a single **v1.1 schema** (breaking change OK).
- Golden fixtures updated:
  - `backend/tests/fixtures/value_line/axs_v1.expected.json`
  - `backend/tests/fixtures/value_line/ao_smith_v1.expected.json`
  - `backend/tests/fixtures/value_line/bud_v1.expected.json`
- Fixture tests are green in Docker:
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_parser_fixture.py`
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_bud_parser_fixture.py`
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_axs_parser.py`
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_axs_parser_time_fields.py`
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_smith_null_sections.py`
  - `docker compose exec api pytest -q backend/tests/unit/test_value_line_metric_facts_time_series.py`

## Scope
**In**
- `build_value_line_page_json` output contract changes (schema v1.1), plus fixture/test updates.

**Out**
- Database schema changes.
- PRD changes.
- Any non-Value Line template support.

## Proposed v1.1 Contract (Breaking)
### 1) Stable Top-Level Keys
- Always emit the same top-level keys; for non-applicable sections emit `null` (do not omit keys).
- Always include both revenue-style quarterly blocks:
  - `quarterly_sales` (non-insurance) OR `null`
  - `net_premiums_earned` (insurance) OR `null`
- Always include both earnings blocks:
  - `earnings_per_share` OR `null`
  - `earnings_per_adr` OR `null`
- Always include `current_position` (object or `null`).

### 2) Meta Versioning + Layout Hints
- `meta.schema_version = "1.1"`
- Add:
  - `meta.layout_id`: `"insurance"` or `"industrial"`
  - `meta.security_unit`: `"share"` or `"adr"`

### 3) Quarterly Blocks Are Time-Aware
- Quarterly blocks (`quarterly_sales`, `net_premiums_earned`, `earnings_*`, `quarterly_dividends_paid`) must always include quarter cells shaped as:
  - `{ "period_end": "YYYY-MM-DD" | null, "value": number | null }`

### 4) Narrative Always Contains Commentary Key
- `narrative.analyst_commentary` is always present (nullable).

### 5) Annual Financials Unification
- Rename `annual_financials.per_share_metrics` -> `annual_financials.per_unit_metrics`
- Add `annual_financials.per_unit`: `"share"` or `"adr"`
- Normalize per-unit metric keys by removing `_per_share/_per_adr/_usd` suffixes where applicable.
- Remove BUD-only flattened annual series; keep annual series grouped under:
  - `income_statement_usd_millions`
  - `balance_sheet_and_returns_usd_millions` (may be empty, but should exist consistently when data is present)

## Files To Change (Expected)
- `backend/app/ingestion/parsers/v1_value_line/page_json.py`
- `backend/tests/unit/test_value_line_axs_parser.py`
- `backend/tests/unit/test_value_line_smith_null_sections.py`
- `backend/tests/fixtures/value_line/axs_v1.expected.json`
- `backend/tests/fixtures/value_line/ao_smith_v1.expected.json`
- `backend/tests/fixtures/value_line/bud_v1.expected.json`

## Execution Plan (Approved)
1. Update unit tests to assert the v1.1 contract shape (red).
2. Implement v1.1 schema changes in `build_value_line_page_json` and helpers (green).
3. Regenerate fixtures by running parser against the PDFs inside Docker.
4. Update any remaining tests that reference legacy paths/keys.
5. Run the full verification set in Docker and record results here.

## Rollback Strategy
- Changes are isolated to Value Line v1 page-json builder + fixtures/tests.
- If a specific company regresses (AXS/AO/BUD), revert the smallest schema change and re-apply with a more conservative mapping.

## Contract Checklist (Fill During Verification)
- [x] No schema migrations
- [x] Screeners still query only `metric_facts` (`is_current = true`) (no screener changes in this task)
- [x] No raw SQL from user input; no eval/exec
- [x] Normalization and scale token handling unchanged
- [x] Parser output includes required lineage fields (where applicable; unchanged for metric_extractions)

## Notes / Decisions
- This is intentionally a **breaking** change to unify the JSON contract across fixtures.

## Breaking Changes (External)
This change introduces a new **Value Line page JSON schema v1.1** (breaking vs v1 fixtures).

- `meta`
  - Added: `meta.schema_version = "1.1"`
  - Added: `meta.layout_id` in `{"insurance","industrial"}`
  - Added: `meta.security_unit` in `{"share","adr"}`

- Stable top-level keys (nullable)
  - Previously some sections were conditionally omitted; in v1.1 the following keys are always present:
    - `quarterly_sales` (or `null`)
    - `net_premiums_earned` (or `null`)
    - `earnings_per_share` (or `null`)
    - `earnings_per_adr` (or `null`)
    - `current_position` (or `null`)

- Quarterly block cell shape
  - All quarterly blocks now emit quarter cells as:
    - `{ "period_end": "YYYY-MM-DD" | null, "value": number | null }`
  - This applies to `quarterly_dividends_paid` as well (previously ADR layouts omitted `period_end`).

- Narrative
  - `narrative.analyst_commentary` is always present (nullable). Previously it could be omitted.

- Annual financials
  - Renamed:
    - `annual_financials.per_share_metrics` -> `annual_financials.per_unit_metrics`
  - Added:
    - `annual_financials.per_unit` in `{"share","adr"}`
    - `annual_financials.income_statement_ratios_pct` (e.g. `income_tax_rate_pct`, `net_profit_margin_pct`)
  - Removed:
    - BUD-specific flattened annual series at the top-level of `annual_financials` (now kept grouped under `balance_sheet_and_returns_usd_millions`).

Compatibility note:
- Metric-fact mapping paths were updated to the new v1.1 JSON paths (see `docs/metric_facts_mapping_spec.yml`).

## Implementation Notes (What Changed)
- `build_value_line_page_json` now emits `meta.schema_version = "1.1"` and stable top-level keys (nullable instead of conditionally omitted).
- Quarterly blocks always include `period_end` per quarter cell (including ADR layouts).
- `narrative.analyst_commentary` is always present (nullable).
- `annual_financials` is unified:
  - `per_share_metrics` renamed to `per_unit_metrics` + `per_unit`
  - Removed BUD-only flattened annual series; balance sheet/returns stay grouped
  - Added `income_statement_ratios_pct` group (tax rate + margin series) for consistency
- Metric facts mapping spec updated to track `annual_financials.per_unit_metrics.*`.
- Mapping engine avoids emitting “estimate-only” facts when numeric/text value is missing.
- Open-world extraction spec/logic adjusted to map `total_debt` and correctly align partial year tables (BUD regression fixtures updated).

## Verification (Docker)
- `docker compose exec api pytest -q` -> **79 passed** (2026-01-22)
