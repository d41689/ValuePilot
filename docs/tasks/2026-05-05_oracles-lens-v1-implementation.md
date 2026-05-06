# Oracle's Lens V1 Implementation

## Goal / Acceptance Criteria
- Implement the first usable Oracle's Lens V1 slice from `docs/plans/13f_oracles_lens_dashboard_product_plan.md`.
- Deliver a backend aggregate endpoint for signal-ranked 13F research candidates.
- Deliver a table-first frontend page that shows the fixed 13F delay notice, coverage, primary Signal Score, explanations, score confidence, and grouped caution flags.
- Keep V1 scoped: no Value Line quality overlay, no valuation strip, no bubble chart, no historical time-machine.

## Scope
- In:
  - 13F coverage selection.
  - Raw consensus rows.
  - Minimal manager signal profile using existing data and derived proxies.
  - Holding streak calculations.
  - Signal-weighted consensus score.
  - Capped conviction score components.
  - Score confidence.
  - Grouped caution flags.
  - Dashboard API and frontend table page.
- Out:
  - Schema changes unless strictly required.
  - Full manager taxonomy workflow.
  - Value Line quality overlay.
  - Valuation reference strip.
  - Bubble chart.
  - Price/history expansion.

## Files to Change
- `backend/app/services/oracles_lens/*`
- `backend/app/api/v1/endpoints/oracles_lens.py`
- `backend/app/api/v1/api.py`
- Backend tests under `backend/tests/unit/`
- Frontend route/components/libs for `/13f/oracles-lens`

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- Broader API/frontend tests if shared routes or components are affected.

## Notes
- 2026-05-05: Starting with M1/M2 V1 implementation. The implementation must keep 13F limitations visible and must not expose cost-basis or buy-signal copy.
- 2026-05-05: Added backend Oracle's Lens aggregate service and `/api/v1/13f/oracles-lens` endpoint.
- 2026-05-05: Implemented latest-complete-period selection, raw consensus, derived manager signal weighting, holding streaks, score confidence, score explanations, and grouped caution flags without schema changes.
- 2026-05-05: Added table-first frontend route `/13f/oracles-lens` with fixed 13F delay notice, coverage cards, visually primary Signal Score, explanation chips, confidence badge, and primary caution flags.
- 2026-05-05: Added navigation entry under the dashboard shell.

## Verification
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` passed: 2 passed.
- `docker compose exec api pytest -q` passed: 203 passed.
- `docker compose exec web node --test lib/oraclesLens.test.js` passed: 3 passed.
- `docker compose exec web npm run lint` passed.
- `git diff --check` passed.
