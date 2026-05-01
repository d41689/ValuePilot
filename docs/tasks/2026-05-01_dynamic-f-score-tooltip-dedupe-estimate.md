# Dynamic F-Score Tooltip Dedupe And Estimate Marks

## Goal / Acceptance Criteria

- Do not show duplicate formulas in Dynamic F-Score tooltip details when the used formula is also a fallback formula.
- Mark score cells whose referenced calculation data is `estimate`.
- Keep the marker compact in the score cell and expose the meaning visually.

## Scope

In:
- Summary API score fact-nature serialization.
- Frontend formula-detail dedupe and estimate score marker.
- Backend/frontend tests.

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
- Confirmed the duplicate happened because the tooltip displayed the actual `usedFormula` and then displayed the same expression again in the fallback list when the actual method was a fallback.
- Added backend and frontend dedupe so fallback lists exclude the already displayed used formula and repeated fallback formulas.
- Added `score_fact_natures` to card rows and an inline `估` badge for year cells backed by estimate inputs/facts.
- Estimate detection prioritizes referenced inputs marked `estimate`, then falls back to the calculated fact's own `fact_nature`.

## Verification

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` passed.
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js` passed.
- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web npm run lint` passed.
- API spot check for ASML confirmed no formula remains duplicated between `used_formula` and `fallback_formulas`.
- API spot check for ASML confirmed estimate-backed rows expose `score_fact_natures` with `estimate`.

## Contract Checklist

- Estimate markers are display-only metadata from existing calculated facts.
- Formula dedupe is display-only; formulas are not executed.
- No raw SQL from user input added.
- No eval/exec added.
- Lineage and `is_current` semantics are unchanged.
