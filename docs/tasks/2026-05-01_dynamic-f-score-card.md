# Dynamic F-Score Card

## Goal / Acceptance Criteria

- Add a `Dynamic F-Score Card` to `/stocks/ASML/summary`.
- Display the requested five-year F-Score health table for 2022 through 2026.
- Include category, check item, yearly scores, status, and AI commentary.
- Use existing shadcn/ui `Card`, `Table`, and `Badge` components.

## Scope

In:
- Frontend summary card UI.
- Static display data for the requested ASML summary page card.
- Focused frontend test for the table model.

Out:
- Backend Piotroski calculation changes.
- Database schema changes.
- API contract changes.

## PRD References

- ValuePilot v0.1 focuses on normalized financial facts and screening formulas.
- This task is UI-only and does not alter metric fact storage, screeners, or formula calculation.

## Files To Change

- `frontend/lib/dynamicFScoreCard.js`
- `frontend/lib/dynamicFScoreCard.d.ts`
- `frontend/lib/dynamicFScoreCard.test.js`
- `frontend/components/DynamicFScoreCard.tsx`
- `frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx`

## Test Plan

- `docker compose exec web node --test lib/dynamicFScoreCard.test.js`
- `docker compose exec web node --test lib/uiStandard.test.js`
- `docker compose exec web npm run lint`

## Execution Plan

1. Add a small table model with years, rows, statuses, and commentary.
2. Add a focused Node test that locks the requested card data and totals.
3. Render the model inside `StockSummaryCard` using shared shadcn/ui components.
4. Run frontend verification in Docker.

## Progress Notes

- Task created before code changes.
- Added a failing frontend model test before implementation.
- Implemented the static requested ASML F-Score model and a shadcn/ui card rendered only for ASML summary pages.

## Verification

- `docker compose exec web node --test lib/dynamicFScoreCard.test.js` passed.
- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web npm run build` compiled successfully and then failed during existing `/404` prerender with `<Html> should not be imported outside of pages/_document`.
- Browser check at `http://localhost:3001/stocks/ASML/summary` confirmed `Dynamic F-Score Card`, years 2022-2026, and requested commentary are visible after restarting the web service.

## Contract Checklist

- `metric_facts` query contracts are unchanged.
- No `value_numeric` normalization behavior changed.
- No raw SQL from user input added.
- No eval/exec added.
- Lineage and `is_current` semantics are unchanged.
