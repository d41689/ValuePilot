# Task: Add automatic local deployment from main

## Goal / Acceptance Criteria
- After code is merged to `main`, GitHub Actions automatically deploys the latest `main` code to this local machine.
- Deployment must happen on a self-hosted runner running on this machine.
- Deployment must use the existing prod Docker Compose entrypoint.
- Deployment must not overwrite the active development workspace used for coding.
- Deployment must verify the prod API and web service after restarting.

## Scope

### In
- Add a GitHub Actions deployment workflow
- Add a deployment script for the local prod stack
- Configure a dedicated self-hosted runner for the `ValuePilot` repo on this machine
- Set up stable local config files for deploy-time `.env` and `.env.prod`

### Out
- Changing application product behavior
- Changing domain or cloudflared configuration
- Replacing the existing prod Docker Compose topology

## PRD / Contract References
- AGENTS.md: Development & Execution Environment (Docker Compose)
- AGENTS.md: Running Tests (Docker Only)
- AGENTS.md: Minimal Verification Checklist
- docs/prd/value-pilot-prd-v0.1.md -> Docker-based runtime / deployment expectations

## Files To Change
- `.github/workflows/deploy.yml`
- `scripts/deploy_prod_from_main.sh`
- `docs/tasks/2026-04-22_add-main-auto-deploy.md`

## Execution Plan
1. Inspect the current CI, prod compose setup, and local runner state.
2. Add a deployment workflow triggered after successful `CI` runs on `main`, plus `workflow_dispatch` for verification.
3. Add a local deployment script that creates prerequisites, deploys the prod stack, and verifies health.
4. Configure a dedicated repo-level self-hosted runner on this machine.
5. Move deploy-time local env files into a stable host config directory and have the workflow copy them into the runner workspace.
6. Validate the workflow on a branch with `workflow_dispatch`.
7. Merge to `main` and confirm the post-merge automatic deployment path succeeds.

## Rollback Strategy
- Disable or remove `.github/workflows/deploy.yml`.
- Stop and uninstall the dedicated self-hosted runner service for `ValuePilot`.

## Test Plan
- `bash -n scripts/deploy_prod_from_main.sh`
- `docker compose -f docker-compose.prod.yml config`
- Manual `workflow_dispatch` run of the deploy workflow on the feature branch
- Merge to `main` and verify the automatic deploy workflow succeeds

## Notes
- 2026-04-22: Found an existing local runner at `/Users/huawang/actions-runner`, but it is registered to `d41689/MathPilot`, not `ValuePilot`.
- 2026-04-22: Found no repo-level runners registered for `d41689/ValuePilot`.
- 2026-04-22: Added `.github/workflows/deploy.yml` with `workflow_run` on successful `CI` runs and `workflow_dispatch` for manual verification.
- 2026-04-22: Added `scripts/deploy_prod_from_main.sh` to create the shared Docker network, deploy the prod stack, and wait for API/web readiness.
- 2026-04-22: Copied the local deploy-time `.env` and `.env.prod` files into `$HOME/.config/valuepilot/` so the self-hosted runner can install them into its workspace.
- 2026-04-22: Registered a dedicated repo-level self-hosted runner at `/Users/huawang/actions-runner-valuepilot` with label `valuepilot-prod`.
- 2026-04-22: Verified the new runner is online in GitHub for `d41689/ValuePilot`.
