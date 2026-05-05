# Oracle's Lens V1 Filters

## Goal / Acceptance Criteria

- Add V1 dashboard filters from the product plan.
- UI exposes a visible `Superinvestors only` noise filter.
- UI exposes period, minimum holders, and minimum signal score controls using shared UI components.
- API requests include filter query parameters.
- Filter copy must reinforce research-candidate language, not trading signals.

## Scope

In:
- Frontend query parameter helper.
- Frontend helper tests.
- Oracle's Lens page filter controls.

Out:
- Long-term / concentrated manager taxonomy toggle.
- Bubble chart.
- Historical time-machine visualization.
- Backend changes.

## Files To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`

## Notes

- Use existing endpoint query params rather than adding a new backend contract.
- Keep defaults aligned with backend defaults.

## Implementation Notes

- Added `buildOracleLensQueryParams` helper for V1 filter serialization.
- Added filter controls to the Oracle's Lens page:
  - period
  - minimum holders
  - minimum signal score
  - `Superinvestors only` noise filter
- Query key now includes serialized filter state so React Query refreshes candidates when filters change.
- Filter copy keeps the dashboard framed as research candidates rather than investment recommendations.

## Verification

- `docker compose exec web node --test lib/oraclesLens.test.js` - 8 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 5 passed
- `git diff --check` - passed

## Contract Checklist

- [x] No backend contract or schema changed.
- [x] Existing backend query params are used.
- [x] Shared `Input`, `Checkbox`, and `Button` components are used.
- [x] UI copy avoids buy-signal language.
