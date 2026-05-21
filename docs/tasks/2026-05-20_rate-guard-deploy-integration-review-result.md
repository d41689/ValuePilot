# Review result — Rate Guard prod deploy integration (PR #79)

Date: 2026-05-20
Branch reviewed: `claude/rate-guard-deploy-integration`
Prompt: `docs/tasks/2026-05-20_rate-guard-deploy-integration-review-prompts.md`

## Verdict

**暂不批准 / not approved**

The main deploy ordering is correct: Rate Guard is started and health-checked
before the prod stack, `wait_for_url` is defined before both call sites, the
shared network is created early, and the health URL matches the compose file
and FastAPI route.

However, the PR overstates the safety/idempotency of
`docker compose -f docker-compose.rateguard.yml up -d --build` for a shared
prod+dev infrastructure service. Compose can recreate the Rate Guard container
for reasons beyond changes under `rate-guard/` (env file changes, compose
config changes, changed image digest, forced recreate, etc.). More importantly,
if a Rate Guard deploy does recreate the existing shared container and the new
container never becomes healthy, the script safely stops before redeploying the
prod app stack, but the previously healthy shared Rate Guard may already be
gone. Once PR 2/4 makes prod live-mode egress hard-depend on Rate Guard, that
failure mode can leave the currently running prod app with a broken dependency.

## Blocking findings

1. **False idempotency/recreation claim in deploy script comment.**
   - File: `scripts/deploy_prod_from_main.sh:50-51`
   - Current text says compose only recreates the container when `rate-guard/`
     changed. That is not accurate for `up -d --build`: service config/env
     changes and image changes can also recreate the container.
   - Fix: soften the claim to describe actual Compose behavior, or remove it.

2. **False idempotency/recreation claim in operator runbook.**
   - File: `rate-guard/README.md:25-26`
   - Same inaccurate claim appears in operator-facing docs, which is risky for
     a shared limiter used by both dev and prod.
   - Fix: document that `up -d --build` is repeatable, but may recreate the
     shared Rate Guard when its image or service config changes.

3. **Rate Guard deployment is not fail-safe for the existing shared Rate Guard
   instance.**
   - File: `scripts/deploy_prod_from_main.sh:53-54`
   - The script starts/recreates Rate Guard, then waits for health. If the new
     container replaces a healthy old one and fails health, prod app deployment
     is skipped, but the shared Rate Guard dependency itself can remain down.
   - Fix: either add an explicit rollback/recovery plan for a failed Rate Guard
     recreation, or document this as an accepted operational risk and ensure
     the failure path preserves/restores the last healthy Rate Guard where
     feasible.

## Per-question findings

### A. Ordering & correctness

- **A1: PASS.** `scripts/deploy_prod_from_main.sh:29-45` defines
  `wait_for_url` before the Rate Guard call at line 54 and the prod health
  calls at lines 63-64. Rate Guard `up` runs at line 53 before prod stack `up`
  at line 57. `sh -n scripts/deploy_prod_from_main.sh` passed.
- **A2: PASS.** `projects-shared` is inspected/created at
  `scripts/deploy_prod_from_main.sh:20-22`, before Rate Guard starts. This is
  required because `docker-compose.rateguard.yml:30-33` declares the network as
  external.
- **A3: PASS.** Health URL is
  `http://127.0.0.1:${RATE_GUARD_HOST_PORT:-9099}/healthz`
  (`scripts/deploy_prod_from_main.sh:52-54`). Compose maps
  `${RATE_GUARD_HOST_PORT:-9099}:9000` (`docker-compose.rateguard.yml:21-24`),
  and the service defines `GET /healthz` in `rate-guard/app/main.py:35-37`.

### B. Failure modes & safety

- **B4: FAIL.** With `set -eu`, a failed `wait_for_url` returns non-zero and
  aborts before `docker compose -f docker-compose.prod.yml up -d --build`, so
  the prod app stack is not redeployed. That part is safe. The gap is that the
  Rate Guard `up` may already have replaced the existing shared Rate Guard, so
  a failed Rate Guard update can leave the current prod/dev dependency down.
