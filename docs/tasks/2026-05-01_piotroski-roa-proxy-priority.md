# Piotroski ROA Proxy Priority

## Goal / Acceptance Criteria

- `score.piotroski.roa_positive` uses `returns.roa[Y] > 0` when true ROA is available.
- When true ROA is unavailable, `score.piotroski.roa_positive` prefers `returns.total_capital[Y] > 0` before falling back to `is.net_income[Y] > 0`.
- `score.piotroski.roa_improving` remains limited to true ROA first, then `returns.total_capital` as the Value Line proxy. It must not fall back to raw net income growth.
- Formula documentation matches the implemented priority.

## Scope

In:
- Backend Piotroski F-Score calculation priority.
- Unit tests for ROA proxy precedence.
- Calculation plan documentation for the ROA positive rule.

Out:
- Database schema changes.
- Recalculation job implementation for already stored facts.
- UI layout changes.

## Files to Change

- `backend/app/services/calculated_metrics/piotroski_f_score.py`
- `backend/tests/unit/test_piotroski_f_score.py`
- `docs/plans/piotroski_f_score_calculation_plan.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_piotroski_f_score.py`

## Notes

- 2026-05-01: Started implementation. The intended behavior is to keep ROA improvement on return-ratio inputs only, while making ROA positive prefer the same Value Line return-ratio proxy before the weaker net-income sign fallback.
- 2026-05-01: Added a failing unit test proving `ROA > 0` should choose `returns.total_capital` before `is.net_income` when true ROA is unavailable.
- 2026-05-01: Updated `score.piotroski.roa_positive` candidate order and aligned the calculation plan documentation.
- 2026-05-01: Verification passed:
  - `docker compose exec api pytest -q tests/unit/test_piotroski_f_score.py`
  - `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`

## Contract Checklist

- [x] `metric_facts` remains the source of queryable facts.
- [x] Numeric comparisons still use normalized `value_numeric` inputs.
- [x] No raw SQL from user input.
- [x] No eval/exec formula execution.
- [x] Lineage metadata behavior is unchanged.
- [x] `is_current` semantics are unchanged.
