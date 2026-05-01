# Dynamic F-Score Card Nine Indicators

## Goal / Acceptance Criteria

- `/stocks/{ticker}/summary` Dynamic F-Score Card shows all 9 Piotroski component indicators.
- Keep the total F-Score row after the 9 component rows.
- Add a formula column showing each indicator's calculation formula.
- Formulas should come from calculated fact metadata when available and fall back to the documented component formula.

## Scope

In:
- Summary API Piotroski card row configuration and serialization.
- Frontend card table column/model updates.
- Backend and frontend tests.

Out:
- Piotroski calculation algorithm changes.
- Database schema changes.
- Screener/watchlist UI changes.

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

- Task created before code changes.
- Added failing backend coverage for all 9 component rows plus total and formula serialization.
- Added failing frontend model coverage for preserving row formulas.
- Expanded the summary API Piotroski card config to all 9 components and added formula serialization from latest fact metadata with fallback formulas.
- Added the `计算公式` table column in the frontend card.

## Verification

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` passed.
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js` passed.
- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web npm run lint` passed.
- API spot check for ASML returned 10 rows: 9 component indicators plus total.
- Browser check at `http://localhost:3001/stocks/ASML/summary` confirmed the formula column and all added indicators are visible.

## Contract Checklist

- Card values continue to read current calculated facts from `metric_facts`.
- Formula display uses calculated fact metadata/fallback constants only; no formula execution is introduced.
- No raw SQL from user input added.
- No eval/exec added.
- Lineage and `is_current` semantics are unchanged.
