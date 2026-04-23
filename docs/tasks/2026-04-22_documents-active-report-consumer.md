# Task: Show active report metadata on the documents page

## Goal / Acceptance Criteria
- Surface active report metadata from `/api/v1/documents` in the frontend `/documents` page.
- Users must be able to tell which uploaded document is currently active for which ticker(s) without opening raw data.
- Existing parsed/raw/evidence actions must keep working.

## Scope
**In**
- Minimal frontend helper for active report display text.
- `/documents` page updates to render active-report status.
- Targeted frontend verification.

**Out**
- New backend changes.
- New frontend routes.
- Stock detail page changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> document lineage and research workflow
- `AGENTS.md` -> task logging, Docker-only verification

## Files To Change
- `docs/tasks/2026-04-22_documents-active-report-consumer.md` (this file)
- `frontend/app/(dashboard)/documents/page.tsx`
- `frontend/lib/documentActiveReport.js`
- `frontend/lib/documentActiveReport.test.js`

## Execution Plan (Assumed approved per direct request)
1. Add failing helper tests for active report display text.
2. Implement helper and documents page rendering.
3. Run frontend verification in Docker.

## Contract Checks
- Frontend uses `is_active_report` and `active_for_tickers` from the documents API.
- No new routes or backend dependencies.

## Rollback Strategy
- Revert helper and `/documents` page display changes.

## Progress Log
- [x] Add failing helper tests.
- [x] Implement helper and page rendering.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Consumption stays on the existing `/documents` page; no new route was added.
- Active report state is shown both as a badge (`Active Report` / `Historical`) and as ticker coverage text for active documents.
- Ticker coverage text is capped to keep table rows readable.

## Verification Results
- `docker compose exec web node --test lib/documentActiveReport.test.js lib/documentEvidence.test.js lib/documentsAccess.test.js`
- `docker compose exec web npm run lint`
- Result: tests passed, lint clean
