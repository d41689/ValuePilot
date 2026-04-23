# Task: Surface actual conflicts in stock summary and add document comparison view

## Goal / Acceptance Criteria
- Show stock-level `actual` conflict summary on the stock summary page.
- Add a document comparison view for same-stock Value Line reports on `/documents`.
- Keep the implementation additive and explainable, using existing parsed/evidence APIs where possible.

## Scope
**In**
- Frontend stock summary conflict UI.
- Frontend helper/tests for formatting conflict payloads.
- Document compare UI on `/documents`.
- Minimal backend support if the compare view needs a dedicated endpoint.

**Out**
- Conflict adjudication.
- Cross-source comparison.
- New schema.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> lineage, auditability, normalized queryable facts
- `AGENTS.md` -> Docker-only verification, task logging

## Files To Change
- `docs/tasks/2026-04-22_conflict-summary-and-document-compare.md`
- `frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx`
- `frontend/components/StockSummaryCard.tsx`
- `frontend/lib/*` helper/tests as needed
- `frontend/app/(dashboard)/documents/page.tsx`
- Backend endpoint/helper files only if comparison needs server-side support

## Execution Plan (Assumed approved per direct request)
1. Add summary-page conflict rendering and tests.
2. Verify in Docker and commit that step.
3. Add document comparison view and any minimal backend support.
4. Verify in Docker and commit that step.

## Contract Checks
- Read canonical stock data from the stock API, not raw document JSON alone.
- Preserve document lineage in any compare output.
- Keep parser/extraction tables immutable.

## Rollback Strategy
- Revert frontend consumers and any additive backend compare endpoint.

## Progress Log
- [x] Add summary conflict UI and tests.
- [x] Run Docker verification and commit summary step.
- [ ] Add document comparison view and tests.
- [ ] Run Docker verification and commit compare step.

## Notes / Decisions / Gotchas
- Stock summary conflict rendering is frontend-only and consumes the existing additive stock API payload.
- Conflict formatting is isolated in `frontend/lib/actualConflicts.js` so page components stay declarative.

## Verification Results
- Summary conflict step:
  - `docker compose exec web node --test lib/actualConflicts.test.js lib/factProvenance.test.js`
    - `4 tests passed`
  - `docker compose exec web npm run lint`
    - `No ESLint warnings or errors`
