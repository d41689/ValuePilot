# Oracle's Lens Visual Radar

## Goal / Acceptance Criteria

- Add Milestone 4 compact visual radar for Oracle's Lens candidates.
- Visualization uses existing normalized dashboard rows.
- Bubble size represents aggregate position weight.
- Bubble tone represents add/reduce context.
- Hover/focus content exposes holder action context without replacing the table as the primary research surface.

## Scope

In:
- Frontend visualization helper.
- Frontend helper tests.
- Oracle's Lens page compact cluster panel.

Out:
- New charting library.
- Canvas/SVG-heavy visualization.
- Backend changes.
- Historical timeline.

## Files To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`

## Notes

- The table remains the primary analytical surface.
- Radar copy should say `cluster view` or `ownership signals`, not `opportunities`.

## Implementation Notes

- Added `radarBubbles` helper to map normalized rows to compact visual signals.
- Bubble size is based on aggregate reported position weight.
- Bubble tone is based on add/reduce context.
- Added a `Smart Money Clusters` card above the ranked table.
- Bubble hover/focus content exposes holder action context, signal score, and confidence.
- Clicking a bubble opens the same caution drilldown panel as the table `Review` action.

## Verification

- `docker compose exec web node --test lib/oraclesLens.test.js` - 9 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 5 passed
- `git diff --check` - passed

## Contract Checklist

- [x] No backend contract changed.
- [x] No charting dependency added.
- [x] Table remains the primary research surface.
- [x] Visualization copy avoids opportunity or buy-signal language.
