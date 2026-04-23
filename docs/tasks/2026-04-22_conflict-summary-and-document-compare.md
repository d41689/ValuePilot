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
- [x] Add document comparison view and tests.
- [x] Run Docker verification and commit compare step.

## Notes / Decisions / Gotchas
- Stock summary conflict rendering is frontend-only and consumes the existing additive stock API payload.
- Conflict formatting is isolated in `frontend/lib/actualConflicts.js` so page components stay declarative.
- Document comparison uses a minimal additive backend endpoint instead of client-side JSON diffing.
- Compare alignment differs by `fact_nature`: `actual/estimate` compare on metric+period, while `snapshot/opinion` compare on metric identity across report versions.

## Verification Results
- Summary conflict step:
  - `docker compose exec web node --test lib/actualConflicts.test.js lib/factProvenance.test.js`
    - `4 tests passed`
  - `docker compose exec web npm run lint`
    - `No ESLint warnings or errors`
- Document compare step:
  - `docker compose exec api pytest -q tests/unit/test_documents_api.py`
    - `7 passed in 1.45s`
  - `docker compose exec web node --test lib/documentCompare.test.js lib/documentEvidence.test.js lib/documentActiveReport.test.js lib/documentsAccess.test.js`
    - `8 tests passed`
  - `docker compose exec web npm run lint`
    - `No ESLint warnings or errors`
  - `docker compose exec api pytest -q`
    - `121 passed in 21.06s`
