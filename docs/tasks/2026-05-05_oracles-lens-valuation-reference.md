# Oracle's Lens Valuation Reference

## Goal / Acceptance Criteria

- Add the next Oracle's Lens milestone: conservative valuation reference fields for each 13F research candidate.
- API rows expose holder price estimate range, current price, selected valuation reference, reference type, confidence, discount-to-reference, and unavailable reasons.
- Value Line `target.price_18m.mid` must be labeled as an analyst target reference, not intrinsic value.
- Manual `val.fair_value` facts may act as a user-entered valuation reference when present, but UI copy must still say valuation reference.
- Frontend displays valuation reference as supporting context and avoids buy-signal language.

## Scope

In:
- Backend Oracle's Lens dashboard service.
- Backend unit tests for valuation reference payload priority and calculations.
- Frontend row normalization and table display.
- Frontend helper tests.

Out:
- New database schema.
- DCF model persistence.
- Real transaction-cost inference.
- Side-panel drilldown.
- Any wording such as `below fair value`, `margin of safety`, or `guru cost basis`.

## Files To Change

- `backend/app/services/oracles_lens/dashboard.py`
- `backend/tests/unit/test_oracles_lens.py`
- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec api pytest -q`

## Notes

- Holder price estimate is derived from reported 13F value and shares, which is a quarter-end reported-value proxy, not an actual transaction price.
- Value Line `target.price_18m.mid` is an opinion/analyst target reference, not intrinsic value.
- Missing price or missing valuation reference must be explicit.

## Implementation Notes

- Added holder price estimate low/high from each selected 13F holding's reported value divided by shares.
- Added selected valuation reference priority:
  - manual current `val.fair_value` fact with `source_type = manual`
  - current Value Line `target.price_18m.mid` fact
- Manual references are labeled `User-entered valuation reference`.
- Value Line targets are labeled `Value Line 18-month target midpoint` with `analyst_target_reference` type and `medium` confidence.
- Added current price, discount-to-reference, valuation states, and explicit unavailable reasons.
- Frontend displays valuation as supporting context using conservative copy: `Valuation Ref.`, `Discount to ref`, and `Below selected reference`.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_adds_conservative_valuation_reference tests/unit/test_oracles_lens.py::test_oracles_lens_labels_value_line_target_as_reference_not_intrinsic_value` - 2 passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 5 passed
- `docker compose exec web node --test lib/oraclesLens.test.js` - 5 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q` - 206 passed
- `git diff --check` - passed

## Contract Checklist

- [x] Valuation facts are read from `metric_facts` with `is_current = true`.
- [x] Calculations use normalized `value_numeric`.
- [x] Holder estimate is explicitly a 13F reported-value proxy, not a transaction price.
- [x] Value Line target is not labeled intrinsic value or fair value in Oracle's Lens UI.
- [x] No raw SQL from user input.
- [x] No formula `eval` / `exec`.
