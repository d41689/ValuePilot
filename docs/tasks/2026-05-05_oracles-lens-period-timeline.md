# Oracle's Lens Period Timeline

## Goal / Acceptance Criteria

- Add Milestone 5 historical snapshot navigation foundation.
- API exposes available 13F periods with selected/latest markers and manager coverage.
- Frontend period filter uses the API period timeline instead of free-form text where available.
- Selecting a period refreshes the dashboard through the existing `period` query parameter.
- UI copy keeps historical period selection framed as snapshot review, not real-time intelligence.

## Scope

In:
- Backend Oracle's Lens dashboard service.
- Backend unit tests for period timeline payload.
- Frontend period selector control.

Out:
- EOD price backfill job.
- New price provider integration.
- Historical chart/timeline visualization.
- Database schema changes.

## Files To Change

- `backend/app/services/oracles_lens/dashboard.py`
- `backend/tests/unit/test_oracles_lens.py`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec api pytest -q`

## Notes

- This is the first Milestone 5 slice. It does not fetch external market data.
- Historical snapshot behavior uses the existing backend `period` query parameter.

## Implementation Notes

- Added `periods` to the Oracle's Lens API response.
- Each period includes:
  - label
  - period end date
  - manager count
  - selected marker
  - latest-complete marker
- Empty dashboard responses return an empty period list.
- Frontend period filter now uses the timeline as a `Select` when period options are available.
- Selecting a period continues to call the existing `period` query parameter.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_defaults_to_latest_complete_period_and_signal_rows tests/unit/test_oracles_lens.py::test_oracles_lens_marks_old_selected_period` - 2 passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 5 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec web node --test lib/oraclesLens.test.js` - 9 passed
- `docker compose exec api pytest -q` - 206 passed
- `git diff --check` - passed

## Contract Checklist

- [x] No schema migration.
- [x] Existing historical snapshot `period` query parameter is reused.
- [x] UI labels historical periods as snapshots, not current intelligence.
- [x] No external market-data calls added.
