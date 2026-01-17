# Task: Documents Page (List + Actions)

## Goal / Acceptance Criteria
- `/documents` route renders without 404 and shows a list of uploaded documents.
- Each row includes: file name, template/source label, companies, page count, parse status (actionable labels), upload time.
- Actions per row grouped by intent:
  - View Parsed Data (JSON from extractions endpoint).
  - View Raw Text (raw text preview).
  - Reparse (calls backend reparse endpoint).
- Backend provides document list API and raw_text endpoint; list API includes companies and counts.
- Parsed/partial/failed statuses render with clear labels and colors (parsed=green, parsed_partial=orange, failed=red).

## Scope
- In scope:
  - Frontend `/documents` page implementation.
  - Backend API: list documents + raw_text endpoint.
  - Basic UI for viewing raw text and parse results.
  - Tests for new backend endpoints.
- Out of scope:
  - Auth/permissions changes.
  - Schema migrations.
  - UI redesign beyond existing dashboard styles.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` (data lineage + document artifacts).
- `AGENTS.md` (Docker-only commands, TDD).

## Files to change
- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/app/(dashboard)/documents/page.tsx`
- `docs/tasks/2026-01-19_documents-page.md`

## Plan
1. Add failing tests for list/raw_text endpoints (including companies list/count).
2. Implement backend endpoints for list + raw_text with company aggregation.
3. Build `/documents` page with list + action groups + status labels/colors.
4. Run Docker tests and update task notes.

## Rollback Strategy
- Revert endpoint and UI changes if tests or API contracts fail.

## Test Plan (Docker)
- `docker compose exec api pytest -q tests/unit/test_documents_api.py`
- `docker compose exec api pytest -q`

## Notes / Decisions
- Use existing `user_id=1` convention for v0.1 UI calls.
- Parse result uses `/extractions/document/{document_id}` API.
- Documents list is container-level only; company details derived from parsed facts.
- Companies display rule: show up to 3 tickers; if more, show `AOS, MSFT, JNJ (+2)` style.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_documents_api.py`
- `docker compose exec -T api pytest -q`

## Tooling Notes
- Keep `frontend/package-lock.json` checked in for deterministic installs with npm.
- Accept `frontend/tsconfig.json` + `frontend/next-env.d.ts` updates from Next/TS tooling to avoid repeat diffs.
- Add `frontend/.eslintrc.json` with `next/core-web-vitals` so `docker compose exec -T web npm run lint` stays non-interactive.
- Suggested frontend gate: `docker compose exec -T web npm run lint` (and optionally `docker compose exec -T web npm run build`).