- **B5: advisory.** The 60s wait covers container startup after image build,
  not build time. That is generally adequate for this small FastAPI service;
  first-deploy edge cases are mostly config failure, port conflict, or a bad
  image rather than slow startup.
- **B6: advisory.** Blocking prod deploys on Rate Guard before PR 2/4 is a
  reasonable trade-off because it proves the deployment prerequisite before
  the app starts hard-depending on it. The trade-off should be called out
  explicitly: until PR 2/4, an unrelated prod deploy can fail solely because
  Rate Guard is misconfigured.

### C. Idempotency & shared instance

- **C7: FAIL.** The claim that `up -d --build` only recreates when
  `rate-guard/` changed is inaccurate. It is repeatable/idempotent in the
  usual Compose sense, but container recreation can also be triggered by env
  file changes, compose config changes, image changes, or explicit recreate
  options.
- **C8: advisory.** A prod deploy that changes Rate Guard can briefly drop dev
  in-flight requests because there is one shared instance. That is an accepted
  consequence of the one-limiter design, but it should be documented as
  operator-visible behavior.
- **C9: PASS.** Cache persists across deploys: Rate Guard uses the bind mount
  `./storage/rate_guard_cache:/data/cache`
  (`docker-compose.rateguard.yml:25-26`), and the deploy workflow preserves
  untracked workspace files with `clean: false`
  (`.github/workflows/deploy.yml:32-41`).

### D. Runbook

- **D10: FAIL.** The internal URL `http://rate-guard:9000`, host port `9099`,
  required `SEC_CONTACT_EMAIL`, optional `OPENFIGI_API_KEY`, optional
  `RATE_GUARD_HOST_PORT`, and PR 2/4 `RATE_GUARD_URL` instruction are correct.
  The runbook fails on the inaccurate idempotency/recreation statement at
  `rate-guard/README.md:25-26`.
- **D11: PASS.** Prod `api` joins `shared-infra`
  (`docker-compose.prod.yml:51-53`), which maps to external
  `projects-shared` (`docker-compose.prod.yml:66-69`). Rate Guard service name
  is `rate-guard` (`docker-compose.rateguard.yml:10-11`) on the same external
  network, so Docker DNS should resolve `rate-guard`.

### E. Scope & cross-checks

- **E12: PASS.** The PR diff touches only `.github/workflows/deploy.yml`,
  `scripts/deploy_prod_from_main.sh`, `rate-guard/README.md`, and task/design
  docs. No backend/frontend application code changed.
- **E13: PASS.** No dev compose file defines a Rate Guard service. The only
  Rate Guard service definition is in `docker-compose.rateguard.yml`.
- **E14: PASS.** Deferring `RATE_GUARD_URL` from `backend/app/core/config.py`
  is correct for this PR because the application does not read it until PR 2/4.
  The runbook correctly instructs operators to add the env var before PR 2/4
  merges.

### F. Tests / verification

- **F15: advisory.** `sh -n` passed. `docker compose -f
  docker-compose.rateguard.yml config` and `docker compose -f
  docker-compose.prod.yml config` passed. `git diff --check origin/main...HEAD`
  passed. `shellcheck` could not be run locally because it is not installed in
  this workspace. For this deploy-chain change, `sh -n` + compose config +
  line-by-line runbook review is mostly adequate, but adding `shellcheck` would
  be a useful extra gate for future shell changes.

## Verification performed

- `sh -n scripts/deploy_prod_from_main.sh` — passed.
- `docker compose -f docker-compose.rateguard.yml config` — passed.
- `docker compose -f docker-compose.prod.yml config` — passed.
- `git diff --check origin/main...HEAD` — passed.
- `shellcheck scripts/deploy_prod_from_main.sh` — not run; `shellcheck` is not
  installed in the local environment.

Full end-to-end deploy was not exercised because it depends on the prod host's
live `.env` files, Docker daemon state, and self-hosted runner environment.

## Non-blocking follow-ups

- Document that Rate Guard restarts can briefly interrupt dev in-flight
  requests because dev and prod intentionally share one limiter.
- Consider a future safer Rate Guard rollout path if the service becomes
  critical for more than EDGAR live-mode egress, for example a staged health
  probe before replacing the active shared instance or an explicit rollback
  procedure.
