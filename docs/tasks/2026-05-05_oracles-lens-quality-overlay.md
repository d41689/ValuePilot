# Oracle's Lens Quality Overlay

## Goal / Acceptance Criteria

- Add the next Oracle's Lens product-plan milestone: a Value Line business quality overlay for signal-ranked 13F candidates.
- API rows expose a `quality_overlay` object with Piotroski score, return on capital, ROE, net margin, debt-to-capital, owner earnings yield, coverage, and unavailable reasons.
- Dashboard coverage exposes counts for candidates with Value Line quality facts and price coverage.
- Frontend displays quality as supporting context, not as a competing primary rank.
- Missing quality or price data is explicit and non-misleading.

## Scope

In:
- Backend Oracle's Lens dashboard service.
- Backend unit tests for quality overlay payload and coverage.
- Frontend row normalization and table display.
- Frontend helper tests.

Out:
- Valuation reference strip.
- Manual intrinsic value inputs.
- AI moat score.
- Manager taxonomy expansion beyond the existing V1 heuristic.
- Database schema changes.

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

- Quality overlay values must come from `metric_facts` with `is_current = true`.
- Numeric comparisons and calculations use normalized `value_numeric`.
- The UI must keep Signal Score as the only visually dominant primary score.

## Implementation Notes

- Added backend quality overlay lookup for selected dashboard candidates.
- The overlay reads current normalized `metric_facts` for:
  - `score.piotroski.total`
  - `bs.return_on_total_capital`
  - `bs.return_on_equity`
  - `is.net_profit_margin`
  - `leverage.long_term_debt_to_capital`
  - `owners_earnings_per_share_normalized`
- Owner earnings yield is calculated only when normalized owner earnings and latest price are both present.
- Missing Value Line facts, price, and owner earnings are returned as explicit unavailable reasons.
- Frontend displays quality as a supporting table column while keeping Signal Score as the primary ranking metric.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_adds_value_line_quality_overlay` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 3 passed
- `docker compose exec web node --test lib/oraclesLens.test.js` - 4 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q` - 204 passed
- `git diff --check` - passed

## Contract Checklist

- [x] Quality overlay queries `metric_facts`, not parser JSON or `metric_extractions`.
- [x] Calculations use normalized `value_numeric`.
- [x] No raw SQL from user input.
- [x] No formula `eval` / `exec`.
- [x] `is_current = true` semantics are preserved.
- [x] Missing data is exposed as a product state instead of hidden.
