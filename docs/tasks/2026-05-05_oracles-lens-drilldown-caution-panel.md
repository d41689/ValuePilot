# Oracle's Lens Drilldown Caution Panel

## Goal / Acceptance Criteria

- Add the Milestone 3 drilldown caution panel for Oracle's Lens candidates.
- Users can open a candidate detail panel from the ranked table.
- The panel shows all caution flags grouped by category, quality/valuation missing data, top holders, and suggested next research steps.
- Suggested steps must be contextual: missing quality facts should point to locating/uploading a Value Line report before valuation review.
- UI must keep the dashboard as a research workflow, not a buy recommendation.

## Scope

In:
- Frontend row normalization helpers.
- Frontend helper tests.
- Oracle's Lens page detail panel.

Out:
- New backend endpoint.
- Database schema changes.
- Watchlist/reject-note actions.
- Document review deep links beyond textual next-step guidance.

## Files To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`

## Notes

- Use existing shared UI components only.
- Do not add a Radix dependency for a sheet in this step.
- Main table continues to show only the top 1-2 caution flags; drilldown shows the complete grouped list.

## Implementation Notes

- Added `groupCautionFlags` so the main table can stay quiet while the review panel shows all grouped caution flags.
- Added `suggestedResearchSteps` with contextual missing-data handling.
- Added a responsive right-side review panel to the Oracle's Lens page.
- The panel shows:
  - all grouped caution flags
  - missing quality and valuation data
  - top holder context
  - suggested next research steps
- The table now exposes a `Review` action for each candidate using the shared `Button` component.

## Verification

- `docker compose exec web node --test lib/oraclesLens.test.js` - 7 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 5 passed
- `git diff --check` - passed

## Contract Checklist

- [x] No backend data contract changed.
- [x] No new dependency or schema migration.
- [x] UI avoids buy-signal language.
- [x] Main table remains focused on the primary Signal Score.
- [x] Full caution detail is available in the drilldown panel.
