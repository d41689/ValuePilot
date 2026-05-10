# 13F Job Scheduler Locks, Leases, Retry Skeleton

## Goal / Acceptance Criteria

Implement execution-plan task `13F-1A-05`: job execution primitives for daily sync and later ingestion tasks.

Acceptance criteria:
- Job creation uses `dedupe_key` and `lock_key` with active-job duplicate suppression.
- A second worker cannot claim a job with an unexpired lease.
- Expired leases can be taken over safely.
- Only the lease owner can heartbeat or complete a running job.
- Daily sync can be queued and executed through `job_runs`.
- Hourly polling respects `DAILY_SYNC_EARLIEST_ATTEMPT_ET` before queueing today's daily sync.
- Retry skeleton queues eligible `pending` / `failed` / retryable `partial_success` sync dates.
- Unexpected 404 retry policy can mark a sync date `no_data` only after configured retry count and end-of-day ET.
- Watchdog logic checks expired `lease_expires_at` and job timeout before abandoning stale jobs.
- Alert service abstraction records severity/message payloads and can send Discord if configured.

## Scope In

- Job scheduler service functions for daily sync jobs.
- Lease claim, heartbeat, completion, and expired-lease takeover primitives.
- Duplicate active-job suppression for daily sync and accession ingestion.
- Retry skeleton for daily sync status rows.
- Watchdog stale-running-job detection/marking foundation.
- Alert abstraction for P1/P2/P3 payloads.
- Focused unit tests with mocked sync execution and time.

## Scope Out

- Full alert rule coverage.
- Full MVP 1B filing parser orchestration.
- `parse_runs` implementation.
- Frontend UI.
- PRD edits.
- Schema changes unless blocked by approved plan.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §4.4 Daily Sync hourly worker and 404 retry policy.
- `docs/prd/13f_automation_and_resilience_prd.md` §12 job_runs locks, leases, statuses, and timeouts.
- `docs/prd/13f_automation_and_resilience_prd.md` §15 alert severities and foundation.
- `docs/tasks/2026-05-09_13f-automation-development-plan.md` `13F-1A-05`.

## Files To Change

- `backend/app/services/*`
- `backend/app/api/v1/endpoints/*` if job trigger behavior needs route exposure.
- `backend/app/core/*` if config defaults are missing.
- `backend/tests/unit/*`
- `docs/tasks/2026-05-09_13f-job-scheduler-lease.md`

## Test Plan

Docker only:
- `docker compose exec api pytest -q tests/unit/test_13f_job_scheduler.py`
- `docker compose exec api pytest -q tests/unit/test_13f_alerts.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Started after 13F-1A-04 approval and review fixes. Read execution plan `13F-1A-05` and PRD §4.4, §12, §15.
- 2026-05-09: Added red tests first:
  - `tests/unit/test_13f_job_scheduler.py`
  - `tests/unit/test_13f_alerts.py`
  - scheduler registration coverage in `tests/unit/test_scheduler_alignment.py`
- 2026-05-09: Initial red tests failed because lease completion/heartbeat helpers, scheduler daily poll service, and alert abstraction did not exist.
- 2026-05-09: Implemented lease primitives in `thirteenf_job_worker`:
  - queued job claim assigns `lease_token` and `lease_expires_at`.
  - running jobs with expired leases can be claimed by another worker.
  - heartbeat and completion require matching `worker_id` + `lease_token`.
  - stale running jobs are marked failed only when both timeout and expired lease conditions hold.
- 2026-05-09: Implemented scheduler primitives:
  - `queue_daily_sync_poll` queues `fetch_daily_index:{sync_date}` jobs after `DAILY_SYNC_EARLIEST_ATTEMPT_ET`.
  - active duplicate jobs are suppressed by `dedupe_key` while `queued` / `running` / `cancel_requested`.
  - failed sync rows can transition to `no_data` after retry exhaustion and end-of-day ET.
  - APScheduler registers hourly `daily_13f_sync_poll`.
- 2026-05-09: Integrated daily sync with `job_runs`:
  - `trigger_job` supports `fetch_daily_index` lock key and persists `sync_date`.
  - `execute_job_payload("fetch_daily_index", ...)` calls `run_daily_index_sync`.
- 2026-05-09: Added alert foundation:
  - P1/P2/P3 payload validation.
  - Discord webhook transport when configured.
  - in-memory transport for tests.
- 2026-05-09: Scope guard:
  - Did not implement full MVP 1B parser orchestration.
  - Did not introduce `parse_runs`.
  - Did not add frontend UI.
  - Did not edit PRD or schema.
- 2026-05-09: Docker verification passed:
  - `docker compose exec api pytest -q tests/unit/test_13f_job_scheduler.py` -> `9 passed in 0.11s`
  - `docker compose exec api pytest -q tests/unit/test_13f_alerts.py tests/unit/test_scheduler_alignment.py tests/unit/test_13f_admin_dashboard.py` included in related run -> `67 passed in 9.16s`
  - `docker compose exec api pytest -q tests/unit/test_13f_daily_index_sync.py tests/unit/test_smart_retries.py` -> `16 passed in 0.20s`
  - `docker compose exec api pytest -q tests/unit` -> `354 passed in 40.34s`
