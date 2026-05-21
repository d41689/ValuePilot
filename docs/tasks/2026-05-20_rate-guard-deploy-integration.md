# Task — Rate Guard prod deploy integration

Date: 2026-05-20
Branch: `claude/rate-guard-deploy-integration`
Design: `docs/tasks/2026-05-20_rate-guard-design.md`

## Goal

Bring the Rate Guard service into the prod deploy pipeline **before** Rate
Guard PR 2/4 repoints `EdgarClient` at it. PR 2/4 makes a live-mode prod api
**hard-depend** on Rate Guard (missing `RATE_GUARD_URL` → startup error). The
self-hosted runner auto-deploys every `main` push, so that dependency must be
satisfiable at deploy time: Rate Guard has to already be running and reachable.

## Acceptance criteria

- `scripts/deploy_prod_from_main.sh` brings up `docker-compose.rateguard.yml`
  and waits for its `/healthz` **before** the prod stack — a broken limiter
  aborts the deploy instead of shipping a prod that will later depend on it.
- The deploy workflow prints Rate Guard logs on failure (debuggability).
- An operator runbook (`rate-guard/README.md`) documents the required host
  `.env` keys, including `RATE_GUARD_URL` for the upcoming PR 2/4.
- Canonical CI stays green; the deploy script passes `sh -n` and
  `docker compose config` validates the rateguard compose.

## Scope

**In**

- `scripts/deploy_prod_from_main.sh` — Rate Guard up + healthcheck, ordered
  before the prod stack; `wait_for_url` hoisted above first use.
- `.github/workflows/deploy.yml` — failure step also dumps rateguard logs.
- `rate-guard/README.md` — operator runbook.
- Design-doc build log entry.

**Out**

- Repointing `EdgarClient` / `OpenFigiClient` / `DataromaClient` — that is
  PR 2/4 and PR 3/4.
- Adding `RATE_GUARD_URL` to `backend/app/core/config.py` — added in PR 2/4
  where it is first read.
- Editing the host `.env` files — they live at `~/.config/valuepilot/.env*`,
  outside the repo. The runbook documents what the operator must add.

## Manual pre-merge step for PR 2/4 (not this PR)

Before Rate Guard PR 2/4 merges, add to `~/.config/valuepilot/.env`:

```
RATE_GUARD_URL=http://rate-guard:9000
```

The prod `api` service is already on the `projects-shared` network, so it
resolves the `rate-guard` service by name. This PR only ensures Rate Guard is
running there; PR 2/4 is what starts reading `RATE_GUARD_URL`.

## Test plan

- `sh -n scripts/deploy_prod_from_main.sh` — shell syntax.
- `docker compose -f docker-compose.rateguard.yml config` — compose validates.
- Rate Guard image builds and serves `/healthz` (verified earlier this batch).
- Canonical CI commands green in-container.
- True end-to-end (Rate Guard up + healthz + prod stack) runs on the prod
  self-hosted runner at deploy time — it cannot be fully exercised off-host
  because it depends on the prod `.env` and the live `projects-shared` network.

## Sign-off trail

- Deploy script + workflow + runbook written; `sh -n` and `compose config`
  pass; canonical CI green.
