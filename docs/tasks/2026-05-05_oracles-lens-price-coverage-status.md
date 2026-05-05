# Oracle's Lens Price Coverage Status

## Goal / Acceptance Criteria

- Expose price coverage status for Oracle's Lens historical snapshots.
- API coverage makes selected price context, price target date, covered candidates, missing candidates, and coverage ratio explicit.
- Historical periods with missing local prices surface a backfill-needed state.
- Frontend displays price coverage above the candidate table.
- UI should make missing historical price data visible without triggering provider calls.

## Scope

In:
- Backend Oracle's Lens coverage payload.
- Backend unit tests for historical price coverage.
- Frontend coverage card.

Out:
- Running the backfill automatically.
- New backend endpoint.
- New schema.
- Provider/network calls during dashboard rendering.

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

- This follows the explicit backfill service. The dashboard should tell users when backfill is needed, not perform it implicitly.

## Implementation Notes

- Added price coverage status fields to the Oracle's Lens API coverage payload:
  - `candidate_count`
  - `price_context`
  - `price_target_date`
  - `price_coverage_count`
  - `price_missing_count`
  - `price_coverage_ratio`
  - `price_backfill_required`
  - `price_backfill_hint`
- Historical snapshots with missing local prices now return a backfill-needed state.
- Added a frontend `Price Coverage` card that displays context, target date, candidate coverage, missing count, and the explicit backfill command when needed.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_uses_period_price_for_historical_snapshot tests/unit/test_oracles_lens.py::test_oracles_lens_marks_old_selected_period` - 2 passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 6 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec web node --test lib/oraclesLens.test.js` - 9 passed
- `docker compose exec api pytest -q` - 209 passed
- `git diff --check` - passed

## Contract Checklist

- [x] Dashboard rendering does not trigger provider/network calls.
- [x] Backfill command is shown as an explicit operator action.
- [x] No schema migration.
- [x] Historical missing price data is visible in coverage summary.
- [x] UI labels price data as local EOD coverage, not real-time price data.
