# 13F Manager CIK Revocation Workflow

## Goal / Acceptance Criteria

- Add a safe admin workflow to revoke an already confirmed manager CIK when it is discovered to be wrong.
- Revocation must be auditable, require an admin note, preserve the old CIK and affected downstream scope, and make the manager ineligible for future 13F ingestion until reconfirmed.
- Existing filings and holdings must not be deleted or rewritten automatically. The workflow should report affected quarters so admins know what needs reprocessing or engineering review.

## Scope

In:
- Durable manager CIK review event table.
- Backend service/API for manager review events and confirmed CIK revocation.
- Admin dashboard control for confirmed managers.
- Tests for audit persistence and ingestion exclusion after revocation.

Out:
- Automatic deletion/quarantine of existing filings or holdings.
- Automatic reassignment of filings to a different manager.
- Bulk downstream repair jobs.

## Files to Change

- `backend/app/models/institutions.py`
- `backend/alembic/versions/*-add_manager_cik_review_events.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`

## Test Plan

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-06: Started after amendment accession review. The workflow is intentionally conservative: revoke the CIK and audit affected scope, but do not mutate existing filings or holdings.
- 2026-05-06: Added durable `institution_manager_cik_review_events` audit records for confirm, reject, and revoke actions.
- 2026-05-06: Revoking a confirmed CIK now requires a note, sets the manager to `match_status='revoked'` with `cik=NULL`, records old CIK/status, affected filing count, affected quarters, and marks whether downstream review is required.
- 2026-05-06: Added admin UI `Revoke CIK` action for confirmed managers and a latest CIK audit column in the Managers table.

## Verification

- `docker compose exec api alembic upgrade head` passed.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 22 tests.
- `docker compose exec api pytest -q` passed: 233 tests.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` passed: 89 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- Screeners and Oracle's Lens still filter managers by `match_status='confirmed'` and `cik IS NOT NULL`; revoked managers are excluded from future ingestion/product reads.
- Existing filings, holdings, and raw documents are preserved for audit and are not silently deleted.
- No raw SQL from user input was added.
- No formula evaluation or `eval`/`exec` behavior was touched.
- CIK revocation records reviewer, timestamp, note, old/new identity state, and affected downstream scope.
