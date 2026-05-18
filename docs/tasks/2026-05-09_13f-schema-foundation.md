# 13F Schema Foundation

## Goal / Acceptance Criteria

Implement execution-plan task `13F-1A-01`: add or align the MVP 1A database foundation for managers, EDGAR sync status, no-index expected dates, and job runs without implementing SEC ingestion, parser behavior, or frontend UI.

Acceptance criteria:
- Migrations apply cleanly from current Alembic head.
- Manager schema supports PRD-required fields and stable enum-like values.
- `edgar_sync_status` exists with PRD §4.2 fields and MVP 1A query indexes.
- `no_index_expected_dates` exists with `date`, `reason`, `source`, `active`, audit fields, and soft-disable semantics.
- `job_runs` supports PRD §12 status values plus lock/lease fields.
- Tests cover required fields, enum validation, uniqueness/index behavior, and no-index active/inactive behavior.

## Scope

In:
- SQLAlchemy model additions/updates.
- Alembic migration for missing MVP 1A columns/tables/indexes.
- Focused unit tests for schema/model contracts.
- Task log progress and verification notes.

Out:
- SEC network calls, daily index fetch/parse behavior, or EDGAR client code.
- Parser implementation or holdings ingestion.
- Frontend/admin UI.
- MVP 1B/MVP 2/MVP 3 schema unless already required by current DB compatibility.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §3.2-§3.6 Manager Management Center.
- `docs/prd/13f_automation_and_resilience_prd.md` §4.2-§4.4 Daily Sync Engine and sync statuses.
- `docs/prd/13f_automation_and_resilience_prd.md` §12 Job Runs, locks, retries.
- `docs/prd/13f_automation_and_resilience_prd.md` §13 no-index calendar API data contract.
- `docs/prd/13f_automation_and_resilience_prd.md` §14 indexes.
- `docs/prd/13f_automation_and_resilience_prd.md` §17 MVP 1A delivery plan.

## Files To Change

- `backend/app/models/institutions.py`
- `backend/alembic/versions/*`
- `backend/tests/unit/test_13f_schema_foundation.py`
- `docs/tasks/2026-05-09_13f-schema-foundation.md`

## Test Plan

Docker only:
- `docker compose up -d --build`
- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_schema_foundation.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Started `13F-1A-01` after reading the execution plan and PRD sections for managers, sync status, no-index dates, job runs, indexes, and MVP 1A scope.
- 2026-05-09: Existing repository already has early `institution_managers`, `job_runs`, `filings_13f`, and `holdings_13f` tables. This task will align the MVP 1A foundation without expanding parser/holdings behavior.
- 2026-05-09: No PRD/plan conflict found so far. G3 migration review will be triggered by this task.
- 2026-05-09: Wrote failing schema/model contract tests first. Initial red failure was missing PRD enum constants and missing model/table definitions.
- 2026-05-09: Added `edgar_sync_status`, `no_index_expected_dates`, manager PRD-facing fields, job lease fields, and application-level enum validation. Kept legacy `match_status` compatibility and mapped it into new manager `status` during model writes.
- 2026-05-09: Made existing `uq_job_runs_active_lock_key` migration idempotent because the local database already had the index while Alembic had not marked the revision applied.
- 2026-05-09: Verification passed:
  - `docker compose up -d --build`
  - `docker compose exec api alembic upgrade head`
  - `docker compose exec api pytest -q tests/unit/test_13f_schema_foundation.py`
  - `docker compose exec api pytest -q tests/unit` (`305 passed in 38.14s`)
- 2026-05-09: Gate status: G3 schema migration review is triggered and should happen before downstream 13F services depend on this schema.
- 2026-05-09: Contract check: no parser implementation, no SEC network calls, no frontend, no PRD edits, no MVP 2/MVP 3 work.
- 2026-05-09: G3 review accepted with no blocking findings. Follow-up notes accepted:
  - Use PRD spelling `canceled` consistently in job task-layer code.
  - Preserve CIKs as 10-digit strings; downstream ingestion should normalize/pad with leading zeroes before insert/query.
  - `edgar_legal_name` should be written from EDGAR confirmation in `13F-1A-02`; candidate rows without CIK may keep it null.
  - CUSIP temporal mapping remains out of scope for MVP 1A and should be handled by the later CUSIP task.
  - `job_runs.dedupe_key` indexing can be evaluated in the scheduler/dedupe task when the concrete query path lands.
- 2026-05-09: Addressed accepted test-coverage feedback by asserting `ix_job_runs_sync_date` and `ix_job_runs_lease_expires_at`, and by testing legacy `match_status` to PRD `status` runtime mapping.
- 2026-05-09: The new legacy mapping test exposed that SQLAlchemy object defaults may leave `status` as `None` before flush; fixed the model event to map legacy `match_status` when `status` is `None` or `candidate`.
- 2026-05-09: Post-review verification passed:
  - `docker compose exec api pytest -q tests/unit/test_13f_schema_foundation.py` (`40 passed`)
  - `docker compose exec api pytest -q tests/unit` (`310 passed in 37.19s`)
