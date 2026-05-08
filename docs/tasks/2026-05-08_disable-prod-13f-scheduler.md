# Task: Disable production 13F scheduler

## Goal / Acceptance Criteria
- Disable automatic production 13F / EDGAR scheduler so development testing can use SEC access without production competing for rate limits.
- Disable production 13F background worker and smart retry automation for the same SEC rate-limit protection.
- Production compose reads the scheduler flag from the production environment file.
- Record the exact environment file and variable changed.

## Scope
- In:
  - `docker-compose.prod.yml`
  - `.env.prod`
  - `docs/tasks/2026-05-08_disable-prod-13f-scheduler.md`
- Out:
  - 13F parser, ingestion, API, schema, or UI behavior changes.
  - Development environment 13F settings.

## Files To Change
- `docker-compose.prod.yml`: remove hardcoded 13F production overrides so `.env.prod` controls the values.
- `.env.prod`: set `EDGAR_SCHEDULER_ENABLED=false`, `THIRTEENF_SMART_RETRY_ENABLED=false`, and `THIRTEENF_JOB_WORKER_ENABLED=false`.

## Test Plan
- Docker verification is not required for this configuration-only safety change.
- Verify with static checks:
  - `rg -n "EDGAR_SCHEDULER_ENABLED" .env.prod docker-compose.prod.yml`

## Notes
- 2026-05-08: Found production compose loads `.env` and `.env.prod`, but hardcoded `EDGAR_SCHEDULER_ENABLED: "true"` in `docker-compose.prod.yml` would override `.env.prod`.
- 2026-05-08: Set `.env.prod` `EDGAR_SCHEDULER_ENABLED=false` and removed the hardcoded production compose override so the env file value reaches the API container.
- 2026-05-08: Verified with `docker compose -f docker-compose.prod.yml config`; the API service receives `EDGAR_SCHEDULER_ENABLED="false"`.
- 2026-05-08: After pulling latest `main`, resolved the production compose conflict by removing newly hardcoded `THIRTEENF_SMART_RETRY_ENABLED` and `THIRTEENF_JOB_WORKER_ENABLED` overrides too; set both to `false` in `.env.prod`.
- 2026-05-08: Confirmed GitHub Runner deploys from `/Users/huawang/actions-runner-valuepilot/_work/ValuePilot/ValuePilot` and copies env files from `/Users/huawang/.config/valuepilot/`.
- 2026-05-08: Updated the Runner deploy-time `/Users/huawang/.config/valuepilot/.env.prod` with `EDGAR_SCHEDULER_ENABLED=false`, `THIRTEENF_SMART_RETRY_ENABLED=false`, and `THIRTEENF_JOB_WORKER_ENABLED=false`.
