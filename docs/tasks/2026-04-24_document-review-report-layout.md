# Document Review Report Layout

## Goal / Acceptance Criteria

Rework `/documents/{document_id}/review` into a report-style review surface that reconstructs a Value Line-like layout from database facts so manual verification is faster.

- Replace the current card-per-field default layout with a report-style page organized by familiar Value Line regions.
- Keep the page backed by database review data from `metric_facts` and existing lineage context.
- Show only review-relevant values by default; move raw lineage, snippets, normalization details, and correction controls into a focused evidence panel.
- Keep single-field manual correction behavior intact without mutating `metric_extractions`.

## Scope

### In

- Frontend report-style review layout for `/documents/[id]/review`.
- Frontend helper logic to map grouped review facts into report slots and tabular sections.
- Focused tests for report model shaping and display formatting.
- Task log updates and Docker-based verification.

### Out

- No PRD changes.
- No database schema changes.
- No parser changes.
- No batch correction flow changes.
- No removal of lineage/correction capability; it only moves out of the default dense view.
- No attempt to reproduce Value Line branding assets exactly.

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md`
  - `C. Data Modeling & Storage (PostgreSQL)`
  - `metric_extractions (field-level lineage)`
  - `metric_facts (queryable facts for formulas/screeners)`
  - `Data Traceability Requirements`
- `docs/value_line_report_modules.md`
  - `1. Module Index (canonical)`
  - `2. Canonical JSON organization (module-oriented)`

## Files To Change

- `frontend/app/(dashboard)/documents/[id]/review/page.tsx`
- `frontend/lib/documentReview.js`
- `frontend/lib/documentReview.test.js`
- `docs/tasks/2026-04-24_document-review-report-layout.md`

## Execution Plan

1. Add failing helper tests for report slotting, table shaping, and focused evidence behavior.
2. Implement helper functions that transform review API groups into a report-oriented view model.
3. Rebuild the review page around the new model with a Value Line-like composition and evidence panel.
4. Verify with Docker Compose commands and record results.

## Contract Checks

- Review data remains fact-backed from `metric_facts`.
- Manual edits still create new current manual facts; no mutation of `metric_extractions`.
- Lineage fields remain visible in the evidence panel for traceability.
- No screeners/formulas behavior is touched.

## Rollback Strategy

- Revert the frontend report-layout changes and restore the previous grouped-card presentation if the new layout proves harder to verify or breaks correction flow.

## Test Plan

- `docker compose up -d --build`
- `docker compose exec -T frontend node --test lib/documentReview.test.js`
- `docker compose exec -T frontend npm run lint`

## Progress Notes

- 2026-04-24: User approved first-pass report-style review page replacing the dense grouped review layout.
- 2026-04-24: Plan is to keep the existing review API and move complexity into frontend view-model shaping.
- 2026-04-24: Added report-view helper modeling for header slots, rating/quality boxes, annual and quarterly tables, and selected-field lookup.
- 2026-04-24: Rebuilt `/documents/[id]/review` as a report-style surface with a sticky evidence panel for lineage and manual correction.
- 2026-04-24: Removed the default raw-text side-by-side panel from the primary review flow to reduce noise; snippet evidence remains available per selected field.
- 2026-04-24: Local browser sanity check confirmed the updated route compiles and serves on `http://localhost:3001/documents/21/review`, but authenticated in-app verification was limited because the local app redirected to `/login` without a session.

## Verification Results

- `docker compose up -d --build` -> pass.
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass (`5 passed`).
- `docker compose exec -T web npm run lint` -> pass.
- `docker compose exec -T web npm run build` -> fail due pre-existing Next.js build error while prerendering `/404`: `Error: <Html> should not be imported outside of pages/_document.`
