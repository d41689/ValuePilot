# Dynamic F-Score Tooltip Key Fix

## Goal / Acceptance Criteria

- Remove React duplicate-key warnings in Dynamic F-Score tooltip used-value rows.
- Preserve duplicated financial input rows when they are legitimate calculation inputs.

## Scope

In:
- Frontend tooltip used-value render keys.
- Frontend test coverage for duplicate input values.

Out:
- Backend data shape changes.
- Piotroski calculation changes.

## Files To Change

- `frontend/components/DynamicFScoreCard.tsx`
- `frontend/lib/dynamicFScoreCard.test.js`

## Test Plan

- `docker compose exec web node --test lib/dynamicFScoreCard.test.js`
- `docker compose exec web node --test lib/uiStandard.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Task created before code changes.
- Root cause: tooltip used-value rows keyed by metric/date/value can collide when a comparison formula legitimately references duplicate-looking inputs.
- Updated render keys to include the map index while preserving duplicate input rows.
- Added frontend coverage that duplicate used values remain present.

## Verification

- `docker compose exec web node --test lib/dynamicFScoreCard.test.js` passed.
- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web npm run lint` passed.

## Contract Checklist

- Rendering key change only; no data contract changes.
- No raw SQL from user input added.
- No eval/exec added.
