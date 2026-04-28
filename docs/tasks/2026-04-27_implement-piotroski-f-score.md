# Implement Value Line-adjusted Piotroski F-Score

## Goal / Acceptance Criteria
- Implement the Value Line-adjusted Piotroski F-Score plan in `docs/plans/piotroski_f_score_calculation_plan.md`.
- Generate reusable calculated ratio facts from active `metric_facts` where inputs are available.
- Generate Piotroski component facts and total/partial diagnostic facts with lineage, variant, method, calculation version, estimate semantics, and deterministic fallback priority.
- Keep parsed/manual facts immutable and reconcile only calculated current facts.
- Integrate recalculation after Value Line parsed facts are inserted.

## Scope
In:
- Backend calculated metric services.
- Focused tests for pure ratio calculation, pure F-Score calculation, DB insertion/current reconciliation, and ingestion integration.
- Minimal mapping-spec alignment only where existing mapped facts already expose required values.

Out:
- UI exposure.
- TTM F-Score, trend scoring, Guru Score integration, thresholds, anomaly radar, and bank-specific scoring.
- Schema changes unless tests prove existing columns cannot carry required metadata.

## Files to Change
- `backend/app/services/calculated_metrics/value_line_ratios.py`
- `backend/app/services/calculated_metrics/piotroski_f_score.py`
- `backend/app/services/ingestion_service.py`
- `backend/app/services/mapping_spec.py`
- Relevant backend tests under `backend/tests/unit/`
- This task log

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_value_line_ratios.py`
- `docker compose exec api pytest -q tests/unit/test_piotroski_f_score.py`
- `docker compose exec api pytest -q tests/unit/test_ingestion.py`
- Broader targeted backend unit tests if touched contracts require it.

## Contract Checks
- Screeners continue to use `metric_facts` and numeric comparisons on `value_numeric`.
- Numeric total facts are only emitted for complete calculated totals.
- Partial total facts use `value_numeric = null`.
- No raw SQL from user input.
- No `eval` / `exec`.
- Calculated facts include lineage metadata and preserve active value semantics.

## Progress Notes
- 2026-04-27: Created implementation task before production code changes.
- 2026-04-27: Added pure ratio tests and pure/DB Piotroski tests first.
- 2026-04-27: Implemented `ValueLineRatioCalculator` for ROA, current ratio, LT debt/assets, asset turnover, and insurance premium turnover.
- 2026-04-27: Implemented `PiotroskiFScoreCalculator` with deterministic standard/proxy/insurance methods, component facts, complete totals, and partial diagnostic totals.
- 2026-04-27: Integrated calculation after Value Line parsed facts are inserted and after document review manual corrections.
- 2026-04-27: Added upload integration coverage for AXS insurance-adjusted partial diagnostic totals.
- 2026-04-27: Updated mapping period derivation so FY facts use `annual_financials.meta.fiscal_year_end_month` when available instead of hardcoding December 31.

## Verification
- `docker compose exec api pytest -q tests/unit/test_value_line_ratios.py tests/unit/test_piotroski_f_score.py` -> pass (`8 passed`).
- `docker compose exec api pytest -q tests/unit/test_value_line_metric_facts_time_series.py::test_value_line_upload_creates_piotroski_partial_diagnostic_fact tests/unit/test_value_line_ratios.py tests/unit/test_piotroski_f_score.py` -> pass (`9 passed`).
- `docker compose exec api pytest -q tests/unit/test_value_line_metric_facts_time_series.py tests/unit/test_documents_api.py::test_document_review_correction_creates_manual_current_fact_without_mutating_extraction tests/unit/test_ingestion.py tests/unit/test_reparse_existing_document.py` -> pass (`26 passed`).
- `docker compose exec api pytest -q tests/unit/test_metric_facts_mapping_spec.py tests/unit/test_value_line_metric_facts_time_series.py::test_quarterly_series_full_year_facts_are_written tests/unit/test_value_line_metric_facts_time_series.py::test_value_line_upload_creates_piotroski_partial_diagnostic_fact` -> pass (`4 passed`).
- `docker compose exec api pytest -q tests/unit` -> pass (`141 passed`).

## Contract Gate
- `metric_facts` remains the only queryable source for ratio and F-Score inputs/outputs.
- Numeric screeners can use complete `score.piotroski.total` rows because partial totals keep `value_numeric = null`.
- Calculated facts include `value_json.inputs`, `variant`, `method`, `calculation_version`, `status`, and `fact_nature`.
- FY facts use Value Line fiscal year-end metadata when available.
- No raw SQL from user input was added.
- No `eval` / `exec` was added.
- Parsed/manual facts are not mutated by the calculators; only prior current calculated rows for the same slot are deactivated.
