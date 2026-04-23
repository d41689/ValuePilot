# Task: Preserve Value Line fact nature semantics in parser outputs

## Goal / Acceptance Criteria
- Value Line parser/page JSON preserves whether a parsed value is a snapshot, opinion, actual, estimate, or mixed section.
- Annual and quarterly time-series outputs correctly distinguish actual years from estimate years for at least:
  - calendar-year companies like `AXS`
  - non-December fiscal-year companies like `CALM`
- Ingestion-derived annual and quarterly `metric_facts` inherit improved estimate semantics instead of assuming only the last annual year is estimated.

## Scope
**In**
- Parser and page-json semantic metadata for key Value Line sections.
- Improved fiscal-year-end handling for quarterly and annual estimate boundaries.
- Ingestion changes needed to carry annual/quarterly estimate semantics into parsed facts.
- Targeted fixture/test updates for affected Value Line outputs.

**Out**
- Cross-source canonical resolver design or implementation.
- SEC ingestion changes.
- Full taxonomy/resolver rollout across all UI/query consumers.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Value Line parser scope and normalized storage
- `AGENTS.md` -> task logging, Docker-only verification, lineage and safety rules

## Files To Change
- `docs/tasks/2026-04-22_value-line-fact-nature.md` (this file)
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/ingestion/parsers/v1_value_line/page_json.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/services/mapping_spec.py`
- `backend/tests/unit/test_value_line_axs_parser_time_fields.py`
- `backend/tests/unit/test_value_line_calm_parser_fixture.py`
- `backend/tests/unit/test_value_line_metric_facts_time_series.py`
- `backend/tests/fixtures/value_line/*.expected.json` (affected fixtures only)

## Execution Plan (Assumed approved per direct request)
1. Add failing parser/page-json and fact-ingestion tests for semantic tagging and estimate boundaries.
2. Implement fiscal-year-end aware estimate boundary helpers and semantic tags in parser/page-json.
3. Propagate estimate/fact-nature metadata into annual/quarterly fact expansion.
4. Update affected expected fixtures to the new parser contract.
5. Run Docker-based verification and record outcomes.

## Contract Checks
- Parsed lineage remains immutable.
- No screener/formula canonical-resolution changes in this task.
- No raw SQL or unsafe evaluation changes.
- Parsed facts keep document/page lineage while gaining better semantic tags.

## Rollback Strategy
- Revert parser/page-json semantic metadata additions.
- Revert estimate-boundary heuristics.
- Revert updated fixtures and tests.

## Progress Log
- [x] Add failing tests.
- [x] Implement parser/page-json semantic metadata.
- [x] Propagate improved estimate semantics into fact expansion.
- [x] Update affected fixtures.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Initial review found that quarterly blocks already carry `is_estimated`, but annual tables do not preserve estimate boundaries consistently.
- Current heuristics also fail for non-December fiscal-year quarter tables because month-order detection is hard-coded to `Mar/Jun/Sep/Dec`.
- Added a shared `semantics.py` helper so parser, page JSON, and fact expansion use the same fiscal-year-end and estimate-boundary rules.
- Quarterly parser output now stores `q1..q4`, `quarter_month_order`, and `fiscal_year_end_month` instead of assuming calendar-quarter labels.
- `annual_financials.meta` now keeps backward-compatible `historical_years` while adding explicit `actual_years`, `estimate_years`, `fiscal_year_end_month`, and `fact_nature="mixed"`.
- Key top-level sections now preserve source semantics: header and total return as `snapshot`; ratings, target price, long-term projection, and narrative as `opinion`.
- Ingestion now propagates `fact_nature` / `is_estimate` into annual and quarterly parsed facts so downstream logic does not have to infer estimate semantics from the last year heuristic.
- Follow-up convergence completed: page JSON no longer emits redundant quarterly/full-year `is_estimated`; consumers now rely on `fact_nature` instead.
- Updated affected Value Line expected fixtures to the new page JSON contract after parser behavior stabilized.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_value_line_axs_parser_time_fields.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_calm_parser_fixture.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_metric_facts_time_series.py`
- `docker compose exec api sh -lc 'pytest -q $(find tests/unit -maxdepth 1 -name "test_value_line*.py" | sort)'`
- `docker compose exec api pytest -q`

All passed. Final full API test run: `111 passed in 19.50s`.

Second-pass convergence verification:
- `docker compose exec api pytest -q tests/unit/test_value_line_axs_parser_time_fields.py tests/unit/test_value_line_calm_parser_fixture.py`
- `docker compose exec api pytest -q tests/unit/test_value_line_metric_facts_time_series.py tests/unit/test_value_line_annual_facts.py`
- `docker compose exec api pytest -q`

All passed. Final full API test run after removing `is_estimated` from page JSON: `111 passed in 17.98s`.
