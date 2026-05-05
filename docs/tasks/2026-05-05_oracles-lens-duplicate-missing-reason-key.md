# Oracle's Lens Duplicate Missing Reason Key

## Goal / Acceptance Criteria

- Fix React duplicate-key warning on `/13f/oracles-lens`.
- Missing-data reasons from quality and valuation can contain duplicate text such as `missing price`.
- Review panel must render duplicate/mixed missing reasons without React key collisions.
- Keep the displayed missing-data list concise and stable.

## Scope

In:
- Frontend Oracle's Lens row normalization/helper tests.
- Frontend review panel missing-data rendering.

Out:
- Backend API changes.
- Schema changes.
- Visual redesign.

## Files To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`

## Notes

- This is a rendering fix only. Do not change the meaning of backend unavailable reasons.

## Implementation Notes

- Added `missingDataReasons` helper to merge quality and valuation unavailable reasons.
- The helper de-duplicates repeated reason labels while keeping stable source-qualified keys.
- Updated the review panel to render `{key, label}` reasons instead of using raw reason text as a React key.

## Verification

- `docker compose exec web node --test lib/oraclesLens.test.js` - 10 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 6 passed
- `git diff --check` - passed

## Contract Checklist

- [x] Backend unavailable reason semantics unchanged.
- [x] Duplicate missing reasons no longer create duplicate React keys.
- [x] Missing data remains visible in the drilldown panel.
