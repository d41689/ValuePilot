# Task: Configure GitHub Actions CI

## Goal / Acceptance Criteria
- Add a GitHub Actions workflow that runs automatically when:
  - a pull request targets `main`
  - code is pushed directly to `main`
- The workflow uses Docker Compose as the canonical runtime.
- The workflow runs the project's relevant automated checks inside containers.

## Scope

### In
- Add `.github/workflows/ci.yml`
- Verify the workflow commands locally with Docker Compose
- Record any GitHub-side setup done with `gh`

### Out
- Changing product behavior
- Changing branch protection rules beyond the existing `main` rule
- Adding deployment automation

## PRD / Contract References
- AGENTS.md: Development & Execution Environment (Docker Compose)
- AGENTS.md: Running Tests (Docker Only)
- AGENTS.md: Minimal Verification Checklist

## Files To Change
- `.github/workflows/ci.yml`
- `docs/tasks/2026-04-22_configure-github-actions-ci.md`

## Execution Plan
1. Inspect current repo test and lint entry points.
2. Add a GitHub Actions workflow triggered by `pull_request` to `main` and `push` to `main`.
3. Use Docker Compose to build/start services and run backend/frontend verification in containers.
4. Run the same commands locally to verify behavior.
5. Push the workflow and confirm GitHub recognizes it.

## Rollback Strategy
- Revert `.github/workflows/ci.yml` if the workflow proves unstable.

## Test Plan
- `docker compose up -d --build`
- `docker compose exec -T api pytest -q`
- `docker compose exec -T web node --test lib/*.test.js`
- `docker compose exec -T web npm run lint`

## Notes
- 2026-04-22: Confirmed the repo did not have an existing `.github/workflows` directory.
- 2026-04-22: Plan is to use Docker Compose directly in Actions so CI matches local development.
- 2026-04-22: Added `.github/workflows/ci.yml` with triggers for `pull_request` to `main` and `push` to `main`.
- 2026-04-22: Discovered `docker-compose.yml` depends on the external network `projects-shared`, so the workflow creates that network before `docker compose up`.
- 2026-04-22: Local verification needed host port overrides because this machine already has other services bound to the default ports; the workflow now sets CI-safe host ports.
- 2026-04-22: First GitHub Actions run failed because the repo intentionally does not track root `.env`; updated the workflow to generate a minimal CI-only `.env` before starting Compose.

## Verification Results
- `HOST_WEB_PORT=13001 HOST_API_PORT=18001 docker compose up -d --build` -> pass
- `HOST_WEB_PORT=13001 HOST_API_PORT=18001 docker compose exec -T api alembic upgrade head` -> pass
- `HOST_WEB_PORT=13001 HOST_API_PORT=18001 docker compose exec -T api pytest -q` -> pass (`108 passed`)
- `HOST_WEB_PORT=13001 HOST_API_PORT=18001 docker compose exec -T web sh -lc 'node --test lib/*.test.js'` -> pass (`18/18`)
- `HOST_WEB_PORT=13001 HOST_API_PORT=18001 docker compose exec -T web npm run lint` -> pass (`No ESLint warnings or errors`)

## Contract Checks
- CI uses Docker Compose as the canonical runtime.
- Backend tests run inside the `api` container.
- Frontend tests and lint run inside the `web` container.
- No product behavior, schema, normalization, or lineage contracts were changed.
