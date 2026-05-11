# 13F MVP2-04 Oracle's Lens Investor Signal UI

## Goal / Acceptance Criteria

Wire MVP 2 13F ownership signals into the existing Oracle's Lens page without overstating 13F data as investment advice.

Acceptance criteria:
- Candidate drilldown fetches `GET /api/v1/13f/stocks/{stock_id}/holders` for the selected period.
- UI displays direct holder count, value-manager direct count, featured holder count, attribution caveat count, top holders, recent changes, data caveats, and `as_of_quarter`.
- UI preserves PRD safety copy: 13F data is delayed research context, not a buy/sell recommendation or total AUM/current-holdings claim.
- Missing/unavailable data is shown explicitly, not as zero.
- Frontend uses shadcn/ui components, Tailwind, and lucide-react icons only.

## Scope In

- `frontend/lib/oraclesLens.js` normalizer for stock-holder aggregation responses.
- `frontend/lib/oraclesLens.test.js` tests for stock-holder aggregation normalization.
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` drilldown UI integration.
- Task log updates with Docker verification results.

## Scope Out

- Backend API/schema changes.
- MVP 3 cross-manager 13F-NT consolidation.
- Buy/sell recommendations, AI moat scores, total AUM, or current-holdings language.
- New frontend routes.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.1: Oracle's Lens investor signals.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.2: exclusion and caveat rules.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.3: stock holder aggregation fields.
- `docs/prd/13f_automation_and_resilience_prd.md` §16: UX copy and caveat principles.
- `docs/tasks/2026-05-10_13f-mvp2-decision-gate.md` D4-D6.

## Files Likely To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`
- `docs/tasks/2026-05-10_13f-mvp2-oracles-lens-ui.md`

## Tests First

Write failing frontend helper tests before UI implementation:
- Normalize stock-holder aggregation counts and labels.
- Preserve unavailable response state and empty arrays.
- Normalize recent changes and data caveats without investment-advice labels.

## Docker Verification Commands

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web node --test lib`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`

## Review Gate

Tech Lead should review:
- UI response-shape alignment with MVP2-03 API.
- Caveat display and avoidance of recommendation language.
- shadcn/ui + Tailwind + lucide-react compliance.
- Scope guard: no backend/schema/PRD/MVP3 changes.

## Progress Notes

- 2026-05-10: Started MVP2-04 after MVP2-03 approval.
- 2026-05-10: Added `normalizeStockHolderAggregation` with TDD coverage for available-with-caveat and unavailable stock-holder responses.
- 2026-05-10: Wired the Oracle's Lens candidate drawer to fetch `GET /api/v1/13f/stocks/{stock_id}/holders` for the selected/latest period and display direct consensus counts, top direct holders, recent direct changes, and data caveats.
- 2026-05-10: Kept UI copy scoped to delayed 13F research context; no buy/sell recommendation, total AUM, current-holdings, or MVP 3 cross-manager attribution language added.
- 2026-05-10: Accepted Tech Lead follow-up items: added visible `13F common weight` label, added explicit 45-day delay copy inside the drawer, memoized selected holder quarter, and covered attribution-only caveats in normalizer tests.
- 2026-05-10: Did not convert `portfolio_weight_pct=0` to unavailable in the frontend. Per PRD §16, unavailable weight should arrive as `NULL`; preserving numeric zero avoids hiding a valid backend value.

## Verification Results

- `docker compose exec web node --test lib/oraclesLens.test.js` - passed, 13 tests.
- `docker compose exec web node --test lib` - passed, 114 tests.
- `docker compose exec web npm run lint` - passed with no warnings or errors.
- `docker compose exec web npm run build` - passed.
