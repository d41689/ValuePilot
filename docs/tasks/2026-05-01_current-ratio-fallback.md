# Current Ratio Fallback

## Goal / Acceptance Criteria

- `score.piotroski.current_ratio_improving` still prefers reusable `liquidity.current_ratio` facts when available.
- If `liquidity.current_ratio` is missing, calculate the comparison directly from `bs.current_assets / bs.current_liabilities` for current and prior fiscal years.
- The fallback must require positive current liabilities in both periods to avoid invalid ratio calculations.
- Dynamic F-Score formula metadata must show the Current Position fallback formula.

## Scope

In:
- Backend Piotroski F-Score fallback calculation.
- Unit tests for direct Current Position fallback and standard-priority behavior.
- Summary API formula metadata.
- Calculation plan documentation.

Out:
- Parser changes.
- Database schema changes.
- Backfill/recalculation job implementation for existing stored facts.

## Files to Change

- `backend/app/services/calculated_metrics/piotroski_f_score.py`
- `backend/tests/unit/test_piotroski_f_score.py`
- `backend/app/api/v1/endpoints/stocks.py`
- `docs/plans/piotroski_f_score_calculation_plan.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_piotroski_f_score.py`
- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`

## Notes

- 2026-05-01: Started implementation. Existing code only compares precomputed `liquidity.current_ratio`; fallback should compute the same ratio directly from Current Position totals when the derived ratio fact is absent.
- 2026-05-01: Added failing tests for Current Position fallback, standard ratio priority, and zero-liability guard behavior.
- 2026-05-01: Implemented direct `bs.current_assets / bs.current_liabilities` comparison fallback, with positive-liability guards, and exposed the fallback formula in summary metadata.
- 2026-05-01: Verification passed:
  - `docker compose exec api pytest -q tests/unit/test_piotroski_f_score.py`
  - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`

## Contract Checklist

- [x] `metric_facts` remains the source of queryable facts.
- [x] Numeric comparisons use normalized `value_numeric` facts.
- [x] No raw SQL from user input.
- [x] No eval/exec formula execution.
- [x] Lineage inputs are preserved in calculated score facts.
- [x] `is_current` semantics are unchanged.
