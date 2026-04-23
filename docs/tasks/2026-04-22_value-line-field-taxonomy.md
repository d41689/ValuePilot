# Task: Define explicit Value Line field taxonomy contract

## Goal / Acceptance Criteria
- Introduce an explicit Value Line field taxonomy contract that classifies key parsed fields by semantic type.
- Cover the main Value Line fields currently used by parser/page-json/mapping flows, including:
  - annual financials
  - quarterly blocks
  - ratings
  - target price
  - total return
  - valuation metrics
  - commentary
- Add tests that validate the taxonomy contract and prove current mapping/parser outputs align with it.
- Use the taxonomy in at least one production validation path so field semantics are no longer defined only by scattered code heuristics.

## Scope
**In**
- New taxonomy contract file(s) for Value Line semantic classification.
- Targeted tests for taxonomy coverage and consistency with existing parser/mapping outputs.
- Minimal production integration that reads or validates against the taxonomy.

**Out**
- Cross-source resolver implementation.
- SEC taxonomy implementation.
- Broad UI changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Value Line parser scope and normalized storage
- `AGENTS.md` -> task logging, Docker-only verification, lineage and safety rules

## Files To Change
- `docs/tasks/2026-04-22_value-line-field-taxonomy.md` (this file)
- `docs/value_line_field_taxonomy.yml` (new, if separate contract is cleaner)
- `backend/app/services/mapping_spec.py`
- `backend/tests/unit/test_value_line_field_taxonomy.py`
- `backend/tests/unit/test_metric_facts_mapping_spec.py`
- `backend/tests/unit/test_value_line_metric_facts_time_series.py`
- `backend/tests/unit/test_value_line_annual_facts.py`
- `backend/tests/unit/test_screener_api_metrics.py`
- Other minimal parser/mapping files only if needed for contract integration

## Execution Plan (Assumed approved per direct request)
1. Review current mapping spec and parser semantic decisions to identify the minimum taxonomy surface.
2. Add a failing taxonomy contract test.
3. Create the taxonomy contract file and wire minimal production validation/integration to it.
4. Update tests to assert current parser/mapping semantics align with the taxonomy.
5. Run Docker-based verification and record outcomes.

## Contract Checks
- No changes to metric lineage or storage layers beyond taxonomy validation/integration.
- No resolver or precedence logic in this task.
- No raw SQL or unsafe evaluation changes.

## Rollback Strategy
- Revert the taxonomy contract file and its validation hooks.
- Revert associated tests.

## Progress Log
- [x] Review existing mapping/spec structure.
- [x] Add failing taxonomy tests.
- [x] Implement taxonomy contract + minimal integration.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Kept the taxonomy as a separate YAML contract instead of embedding it into `metric_facts_mapping_spec.yml`, so semantic classification stays explicit and reviewable.
- `MappingSpec.load()` now auto-loads `docs/value_line_field_taxonomy.yml` when present and merges mapping-level `fact_nature` / `fact_nature_rule` into the mapping spec.
- Static semantics now come from taxonomy for fields like market snapshot metrics, ratings, target prices, long-term projections, and commentary.
- Dynamic annual/quarterly statement fields use explicit taxonomy rules (`context_only` / `context_or_annual_meta`) instead of leaving those semantics implicit in scattered code.
- The taxonomy currently focuses on the active Value Line surface. It does not yet define multi-source precedence or SEC semantics.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_value_line_field_taxonomy.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_field_taxonomy.py tests/unit/test_metric_facts_mapping_spec.py tests/unit/test_value_line_metric_facts_time_series.py tests/unit/test_value_line_annual_facts.py tests/unit/test_screener_api_metrics.py`
- `docker compose exec api pytest -q`

All passed. Final full API test run: `113 passed in 18.05s`.
