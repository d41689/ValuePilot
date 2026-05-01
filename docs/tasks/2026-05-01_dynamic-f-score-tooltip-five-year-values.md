# Dynamic F-Score Tooltip Five-Year Used Values

## Goal / Acceptance Criteria

- Dynamic F-Score tooltip `实际使用计算的值` shows inputs for all displayed years, not only the latest year.
- Applies to all 9 Piotroski component indicators.
- Preserve formula dedupe and estimate markers.

## Scope

In:
- Summary API formula detail serialization for multi-year used values.
- Frontend model test coverage.

Out:
- Piotroski calculation algorithm changes.
- Database schema changes.
- Visual redesign of the card.

## Files To Change

- `backend/app/api/v1/endpoints/stocks.py`
- `backend/tests/unit/test_stocks_lookup_by_ticker.py`
- `frontend/lib/dynamicFScoreCard.test.js`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py`
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js`
- `docker compose exec web node --test lib/uiStandard.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Task created before code changes.
- Confirmed root cause: `formula_details.used_values` was built from only the latest displayed fact.
- Updated API serialization to aggregate used input values across every displayed year for each component row.
- Kept total row input details empty because total is an aggregate of component scores rather than a direct metric input formula.

## Verification

- `docker compose exec api pytest -q tests/unit/test_stocks_lookup_by_ticker.py` passed.
- `docker compose exec web node --test lib/dynamicFScoreCard.test.js` passed.
- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web npm run lint` passed.
- API spot check for ASML confirmed component rows now expose used values across the displayed years instead of only the latest year.

## Contract Checklist

- Tooltip values continue to read existing calculated fact metadata from `metric_facts`.
- No formula execution is introduced.
- No raw SQL from user input added.
- No eval/exec added.
- Lineage and `is_current` semantics are unchanged.
