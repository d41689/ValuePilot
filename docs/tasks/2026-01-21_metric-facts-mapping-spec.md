Goal / Acceptance Criteria
- Map parsed Value Line page JSON to metric_facts using `docs/metric_facts_mapping_spec.yml`.
- Log any parsed fields that are not present in the mapping spec (per-page, with path info).
- Ingestion respects period_type, period_end_date, units, and value selection per mapping spec.
- Tests cover mapping and unmapped logging behavior.

Scope (In)
- Mapping-spec driven fact extraction for Value Line parsed page JSON.
- Logging of unmapped parsed fields.
- Unit tests for mapping resolution, date derivations, and logging.
- Dependency add for YAML parsing if required.

Scope (Out)
- Parser extraction changes.
- Schema changes beyond what already exists for metric_facts.
- API changes.

PRD References
- docs/prd/value-pilot-prd-v0.1.md (Parsing Logic, Data Integrity, Metric Normalization)

Files to Change
- backend/app/services/ingestion_service.py
- backend/app/ingestion/parsers/v1_value_line/page_json.py (if aliasing paths required)
- backend/app/services/mapping_spec.py (new)
- backend/tests/unit/test_metric_facts_mapping_spec.py (new)
- backend/pyproject.toml (if YAML parser dependency needed)
- docs/tasks/2026-01-21_metric-facts-mapping-spec.md

Test Plan (Docker)
- docker compose exec -T api pytest -q backend/tests/unit/test_metric_facts_mapping_spec.py
- docker compose exec -T api pytest -q

Execution Plan
1) Confirm metric_key naming strategy (mapping spec uses dotted keys vs current snake_case constraint) and document decision.
2) Add mapping spec loader + path resolver with derivations (year_end_from_key, quarter_end_from_context, year_end_from_context, financial_position_date_from_index) and unit normalization to base units.
3) Integrate spec-driven fact extraction into ingestion (build page JSON, map to facts, log unmapped paths).
4) Add/update tests for mapping resolution, period_type handling, and unmapped logging; update any metric_key expectations.
5) Run Docker tests and record results/contract checks.

Decision: metric_key Naming & Mapping Strategy

Decision
- Adopt dotted metric_key naming (e.g. `per_share.eps`) as the canonical, long-term format.
- metric_key values are stored in the database exactly as defined in `metric_facts_mapping_spec.yml` (no transformation on write).
- This decision intentionally updates the earlier snake_case-only convention to avoid long-term technical debt and preserve semantic hierarchy.

Rationale
- Dotted namespaces encode semantic structure (e.g. per_share, ratios, income_statement) that snake_case cannot express cleanly.
- Avoids lossy or ambiguous transformations (`eps`, `earnings_per_share`, `per_share_eps`).
- Aligns DB, mapping spec, analytics, and future APIs on a single canonical vocabulary.
- Project is in early development; changing the convention now minimizes long-term migration risk.

Database / Engineering Constraints
- metric_key MUST match the regex:
  ^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$
- No leading/trailing dots; no consecutive dots.
- metric_key column SHOULD be indexed.
- Any display/export layer that requires snake_case must convert from dotted form at the boundary (never persisted back).

Mapping Spec Contract
- `docs/metric_facts_mapping_spec.yml` is the source of truth for metric_key naming.
- Ingestion code must validate metric_key values against the above constraints before insert.
- Tests must assert dotted metric_key values end-to-end.

Alias / Compatibility Strategy
- Parsed page JSON path mismatches (e.g. `header.report_date` vs `meta.report_date`,
  `text_blocks.*` vs `narrative.*`, `net_profit_usd_millions` vs `net_profit`)
  are handled via an alias layer in the mapping resolver.
- Parser output is NOT modified.
- Mapping layer resolves aliases before applying spec rules.
- All resolved facts are written using canonical metric_key only.

Non-Goals
- No backward compatibility for legacy snake_case metric_key values.
- No automatic migration of historical data (database currently assumed clean).

Acceptance Criteria (Updated)
- All metric_facts rows use dotted metric_key values.
- No snake_case-only metric_key values are introduced by ingestion.
- Unit tests cover validation, alias resolution, and failure on invalid metric_key.

Notes
- Updated `docs/metric_facts_mapping_spec.yml` paths to match current page JSON (meta.report_date, narrative.*, capital_structure.*.normalized, target_price_18m/scenarios).
- Removed mappings that referenced non-existent page JSON sections (rates_of_change, insurance_operating_statistics).
- Re-added rates_of_change via `annual_rates.metrics[]` with dynamic metric_key_template; restored insurance_operating_statistics mappings for union coverage.

Progress Update
- Fixed mapping-spec path walker to recognize list tokens (`[]`) and parse period_end_date from `from:` paths.
- Normalized unmapped-path regex handling for list indices/projection labels.
- Added nullable support for `metric_facts.value_json` (new migration) to allow value_text-only facts.

Verification
- `docker compose exec -T api alembic upgrade head`
- `docker compose exec -T api pytest -q`
