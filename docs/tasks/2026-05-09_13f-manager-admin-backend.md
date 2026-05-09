# 13F Manager Admin Backend

## Goal / Acceptance Criteria

Implement execution-plan task `13F-1A-02`: backend manager CRUD, candidate import, CIK confirmation surfaces, and a safe backfill preview without starting jobs silently.

Acceptance criteria:
- Admin can list, create, patch, and deactivate 13F managers.
- Bulk CSV import creates candidate managers only and never confirms CIK.
- CIK confirmation transitions only valid manager records to active tracked status and records audit fields.
- Backfill preview returns an estimate/stub response and does not enqueue `job_runs`.
- `value_unit_override` defaults to `infer`.
- Existing legacy 13F admin behavior remains compatible while PRD-facing fields are exposed.

## Scope

In:
- Admin API endpoints for manager create/patch/deactivate/bulk-import/backfill-preview.
- Service-layer manager creation/update/import/preview helpers.
- Tests for the PRD acceptance criteria.
- Task log progress and verification notes.

Out:
- Full frontend UI.
- Actual historical backfill job execution.
- SEC network search/client implementation beyond existing discovery hints.
- Daily index fetching/parsing.
- Parser or holdings ingestion.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §3 Manager Management Center.
- `docs/prd/13f_automation_and_resilience_prd.md` §3.2 Manager statuses.
- `docs/prd/13f_automation_and_resilience_prd.md` §3.3 Manager fields.
- `docs/prd/13f_automation_and_resilience_prd.md` §3.5 CIK search and confirmation workflow.
- `docs/prd/13f_automation_and_resilience_prd.md` §3.6 Bulk import.
- `docs/prd/13f_automation_and_resilience_prd.md` §13 Manager APIs.

## Files To Change

- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_manager_admin_backend.py`
- `docs/tasks/2026-05-09_13f-manager-admin-backend.md`

## Test Plan

Docker only:
- `docker compose exec api pytest -q tests/unit/test_13f_manager_admin_backend.py`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Started `13F-1A-02` after G3 approval and after committing `13F-1A-01`.
- 2026-05-09: Existing code already has manager list plus CIK confirm/reject/revoke/retry endpoints using legacy `match_status`; this task will add PRD CRUD/import/deactivate/backfill-preview behavior while preserving compatibility.
- 2026-05-09: Wrote failing tests first for create, patch, deactivate, bulk CSV import, confirm CIK active transition, and backfill preview no-enqueue behavior.
- 2026-05-09: Implemented manager create/patch/deactivate/bulk-import/backfill-preview service helpers and admin routes.
- 2026-05-09: Updated manager payloads to expose PRD-facing fields while preserving existing legacy fields.
- 2026-05-09: Confirm CIK now sets `status=active`, `confirmed_by`, `confirmed_at`, and `edgar_legal_name`; bulk import explicitly ignores CIK values as hints and creates candidates only.
- 2026-05-09: Verification passed:
  - `docker compose exec api pytest -q tests/unit/test_13f_manager_admin_backend.py` (`6 passed`)
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` (`50 passed`)
  - `docker compose exec api pytest -q tests/unit` (`316 passed in 38.91s`)
- 2026-05-09: Contract check: no SEC network calls added, no backfill jobs enqueued by preview or confirmation, no frontend, no parser/holdings implementation, no PRD edits.
