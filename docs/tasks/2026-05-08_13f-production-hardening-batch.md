# 2026-05-08 13F Production Hardening Batch

## Goal / Acceptance Criteria
- Deliver the next three highest-value production hardening items for the 13F Admin system:
  1. Stale running JobRun recovery / lock release.
  2. Structured dry-run confirmation modal for heavy admin jobs.
  3. Smart retry observability in the Admin Dashboard.
- Preserve existing JobRun audit trail and lock-key duplicate prevention.
- Keep manual retry and Dashboard task behavior intact.

## Scope
- In:
  - Detect running/cancel-requested jobs whose worker heartbeat is stale.
  - Add a safe admin action to mark stale running jobs failed and release their active lock.
  - Surface stale running job tasks and Job Detail recovery affordance.
  - Replace `window.confirm` dry-run UX with a shadcn-style Dialog that displays preview scope, warnings, and lock key.
  - Surface `THIRTEENF_SMART_RETRY_ENABLED` status in admin readiness/status UI.
- Out:
  - Automatic force-killing workers or OS processes.
  - Schema changes.
  - Parallel accession child-job fan-out.
  - New global settings editor UI.

## Files to Change
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `frontend/components/ui/dialog.tsx` if a shared Dialog component does not already exist.
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `docs/tasks/2026-05-08_13f-production-hardening-batch.md`

## Execution Plan
1. Stale running JobRun recovery
   - Add backend detection for stale running/cancel-requested jobs using `JobRun.heartbeat_at` and `THIRTEENF_JOB_WORKER_HEARTBEAT_STALE_S`.
   - Add a service action that only releases a lock by marking the job `failed` when it is stale; non-stale running jobs remain protected.
   - Add an admin endpoint, likely `POST /api/v1/admin/13f/jobs/{id}/release-stale-lock`.
   - Add task metadata and retry/recovery hints so admins can find and resolve stale locks.
   - Add unit tests for stale detection, successful release, rejection of non-stale release, and lock reuse after release.

2. Dry-run confirmation modal
   - Add or reuse a shared `Dialog` component under `frontend/components/ui/`.
   - Refactor `runJob()` to request dry-run preview, store pending job state, and open a modal instead of calling `window.confirm`.
   - Modal should display job label/type, lock key, target quarter/accession, rate-limit warning, and estimated scope fields.
   - Confirm button submits `dry_run: false`; cancel clears pending state.
   - Keep fallback path for failed preview, but display it in the modal rather than relying on a browser confirm.

3. Smart retry observability
   - Extend frontend normalization to preserve `smart_retry_enabled`.
   - Add an Admin Dashboard status indicator that distinguishes scheduler enabled, smart retry enabled, and worker availability.
   - Add frontend unit coverage for the new normalized field.
   - Keep this display read-only; no settings mutation in this task.

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q tests/unit/test_smart_retries.py`
- `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py`
- `docker compose exec web npm run lint`
- If frontend library tests are runnable in the repo, run the existing `frontend/lib/thirteenfAdmin.test.js` path with the project’s established command.

## Contract Checks
- Stale recovery must not mutate completed/canceled jobs.
- Stale recovery must not release an active running job with a fresh heartbeat.
- Released stale jobs must retain audit evidence through `error_message`, `finished_at`, and existing `input_json`.
- Dry-run must remain mandatory before manual job trigger from the Dashboard.
- Smart retry observability must not expose admin-only details through consumer readiness.

## Rollback Strategy
- Revert the endpoint/service/UI changes together.
- No migration rollback is needed because this task does not change schema.

## Progress Notes
- 2026-05-08: Initial plan created after reviewing current JobRun heartbeat handling, dry-run preview flow, and smart retry readiness fields.
- 2026-05-08: Added stale running JobRun detection to admin tasks and Job Detail. Stale release is restricted to `running` / `cancel_requested` jobs whose heartbeat is older than `THIRTEENF_JOB_WORKER_HEARTBEAT_STALE_S`.
- 2026-05-08: Added `POST /api/v1/admin/13f/jobs/{job_id}/release-stale-lock`; release marks the job `failed`, records an error message, sets `finished_at`, and frees the active lock without deleting audit data.
- 2026-05-08: Replaced manual-job `window.confirm` dry-run flow with a structured Dialog that shows action, job type, lock key, target scope, estimated counts, and rate-limit warnings before queueing.
- 2026-05-08: Added read-only Dashboard badges for scheduler, smart retry, and worker availability. `normalizeReadiness()` now preserves `smartRetryEnabled`.
- 2026-05-08: Review fixes: stale release no longer overwrites `heartbeat_at`; stale lock release now uses Dialog confirmation; Dialog now wires `aria-labelledby`; worker availability ignores stopped/error workers; dry-run preview preserves `false` and `0` scope values.

## Verification
- 2026-05-08: `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` passed (`40 passed`).
- 2026-05-08: `docker compose exec api pytest -q tests/unit/test_smart_retries.py` passed (`11 passed`).
- 2026-05-08: `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py` passed (`5 passed`).
- 2026-05-08: `docker compose exec web node --test lib/thirteenfAdmin.test.js` passed (`9 passed`).
- 2026-05-08: `docker compose exec web npm run lint` passed with no ESLint warnings or errors.
- 2026-05-08: Post-review verification repeated: `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` passed (`40 passed`); `docker compose exec api pytest -q tests/unit/test_smart_retries.py tests/unit/test_scheduler_alignment.py` passed (`16 passed`); `docker compose exec web node --test lib/thirteenfAdmin.test.js` passed (`9 passed`); `docker compose exec web npm run lint` passed.
