# Oracle's Lens Sort Control

## Goal / Acceptance Criteria

- Expose the Oracle's Lens API `sort` query parameter in the dashboard UI.
- Users can sort by signal score, conviction, add intensity, aggregate weight, or distinctive consensus.
- Default remains `signal_weighted_consensus`.
- Sorting is framed as research ordering, not opportunity ranking.

## Scope

In:
- Frontend query-param helper.
- Frontend helper tests.
- Oracle's Lens filters panel.

Out:
- Backend changes.
- New sort algorithms.
- Persisted user preferences.

## Files To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`

## Notes

- Use the existing backend sort values documented in the product plan.

## Implementation Notes

- Added `sort` to `buildOracleLensQueryParams`.
- Added a shared `Select` control in the filters panel.
- Supported sort values:
  - `signal_weighted_consensus`
  - `conviction`
  - `distinctive_consensus`
  - `add_intensity`
  - `aggregate_weight`
- Reset restores the primary Signal Score sort.

## Verification

- `docker compose exec web node --test lib/oraclesLens.test.js` - 10 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 6 passed
- `git diff --check` - passed

## Contract Checklist

- [x] No backend contract changed.
- [x] Sort values match the existing API plan.
- [x] UI copy avoids opportunity-ranking language.
