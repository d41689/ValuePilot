# Dynamic F-Score Card By Ticker

## Goal / Acceptance Criteria

- `http://localhost:3001/stocks/{ticker}/summary` renders the Dynamic F-Score Card for any ticker with available Piotroski facts.
- Card values come from the current stock's `metric_facts`, not ASML-specific frontend constants.
- If a ticker has no Piotroski facts, the card shows an explicit empty state for that ticker.
- Keep the table columns dynamic from returned fiscal years.

## Scope

In:
- Summary API serialization of five-year Piotroski card data.
- Frontend summary page and card rendering.
- Backend and frontend tests for by-ticker behavior.

Out:
- Piotroski calculation algorithm changes.
- Database schema changes.
- PRD changes.

## Files To Change

- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx`
- `frontend/components/DynamicFScoreCard.tsx`
- `frontend/lib/dynamicFScoreCard.js`
- `frontend/lib/dynamicFScoreCard.d.ts`
- `frontend/lib/dynamicFScoreCard.test.js`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js`
- `docker compose exec web node --test lib/uiStandard.test.js`
- `docker compose exec web npm run lint`

## Execution Plan

1. Add failing API coverage for `piotroski_f_score_card` on ticker lookup.
2. Add frontend model tests for API-driven card rows and empty state.
3. Implement backend serializer from current `metric_facts`.
4. Update the frontend card to accept ticker/company/API data props.
5. Verify in Docker and update this task log.

## Progress Notes

- Task created before code changes.
- Added failing backend coverage for ticker-specific Piotroski card API data.
- Added failing frontend model coverage for API-driven Dynamic F-Score data and empty state.
- Implemented the summary API card serializer from current calculated `metric_facts`.
- Updated the frontend card to render data from the current summary response for every ticker.

## Verification

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` passed.
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js` passed.
- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web npm run lint` passed.
- API spot checks confirmed ASML and FICO return distinct `piotroski_f_score_card` year/score data.
- Browser check at `http://localhost:3001/stocks/ASML/summary` confirmed the card shows ticker context and API-derived total commentary.

## Contract Checklist

- Summary card data reads from `metric_facts`.
- Numeric values are displayed from existing normalized `value_numeric` / calculated `value_json` fields.
- No raw SQL from user input added.
- No eval/exec added.
- Lineage and `is_current` semantics are unchanged.
