# 13F Manager CIK Review Audit Workflow

## Goal / Acceptance Criteria

- Add manager / CIK candidate audit fields required by `docs/plans/13f_admin_data_operations_dashboard_product_plan.md`.
- Preserve candidate provenance from automatic CIK matching.
- Record confirm / reject reviewer, timestamp, review note, evidence source, evidence URL, similarity score, and prior rejected candidates.
- Ensure rejected candidates remain auditable and are not used by ingestion.
- Expose audit fields in the admin manager payload and `/admin/13f` manager table.

## Scope

In:
- Schema migration and `InstitutionManager` model fields for CIK candidate audit metadata.
- `match_cik_candidates` writes candidate evidence metadata instead of encoding it only in `display_name`.
- Confirm / reject APIs write review note, reviewer id, and timestamp.
- Admin manager list exposes evidence and review metadata.
- Frontend manager table surfaces candidate evidence and review state.
- Tests for candidate audit metadata, confirm/reject audit writes, and admin payload fields.

Out:
- Revoking already confirmed CIKs.
- Separate candidate history table.
- Downstream repair workflow for wrong historical CIKs.

## Files to Change

- `backend/app/models/institutions.py`
- `backend/alembic/versions/*`
- `backend/app/services/edgar_ingestion.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`

## Test Plan

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-06: Started after async 13F job worker commit `c8a680a`.
- 2026-05-06: Added manager CIK candidate audit schema, preserved EDGAR match evidence in `match_cik_candidates`, and updated admin confirm/reject actions to record reviewer, timestamp, note, and prior rejected candidates.
- 2026-05-06: Updated `/admin/13f` manager table to show candidate CIK, EDGAR legal name, similarity score, source, evidence link, and review note.

## Verification

- `docker compose exec api alembic upgrade head` - passed.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` - 14 passed.
- `docker compose exec api pytest -q` - 225 passed.
- `docker compose exec web sh -lc 'node --test lib/*.test.js'` - 86 passed.
- `docker compose exec web npm run lint` - passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` - passed.
