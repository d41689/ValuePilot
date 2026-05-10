# 13F-1B-08: Backfill Preview and Confirmed Ingestion Jobs

## Goal
Implement explicit admin-driven backfill preview and confirmed job creation.

## Scope (In)
- Preview estimated filings, EDGAR request count, rate limit wait, date/quarter range.
- Use `DEFAULT_BACKFILL_START_QUARTER=2023-Q1` unless overridden.
- Flag backfill must use dual thousands/dollars if pre-2023-Q1.
- Explicit confirmation endpoint for enqueueing backfill.
- Job records for filing ingestion.

## Test Plan
- Run `docker compose exec api pytest -q tests/unit/test_13f_backfill.py`

## Execution Notes
- Modified `build_manager_backfill_preview` to accept `start_quarter` and `end_quarter`. It uses the `EdgarClient` to hit the SEC `submissions` API to precisely count the number of expected 13F-HR filings.
- The preview successfully alerts with `value_unit_risk_warning=True` when dealing with filings filed prior to January 1st, 2023.
- Implemented explicit POST `/api/v1/admin/managers/{manager_id}/backfill` endpoint which queues up a `sync_manager_backfill` job without affecting standard CIK confirmation endpoints.
- Added `sync_manager_backfill` lock handling in `thirteenf_admin_dashboard.py` and timeout bounds in `thirteenf_job_worker.py`. 
- Written and executed `test_13f_backfill.py` which passes locally in Docker.
