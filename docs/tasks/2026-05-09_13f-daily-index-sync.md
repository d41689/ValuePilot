# 13F Daily Index Sync

## Goal / Acceptance Criteria

Implement execution-plan task `13F-1A-04`: daily SEC `form.idx` fetch/parse for active tracked managers, sync status persistence, and no-index calendar maintenance APIs.

Acceptance criteria:
- Fetch daily `form.YYYYMMDD.idx` through the shared `EdgarClient`.
- Save raw daily index content for audit.
- Parse and count `13F-HR`, `13F-HR/A`, and `13F-NT`.
- Match only active tracked managers by CIK.
- Matched rows expose SEC `accession_number` for downstream ingestion dedupe.
- Update `edgar_sync_status` with `success`, `failed`, `no_data`, or `partial_success` as applicable.
- Apply expected no-index date rules for 404 responses.
- Expose admin APIs for no-index dates:
  - `GET /api/v1/admin/13f/no-index-dates`
  - `POST /api/v1/admin/13f/no-index-dates`
  - `PATCH /api/v1/admin/13f/no-index-dates/{date}`
- Do not infer report quarter from sync date.

## Scope In

- Daily index URL construction and fetch orchestration.
- Narrow `form.idx` parser for daily index rows.
- `edgar_sync_status` updates and raw daily index audit persistence.
- Job placeholder/dedupe record creation only where required by the existing schema.
- No-index date list/create/patch service and API endpoints.
- Unit tests with local fixtures/mocks.

## Scope Out

- Filing detail/header fetch.
- Information table fetch or parser implementation.
- Holdings persistence.
- 13F-NT period/other-manager processing beyond daily index discovery/counting.
- Frontend UI.
- PRD edits.
- Schema changes unless a missing field blocks the approved plan.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §4.2-§4.4 Daily Sync Engine.
- `docs/prd/13f_automation_and_resilience_prd.md` §13 sync and no-index APIs.
- `docs/prd/13f_automation_and_resilience_prd.md` §15.2 alert conditions.
- `docs/tasks/2026-05-09_13f-automation-development-plan.md` `13F-1A-04`.

## Files To Change

- `backend/app/edgar/*`
- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*`
- `backend/app/schemas/*`
- `backend/tests/unit/*`
- `backend/tests/fixtures/*`
- `docs/tasks/2026-05-09_13f-daily-index-sync.md`

## Test Plan

Docker only:
- `docker compose exec api pytest -q tests/unit/test_13f_daily_index_sync.py`
- `docker compose exec api pytest -q tests/unit/test_13f_no_index_dates.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Started after G3 was approved and G2 was closed by Tech Lead review. Read execution plan `13F-1A-04` and PRD §4.2-§4.4, §13, §15.2.
- 2026-05-09: Added red tests first:
  - `tests/unit/test_13f_daily_index_sync.py`
  - `tests/unit/test_13f_no_index_dates.py`
  - fixture `tests/fixtures/13f/daily_index/2024-02-14_form.idx`
- 2026-05-09: Initial red test results:
  - `docker compose exec api pytest -q tests/unit/test_13f_daily_index_sync.py` failed because `app.services.thirteenf_daily_sync` did not exist.
  - `docker compose exec api pytest -q tests/unit/test_13f_no_index_dates.py` failed with 404 because no-index admin routes were not implemented.
- 2026-05-09: Implemented narrow daily sync:
  - Added daily `form.YYYYMMDD.idx` URL helper.
  - Added daily 13F parser path for `13F-HR`, `13F-HR/A`, and `13F-NT`.
  - Persisted raw daily index document as `daily_form_idx`.
  - Matched only `InstitutionManager.status == "active"` and non-null CIK.
  - Created `ingest_accession` JobRun placeholders only for matched `13F-HR` / `13F-HR/A`, with `dedupe_key` set to the accession number.
  - Updated `edgar_sync_status` with counts and 404 no-index handling.
- 2026-05-09: Implemented no-index admin APIs:
  - `GET /api/v1/admin/13f/no-index-dates`
  - `POST /api/v1/admin/13f/no-index-dates`
  - `PATCH /api/v1/admin/13f/no-index-dates/{date}`
  - Manual creation rejects `weekend` and `federal_holiday` because those are `auto_generated`.
  - Patch soft-disables with `active=false`; no physical delete path.
- 2026-05-09: Scope guard:
  - Did not fetch filing detail/header.
  - Did not parse information tables.
  - Did not infer report quarter from sync date.
  - Did not implement holdings persistence or frontend UI.
  - Did not modify PRD or schema.
- 2026-05-09: Docker verification passed:
  - `docker compose exec api pytest -q tests/unit/test_13f_daily_index_sync.py` -> `3 passed in 0.13s`
  - `docker compose exec api pytest -q tests/unit/test_13f_no_index_dates.py` -> `4 passed in 0.83s`
  - `docker compose exec api pytest -q tests/unit/test_13f_parsers.py` -> `15 passed in 0.03s`
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_manager_admin_backend.py` -> `58 passed in 10.52s`
  - `docker compose exec api pytest -q tests/unit` -> `340 passed in 38.07s`
- 2026-05-09: Tech Lead reviews approved 13F-1A-04. Accepted Claude review NB-1/NB-3/NB-4:
  - Dedupe now skips only active `ingest_accession` jobs with status `queued`, `running`, or `cancel_requested`; failed/completed jobs no longer permanently block re-queue.
  - `matched_accessions` now includes `job_enqueued` so 13F-NT and already-active HR/HR-A rows are explicit.
  - Added idempotency and failed-job requeue tests.
- 2026-05-09: Deferred Claude review NB-2 to 13F-1A-05: PRD §4.4 retry-count + end-of-day ET -> `no_data` requires scheduler timing policy and should not be implemented inside the single-run sync helper.
- 2026-05-09: Docker verification after review fixes passed:
  - `docker compose exec api pytest -q tests/unit/test_13f_daily_index_sync.py` -> `5 passed in 0.14s`
  - `docker compose exec api pytest -q tests/unit/test_13f_no_index_dates.py` -> `4 passed in 0.85s`
  - `docker compose exec api pytest -q tests/unit/test_13f_parsers.py tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_manager_admin_backend.py` -> `73 passed in 10.38s`
  - `docker compose exec api pytest -q tests/unit` -> `342 passed in 39.73s`
