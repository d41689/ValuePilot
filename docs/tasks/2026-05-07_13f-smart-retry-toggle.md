# 2026-05-07 13F Smart Retry Toggle

## Goal / Acceptance Criteria
- Add an independent `THIRTEENF_SMART_RETRY_ENABLED` setting for automatic smart retries.
- Keep Dashboard task visibility independent from automatic retry execution.
- Scheduler must only enqueue automatic smart retries when the new setting is enabled.
- Smart retry should support safe pipeline retry targets, including failed enrichment stages, while preserving accession retry safeguards.

## Scope
- In:
  - Backend settings and scheduler gating.
  - Smart retry target extraction for `quarterly_pipeline` stage failures.
  - Tests for disabled/enabled scheduler behavior and pipeline stage retry targets.
  - Production compose environment default.
- Out:
  - Frontend settings UI.
  - New database schema.
  - Changes to manual Dashboard retry behavior.

## Files to Change
- `backend/app/core/config.py`
- `backend/app/api/v1/endpoints/scheduler.py`
- `backend/app/services/scheduler.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_scheduler_alignment.py`
- `backend/tests/unit/test_smart_retries.py`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `README.md`

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_smart_retries.py`
- `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`

## Progress Notes
- 2026-05-07: Confirmed `run_smart_retries()` is already scheduled daily whenever `EDGAR_SCHEDULER_ENABLED=true`; the missing control is an independent smart retry kill switch and stage retry support.
- 2026-05-07: Added `THIRTEENF_SMART_RETRY_ENABLED` with default `false`; local compose keeps it explicit false, production compose sets it to `${THIRTEENF_SMART_RETRY_ENABLED:-true}`.
- 2026-05-07: Scheduler now only registers and executes the daily smart retry job when the new setting is enabled.
- 2026-05-07: Smart retry now consumes retry targets from job details, including failed `quarterly_pipeline` enrichment stages, but only auto-runs whitelisted targeted jobs: `ingest_accession`, `enrich_metadata`, and `quality_check`.
- 2026-05-07: Broad quarter-level stages such as `ingest_holdings` remain Dashboard/manual-only for safety.

## Verification
- 2026-05-07: `docker compose exec api pytest -q tests/unit/test_smart_retries.py` passed (`11 passed`).
- 2026-05-07: `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py` passed (`5 passed`).
- 2026-05-07: `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` passed (`38 passed`).

## Contract Checklist
- [x] No schema changes.
- [x] Dashboard task visibility remains independent from auto retry execution.
- [x] Auto retry has an explicit kill switch independent of `EDGAR_SCHEDULER_ENABLED`.
- [x] Auto retry preserves 24-hour cooling, active/succeeded skip checks, and max attempt guard.
- [x] No broad quarter-level ingestion reruns are auto-triggered by smart retry.
