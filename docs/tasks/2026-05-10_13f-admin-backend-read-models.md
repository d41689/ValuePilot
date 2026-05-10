# 13F-1C2-01 Admin Backend Read Models for Dashboard Pages

## Goal / Acceptance Criteria

- Stabilize backend read models for MVP 1C-2 admin dashboard pages before frontend work begins.
- Admin filings list/detail exposes caveat-driving fields: report type, coverage completeness/type, confidential treatment, amendment status/type, parse status, deadlines, and active-period flags.
- Parse runs can be listed by accession as an audit history.
- Jobs list supports pagination and filters for status, job type, started_at date range, sync_date, and quarter.
- Admin endpoints provide holdings coverage summary, pending amendments grouped by type/status, and unresolved CUSIP mapping read models.
- Pagination is implemented for list endpoints so frontend does not invent semantics.

## Scope In

- Backend admin read models and route wiring only.
- Filings list/detail endpoints under `/api/v1/admin/13f/filings`.
- Parse run history endpoint under `/api/v1/admin/13f/filings/{accession_number}/parse-runs`.
- Jobs list filter/pagination enhancements.
- Holdings coverage summary endpoint.
- Pending amendments endpoint.
- CUSIP mappings unresolved endpoint.

## Scope Out

- Frontend UI.
- MVP 3 batch reparse endpoints.
- Schema migrations.
- Parser or ingestion behavior changes.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §11 Admin Dashboard.
- `docs/prd/13f_automation_and_resilience_prd.md` §13 Admin API Requirements.
- `docs/prd/13f_automation_and_resilience_prd.md` §7.1 filing metadata and caveat fields.
- `docs/prd/13f_automation_and_resilience_prd.md` §8 CUSIP mapping.

## Files Likely to Change

- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_read_models.py`

## Tests First

- Add admin filings list/detail read-model tests.
- Add parse runs audit history endpoint test.
- Add jobs filter/pagination test.
- Add pending amendments grouping test.
- Add holdings coverage summary test.
- Add unresolved CUSIP mappings endpoint test.

## Docker Verification Commands

- `docker compose exec api pytest -q tests/unit/test_13f_admin_read_models.py`
- `docker compose exec api pytest -q tests/unit`

## Review Gate

- Tech Lead reviews API contracts and pagination before 13F-1C2-02 frontend starts.

## Progress Notes

- 2026-05-10: Confirmed next task from execution plan is 13F-1C2-01. PRD §11/§13 reviewed. Git worktree was clean before task setup.
- 2026-05-10: Added TDD coverage for filings list/detail, parse run audit history, jobs filters, pending amendments grouping, holdings coverage, and unresolved CUSIP mapping read models.
- 2026-05-10: Implemented admin read-model service helpers and route wiring without schema, parser, frontend, or PRD changes.
- 2026-05-10: Docker verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_read_models.py` -> 6 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_user_api.py` -> 58 passed.
  - `docker compose exec api pytest -q tests/unit` -> 493 passed, 1 existing SQLAlchemy transaction rollback warning.
- 2026-05-10: Accepted Tech Lead review follow-ups:
  - Added pagination envelope to parse-runs-by-accession.
  - Scoped unresolved CUSIP mappings to current parse runs so counts match current holdings coverage semantics.
  - Added explicit `manager_id` filter coverage for filings list.
- 2026-05-10: Follow-up Docker verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_read_models.py` -> 7 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_user_api.py` -> 58 passed.
  - `docker compose exec api pytest -q tests/unit` -> 494 passed, 1 existing SQLAlchemy transaction rollback warning.
