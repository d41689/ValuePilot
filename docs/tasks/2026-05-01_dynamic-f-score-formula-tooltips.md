# Dynamic F-Score Formula Tooltips

## Goal / Acceptance Criteria

- Add formula details to the Dynamic F-Score Card formula column.
- Desktop users can hover/focus formula info controls to see details.
- Tablet/mobile users can tap an info icon to show the same details.
- Tooltip details include standard F-Score definition, our formula including fallbacks, and actual values used by the latest calculation.

## Scope

In:
- Summary API `formula_details` serialization for Piotroski card rows.
- Frontend formula info icon and tooltip/popover behavior.
- Backend/frontend tests.

Out:
- Piotroski calculation algorithm changes.
- Database schema changes.
- Third-party tooltip package installation.

## Files To Change

- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/components/DynamicFScoreCard.tsx`
- `frontend/lib/dynamicFScoreCard.js`
- `frontend/lib/dynamicFScoreCard.d.ts`
- `frontend/lib/dynamicFScoreCard.test.js`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js`
- `docker compose exec web node --test lib/uiStandard.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Added `formula_details` to each card row with standard definition, standard formula, fallback formulas, latest used formula, and latest used values.
- Added an `Info` icon button in the formula column. Hover/focus shows details on desktop; click toggles details for touch devices.
- Reused existing shared `Button` and `lucide-react` icons.

## Verification

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` passed.
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js` passed.
- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web npm run lint` passed.
- API spot check for ASML returned formula details with fallback formulas and used values.
- Browser check confirmed 10 info buttons and visible tooltip sections after clicking an icon.

## Contract Checklist

- Card values continue to read current calculated facts from `metric_facts`.
- Tooltip formulas are displayed from metadata/fallback constants only; no formula execution is introduced.
- No raw SQL from user input added.
- No eval/exec added.
- Lineage and `is_current` semantics are unchanged.
