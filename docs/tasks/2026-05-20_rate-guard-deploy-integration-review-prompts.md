# Review prompt — Rate Guard prod deploy integration (PR #79)

Give this prompt to an independent review agent. It should review the branch
`claude/rate-guard-deploy-integration` (PR #79) on its own, run the checks it
needs, and write a verdict.

---

## Context

ValuePilot runs dev and prod on the **same host, same outbound IP**. Rate
Guard (`rate-guard/`, merged in PRs #76 + #78) is a small FastAPI service that
acts as the single egress chokepoint for rate-limited upstreams (SEC EDGAR,
OpenFIGI, Dataroma), so the *combined* dev+prod egress rate is bounded and
cannot trigger an IP ban.

Rate Guard is built in phases (`docs/tasks/2026-05-20_rate-guard-design.md`
§10). PR 1/4 (the service) is merged but **nothing points at it yet**. The
**next** phase, PR 2/4, repoints `EdgarClient` at Rate Guard and adds a
live-mode startup guard: in `EDGAR_FETCH_MODE=live`, a missing `RATE_GUARD_URL`
becomes a **hard startup error**.

A self-hosted GitHub runner **auto-deploys every `main` push**
(`.github/workflows/deploy.yml` → `scripts/deploy_prod_from_main.sh` →
`docker compose -f docker-compose.prod.yml up -d --build`). So once PR 2/4
merges, the prod `api` will hard-depend on Rate Guard at deploy time.

**PR #79 (this PR) is the deploy-integration step that must land before
PR 2/4**: it makes the prod deploy pipeline bring Rate Guard up first, so the
PR 2/4 dependency is satisfiable. PR #79 contains **no application code** — only
the deploy script, the deploy workflow, an operator runbook, and docs.

Background docs to read first:
- `docs/tasks/2026-05-20_rate-guard-deploy-integration.md` — this PR's task doc.
- `docs/tasks/2026-05-20_rate-guard-design.md` — §3, §6 (topology), §7, §10.

## What changed in PR #79

- `scripts/deploy_prod_from_main.sh` — brings up `docker-compose.rateguard.yml`
  and waits for `/healthz` **before** the prod stack; `wait_for_url` hoisted
  above its first use.
- `.github/workflows/deploy.yml` — the on-failure step also dumps rateguard
  logs.
- `rate-guard/README.md` — operator runbook (new file).
- `docs/tasks/2026-05-20_rate-guard-deploy-integration.md` — task doc (new).
- `docs/tasks/2026-05-20_rate-guard-design.md` — build-log entry.

## The bar

PR #79 is correct if, after it merges, **a normal `main` deploy leaves Rate
Guard running and healthy on the `projects-shared` network before the prod
stack starts**, and a Rate Guard failure fails the deploy *safely* (prod keeps
running its previous version) rather than shipping a broken state. The runbook
must accurately tell an operator what to configure.

## Questions to answer

Answer each explicitly. Reproduce what you can (`sh -n`, `docker compose
config`, reading the compose files); state clearly what cannot be exercised
off the prod host and why.

### A. Ordering & correctness
1. Does `scripts/deploy_prod_from_main.sh` bring Rate Guard up **before** the
   prod stack, and wait for its `/healthz`? Is `wait_for_url` defined before
   **both** call sites? Does `sh -n` pass?
2. The `projects-shared` network is created earlier in the script. Confirm the
   network exists before the rateguard `up` (the rateguard compose declares it
   `external`).
3. Is the health URL correct — host port `${RATE_GUARD_HOST_PORT:-9099}`, path
   `/healthz`? Does that match `docker-compose.rateguard.yml` and the service's
   actual route?

### B. Failure modes & safety
4. If Rate Guard never becomes healthy (e.g. `SEC_CONTACT_EMAIL` missing →
   crash loop), what happens? Trace `set -eu` + `wait_for_url`'s non-zero
   return. Does the prod stack get redeployed, or is prod left untouched on its
   previous version? Is that the safe outcome?
5. `wait_for_url` retries 30×2s = 60s. The `up -d --build` completes the image
   build **before** `wait_for_url` runs — so the wait only covers container
   startup, not build time. Is 60s adequate for a FastAPI app to start? Any
   first-deploy edge case?
6. **Trade-off to weigh:** between PR #79 merging and PR 2/4 merging, prod does
   **not** yet depend on Rate Guard — yet PR #79 already blocks every prod
   deploy on Rate Guard health. Is that acceptable, or should the dependency be
   softer until PR 2/4? Give a recommendation, blocking or not.

### C. Idempotency & the shared instance
7. The PR claims `up -d --build` is idempotent — "the container is only
   recreated when `rate-guard/` actually changed." Is that accurate for
   `docker compose up -d --build`? What recreates the container, what doesn't?
8. Rate Guard is **one shared instance** for dev + prod. A prod deploy that
   *does* change `rate-guard/` will recreate the container, briefly dropping
   any dev in-flight requests. Acceptable? Note it.
9. The response cache is a bind mount (`./storage/rate_guard_cache`). The
   deploy checkout uses `clean: false`. Confirm the cache survives deploys.

### D. The runbook
10. Is `rate-guard/README.md` accurate? Specifically: the internal URL
    `http://rate-guard:9000` (service name + internal port), the host port
    `9099`, the required vs optional `.env` keys, and the `RATE_GUARD_URL`
    pre-merge instruction for PR 2/4.
11. Will the prod `api` container actually resolve `rate-guard` over
    `projects-shared`? Check `docker-compose.prod.yml` (is `api` on that
    network?) and `docker-compose.rateguard.yml` (service name / alias).

### E. Scope & cross-checks
12. Does PR #79 touch any application code? It should not. Confirm via the
    diff.
13. Does any dev compose file define its own Rate Guard service? The design
    forbids it (two limiters defeat the purpose). Confirm PR #79 did not
    introduce one and none exists.
14. `RATE_GUARD_URL` is **not** added to `backend/app/core/config.py` in this
    PR — deferred to PR 2/4 where it is first read. Is deferring it correct, or
    a gap?

### F. Tests / verification
15. This PR changes a shell script and a workflow — neither is covered by the
    canonical CI suite. Is `sh -n` + `docker compose config` + the runbook
    review an adequate verification bar for a deploy-pipeline change, or is
    something missing (e.g. a `shellcheck` pass, a dry-run)?

## Deliverable

Write the result to
`docs/tasks/2026-05-20_rate-guard-deploy-integration-review-result.md` with:

- **Verdict:** 批准 / approved, or 暂不批准 / not approved.
- Per-question findings (A1–F15), each PASS / FAIL / advisory.
- Any blocker stated concretely: file, line, what is wrong, how to fix.
- Non-blocking items recorded separately as follow-ups.

Apply the bar literally: a deploy-pipeline change is correct only if it fails
**safely** — a Rate Guard problem must never leave prod in a broken state.
