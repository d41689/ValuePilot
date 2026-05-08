# 13F Amendment Accession Detail

## Goal / Acceptance Criteria

- Add an admin-facing amendment accession list/detail surface for pending, failed, and applied 13F/A filings.
- Show which original accession is superseded, manager, quarter, raw document parse statuses/errors, holdings count, latest-effective state, and recommended action.
- Let the admin dashboard trigger the existing `reprocess_amendment` job directly from a pending/failed amendment row.

## Scope

In:
- Backend admin service payloads for amendment accessions.
- Admin API endpoints for amendment list/detail.
- Frontend normalization and dashboard card for amendment review.
- Focused tests for pending and failed amendment visibility.

Out:
- New amendment ingestion semantics or schema changes.
- CIK revocation workflow.
- External EDGAR network calls in tests.

## Files to Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-06: Started after quality report persistence commit. The implementation should reuse the existing `reprocess_amendment` job lock key rather than introduce a new job type.
- 2026-05-06: Added admin amendment list/detail endpoints. Each row reports accession, manager, quarter, superseded accession, raw primary/InfoTable parse status, holdings count, latest-effective accession, and a `reprocess_amendment` recommended job for pending/failed rows.
- 2026-05-06: Added the admin dashboard Amendment Accessions card plus slide-out detail panel and row-level Reprocess action.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 19 tests.
- `docker compose exec api pytest -q` passed: 230 tests.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` passed: 88 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- Screeners and Oracle's Lens fact sourcing were not changed.
- No raw SQL from user input was added.
- No formula evaluation or `eval`/`exec` behavior was touched.
- 13F amendment status remains derived from persisted filings, holdings, and raw document parse status.
- Existing `reprocess_amendment` lock key semantics are preserved.
