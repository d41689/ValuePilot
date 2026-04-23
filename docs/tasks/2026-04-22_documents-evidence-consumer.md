# Task: Add documents-page consumer for evidence-only Value Line fields

## Goal / Acceptance Criteria
- Surface evidence-only Value Line fields in the frontend `/documents` experience.
- Users must be able to inspect business description, analyst commentary, and rating events without reading raw extraction JSON.
- Consumer layer must use the new `/api/v1/documents/{document_id}/evidence` endpoint.

## Scope
**In**
- Minimal frontend helper for grouping/labeling document evidence.
- `/documents` page updates to fetch and render evidence-only fields.
- Targeted frontend verification.

**Out**
- New frontend routes or standalone document detail pages.
- Backend schema/API changes beyond the existing evidence endpoint.
- Broad stock-level evidence aggregation.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> audit trail, document lineage, and query/display separation
- `AGENTS.md` -> task logging, Docker-only verification, minimal safe implementation

## Files To Change
- `docs/tasks/2026-04-22_documents-evidence-consumer.md` (this file)
- `frontend/app/(dashboard)/documents/page.tsx`
- `frontend/lib/documentEvidence.js`
- `frontend/lib/documentEvidence.test.js`

## Execution Plan (Assumed approved per direct request)
1. Add failing helper tests for evidence grouping/labels.
2. Implement minimal frontend evidence helper.
3. Wire `/documents` page to load and render evidence view.
4. Run frontend verification in Docker and record results.

## Contract Checks
- Frontend must consume `/documents/{document_id}/evidence`, not scrape raw extraction JSON.
- Evidence-only fields remain document-scoped and audit-oriented.
- Existing parsed/raw views remain intact.

## Rollback Strategy
- Revert evidence helper and `/documents` page changes.

## Progress Log
- [x] Add failing helper tests.
- [x] Implement helper and documents-page evidence rendering.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Consumption stays inside the existing `/documents` page; no new route was added.
- The UI now calls `/documents/{document_id}/evidence` directly instead of reusing raw extraction JSON.
- Evidence is grouped into three stable sections: Business, Commentary, and Rating Events.
- Rating event rows show both normalized value (`Raised` / `Lowered`) and the raw note text for audit clarity.

## Verification Results
- `docker compose exec web node --test lib/documentEvidence.test.js lib/documentsAccess.test.js`
- `docker compose exec web npm run lint`
- Result: tests passed, lint clean
