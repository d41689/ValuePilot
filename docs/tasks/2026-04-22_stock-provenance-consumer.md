# Task: Show stock and DCF provenance metadata in the frontend

## Goal / Acceptance Criteria
- Surface stock/DCF provenance metadata returned by `/api/v1/stocks/by_ticker/{ticker}`.
- Summary and DCF views must show which report date / document the current values come from when available.
- Existing numeric behavior and interactions must remain unchanged.

## Scope
**In**
- Minimal frontend helper for formatting provenance labels.
- Summary page / summary card provenance display.
- DCF page provenance display for active report and default input basis.
- Targeted frontend verification.

**Out**
- Backend changes.
- New routes.
- Deep provenance drill-down UI for every single DCF control.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> auditability and lineage
- `AGENTS.md` -> task logging, Docker-only verification

## Files To Change
- `docs/tasks/2026-04-22_stock-provenance-consumer.md` (this file)
- `frontend/lib/factProvenance.js`
- `frontend/lib/factProvenance.test.js`
- `frontend/components/StockSummaryCard.tsx`
- `frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`

## Execution Plan (Assumed approved per direct request)
1. Add failing helper tests for provenance formatting.
2. Implement helper and wire provenance into summary and DCF pages.
3. Run frontend verification in Docker.

## Contract Checks
- Frontend consumes API-provided provenance fields directly.
- Existing values remain backward-compatible.

## Rollback Strategy
- Revert provenance helper and summary / DCF UI changes.

## Progress Log
- [x] Add failing helper tests.
- [x] Implement helper and wire provenance UI.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Summary view now shows active report metadata and per-metric provenance for price and P/E.
- DCF view shows active report metadata plus provenance for the current `Based on` source and selected growth-rate source.
- This step intentionally stops short of showing provenance beside every DCF input control to avoid overloading the page.

## Verification Results
- `docker compose exec web node --test lib/factProvenance.test.js lib/documentActiveReport.test.js lib/documentEvidence.test.js lib/documentsAccess.test.js`
- `docker compose exec web npm run lint`
- Result: tests passed, lint clean
