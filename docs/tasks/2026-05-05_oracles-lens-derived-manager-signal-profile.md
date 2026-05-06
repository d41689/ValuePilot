# Oracle's Lens Derived Manager Signal Profile

## Goal / Acceptance Criteria

- Implement the product document's minimal V1 manager signal profile from available 13F behavior.
- Do not hardcode manager-name exclusions.
- Derive manager type from portfolio concentration, holding persistence, and turnover proxy where explicit metadata is unavailable.
- Unknown managers remain visible and receive neutral/reduced weight.
- API holder details expose derived profile fields so UI can explain signal quality.

## Scope

In:
- Backend manager signal profile helper.
- Oracle's Lens dashboard scoring integration.
- Backend unit tests for derived profile behavior.
- Frontend drilldown display of manager profile fields.

Out:
- Schema changes.
- Manual manager taxonomy admin UI.
- Name-based quant/index exclusions.
- Backtested historical style relevance.

## Files To Change

- `backend/app/services/oracles_lens/manager_signal.py`
- `backend/app/services/oracles_lens/dashboard.py`
- `backend/tests/unit/test_oracles_lens.py`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec api pytest -q`

## Notes

- This is a derived V1 profile, not a definitive taxonomy.
- Future V2 can replace or refine it with persisted metadata.

## Implementation Notes

- Added `app/services/oracles_lens/manager_signal.py`.
- Derived manager profile inputs:
  - portfolio concentration from current 13F position weights
  - portfolio holding count
  - average holding period from current holdings' streaks
  - turnover proxy
- Derived manager types:
  - `value_concentrated`
  - `long_term_fundamental`
  - `high_turnover`
  - `unknown`
- Integrated derived profile into signal scoring and top holder payload.
- Frontend holder drilldown now shows manager type, portfolio concentration, average holding period, and profile source.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_defaults_to_latest_complete_period_and_signal_rows` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 6 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec web node --test lib/oraclesLens.test.js` - 10 passed
- `docker compose exec api pytest -q` - 209 passed
- `git diff --check` - passed

## Contract Checklist

- [x] No hardcoded manager-name exclusions.
- [x] No schema migration.
- [x] Unknown managers remain visible.
- [x] Derived profiles are labeled with `derived_13f_behavior`.
- [x] High-turnover managers are downweighted.
