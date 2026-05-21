# Review result (independent second review) — Rate Guard prod deploy integration, PR #79

Date: 2026-05-20
Branch reviewed: `claude/rate-guard-deploy-integration`
Prompt: `docs/tasks/2026-05-20_rate-guard-deploy-integration-review-prompts.md`
Reviewer: independent re-review (Claude Code)

## Relationship to the existing `…-review-result.md`

A prior review (`2026-05-20_rate-guard-deploy-integration-review-result.md`)
returned **暂不批准 / not approved** with three "blocking findings". This is a
separate, independent review. It agrees with every **factual** observation in
that review, but **disagrees on severity**: none of the three rise to a blocker
for PR #79. Verdict here is **批准 / approved**, with the three items recorded as
non-blocking advisories. The reasoning is given per-item below — read the
"Divergence" section before acting on either review.

## Verdict

**批准 / Approved.**

PR #79 does exactly its scoped job: the prod deploy now brings Rate Guard up and
health-checks it **before** the prod stack, and a Rate Guard failure aborts the
deploy **before** the prod application stack is touched — so the prod app keeps
running its previous version. The deploy script is syntactically clean, the
compose files validate, the runbook is accurate, and no application code is
touched. There are no blocking defects.

Three advisories (below) are worth addressing — one is a trivial wording fix
that ideally lands in this PR — but none blocks the merge.

## Divergence from the first review — why the three "blockers" are not blockers

**Prior blockers 1 & 2 — the idempotency wording** (`deploy_prod_from_main.sh:50-51`,
`rate-guard/README.md:25-26`). The observation is correct: "`up -d --build`
recreates the container only when `rate-guard/` changed" is an oversimplification
— a change to `docker-compose.rateguard.yml` or to relevant `.env` values also
recreates it. But this is an **explanatory comment / doc sentence**; the script's
*behaviour* is correct regardless of how precisely the comment is worded. A
slightly-imprecise comment is a real nit, not a deploy blocker. → Advisory (1).

**Prior blocker 3 — Rate Guard recreate is not blue-green.** Correct that
`docker compose up -d --build` recreates in place (stop old → start new, no
auto-rollback), so a Rate Guard release that ships a broken image replaces the
healthy one. But this does **not** block PR #79:

- **It does not violate PR #79's bar.** The prompt's bar is "a Rate Guard
  failure fails the deploy safely — *prod keeps running its previous version*",
  and B4 traces `set -eu` + `wait_for_url` for exactly the **prod stack**. PR #79
  meets that: a Rate Guard failure aborts at `deploy_prod_from_main.sh:54`,
  before the prod `up` at line 57 — the prod app stack is never touched.
- **PR #79 introduces no prod risk.** At PR #79 **nothing depends on Rate
  Guard** (PR 2/4 is what repoints `EdgarClient`). A failed Rate Guard recreate
  at this stage has *zero* prod impact.
- **Post-2/4 it is a design-accepted degraded state.** `docs/tasks/2026-05-20_rate-guard-design.md`
  §11 explicitly classifies "Rate Guard down → external access stops" as a
  *safe degraded state — far better than an IP ban*. A down Rate Guard is not
  "prod in a broken state" by the design's own definition.
- **It is not a PR #79 regression.** In-place recreate with no rollback is the
  repo's existing deploy model for *every* service — the prod `api` and `web`
  are recreated the same way. PR #79 did not introduce it.
- The first review itself lists the fix for this (a staged probe / rollback) in
  its **non-blocking follow-ups** — so treating the same item as a blocker is
  internally inconsistent.

A safer Rate Guard rollout is genuinely worth doing — but as a follow-up scoped
to **PR 2/4**, when Rate Guard actually becomes load-bearing. → Advisory (2).

## Per-question findings

### A. Ordering & correctness

- **A1 — PASS.** `deploy_prod_from_main.sh` defines `wait_for_url` at lines
  29-45, before its first use (Rate Guard, line 54) and the prod-stack uses
  (lines 63-64). Rate Guard `up` (line 53) + `/healthz` wait (line 54) run
  before the prod stack `up` (line 57). `sh -n` passes.
- **A2 — PASS.** `projects-shared` is inspected/created at lines 20-22, before
  the Rate Guard `up` at line 53. Required, since `docker-compose.rateguard.yml:30-33`
  declares the network `external`.
- **A3 — PASS.** Health URL `http://127.0.0.1:${RATE_GUARD_HOST_PORT:-9099}/healthz`
  (lines 52-54) matches the compose port map `${RATE_GUARD_HOST_PORT:-9099}:9000`
  (`docker-compose.rateguard.yml:21-24`) and the `GET /healthz` route
  (`rate-guard/app/main.py:35-37`).

### B. Failure modes & safety

- **B4 — PASS.** With `set -eu`, a failed `wait_for_url` (line 54) returns
  non-zero; as a bare command it triggers `set -e` and the script exits **before**
  `docker compose -f docker-compose.prod.yml up -d --build` (line 57). The prod
  app stack is never redeployed and keeps its previous version — the bar's
  definition of "safe". (The separate observation that a broken Rate Guard
  *release* is not auto-rolled-back is real but non-blocking — see Divergence,
  Advisory 2.)
- **B5 — PASS / advisory.** `wait_for_url` is 30 × 2s = 60s and covers only
  container startup — `up -d --build` finishes the image build before the wait.
  60s is ample for this tiny FastAPI app (it does no I/O at import; `/healthz`
  is served as soon as uvicorn binds). First-deploy build time is excluded from
  the wait, so there is no first-deploy edge case.
- **B6 — advisory / acceptable.** PR #79 blocks every prod deploy on Rate Guard
  health even though prod does not depend on Rate Guard until PR 2/4. This is
  acceptable and recommended **as-is**: the coupling window is short and
  intentional, the failure is safe (deploy aborts, prod untouched), and it acts
  as a useful canary — a broken Rate Guard is discovered at PR #79's deploy
  rather than at PR 2/4's hard-failing api. The script comment (lines 47-49)
  documents the rationale.

### C. Idempotency & the shared instance

- **C7 — advisory (not a blocker).** `up -d --build` is idempotent in the
  practical sense the comment intends: an unrelated deploy (nothing under
  `rate-guard/` changed) produces a cache-hit build → identical image ID → no
  recreate. The wording is imprecise only in omitting that a
  `docker-compose.rateguard.yml` change or a relevant `.env` change also
  recreates the container. Behaviour is correct; tighten the wording — Advisory (1).
- **C8 — advisory.** One shared instance means a deploy that *does* change
  `rate-guard/` recreates the container, briefly (~1-2s) dropping any in-flight
  request. This is inherent to the one-limiter design and the affected callers
  retry; nothing calls Rate Guard until PR 2/4. Worth a one-line note in the
  runbook.
- **C9 — PASS.** The cache is the bind mount `./storage/rate_guard_cache:/data/cache`
  (`docker-compose.rateguard.yml:25-26`); a container recreate does not touch
  host bind-mount dirs. The deploy checkout uses `clean: false`
  (`.github/workflows/deploy.yml:40-41`, with a comment explaining it preserves
  `storage/` bind-mount sources), so the cache survives across deploys.

### D. The runbook

- **D10 — PASS / advisory.** `rate-guard/README.md` is accurate: internal URL
  `http://rate-guard:9000` (service name + container port), host port `9099`,
  `SEC_CONTACT_EMAIL` required (Rate Guard fails loud without it — verified in
  the PR #76 review), `OPENFIGI_API_KEY` / `RATE_GUARD_HOST_PORT` / RPS overrides
  optional, and the `RATE_GUARD_URL=http://rate-guard:9000` pre-merge step for
  PR 2/4. "The deploy workflow copies it to `./.env`" matches
  `.github/workflows/deploy.yml:43-48`. The only blemish is the same imprecise
  idempotency sentence (lines 25-26) — Advisory (1). Minor: "`docs/architecture/`
  is the long-form home" — no Rate Guard doc exists under `docs/architecture/`
  yet; cosmetic.
- **D11 — PASS.** Prod `api` joins `shared-infra` → external `projects-shared`
  (`docker-compose.prod.yml:62-69`); the Rate Guard service is named `rate-guard`
  on the same network (`docker-compose.rateguard.yml:10-11,27-33`). Docker
  embedded DNS resolves `rate-guard` across the two compose projects on the
  shared network. (Prod `web` is on `default` only — correct, it does not need
  Rate Guard.)

### E. Scope & cross-checks

- **E12 — PASS.** `git diff main...HEAD` touches only
  `.github/workflows/deploy.yml`, `scripts/deploy_prod_from_main.sh`,
  `rate-guard/README.md`, and two `docs/tasks/` files. No application code.
- **E13 — PASS.** `grep` across all three compose files: only
  `docker-compose.rateguard.yml` defines a `rate-guard` service. The dev
  `docker-compose.yml` does not — the design's "no second limiter" rule holds.
- **E14 — PASS.** Deferring `RATE_GUARD_URL` out of `backend/app/core/config.py`
  is correct — it is first read in PR 2/4; adding it now would be dead config.
  The task doc scopes it out explicitly. (An operator adding `RATE_GUARD_URL` to
  `.env` early per the runbook is harmless: `Settings` uses `extra="ignore"`.)

### F. Tests / verification

- **F15 — PASS / advisory.** `sh -n` + `docker compose config` is the adequate
  minimum for this change, and the script is short and well-quoted. I additionally
  ran `shellcheck` (the first review could not): it flags only **pre-existing**
  lines outside the PR #79 diff — `SC1007` ×2 on lines 5-6, a known
  false-positive for the deliberate `CDPATH= cd …` command-prefix idiom, and
  `SC1091` ×2 (info) for un-followable sourced `.env` files. **Nothing in the
  PR #79 changes.** Adding `shellcheck` to CI would be a reasonable future gate
  but would need `# shellcheck disable=SC1007` on lines 5-6 to avoid noise.

## Verification performed

- `sh -n scripts/deploy_prod_from_main.sh` — pass.
- `docker compose -f docker-compose.rateguard.yml config -q` — valid.
- `docker compose -f docker-compose.prod.yml config -q` — valid.
- `shellcheck scripts/deploy_prod_from_main.sh` (via `koalaman/shellcheck:stable`)
  — only pre-existing `SC1007` (false-positive) + `SC1091` (info); clean within
  the PR #79 diff.
- `git diff main...HEAD` — confirms scope (deploy script, deploy workflow,
  runbook, two docs; no application code).
- A true end-to-end deploy (Rate Guard up + healthz + prod stack) was not run —
  it requires the prod host's `.env` files and the live `projects-shared`
  network and self-hosted runner; correctly disclosed in the task doc.

## Recommended follow-ups (none blocking)

1. **Tighten the idempotency wording** in `scripts/deploy_prod_from_main.sh:50-51`
   and `rate-guard/README.md:25-26` — e.g. "`up -d --build` is repeatable; the
   container is recreated when its image (`rate-guard/`), the compose file, or
   its env changes — an unrelated deploy leaves it untouched." Trivial; ideally
   in this PR.
2. **Safer Rate Guard rollout — scope to PR 2/4.** Before Rate Guard becomes
   load-bearing, add a staged health probe / rollback so a broken Rate Guard
   *release* cannot replace a healthy shared instance with no recovery.
3. Add a one-line note (runbook) that a Rate Guard recreate briefly interrupts
   in-flight requests because dev + prod share one instance.
4. Optional: add a `shellcheck` step for `scripts/*.sh`, with `SC1007` disabled
   on the `CDPATH= cd` lines.

## Bottom line

PR #79 correctly and safely wires Rate Guard into the prod deploy pipeline ahead
of PR 2/4. The first review's three findings are factually accurate but, applied
against PR #79's stated bar and scope, are advisories rather than blockers — see
the Divergence section. **Approved**, with the wording fix (follow-up 1)
recommended for this PR and the safer-rollout work (follow-up 2) tracked for
PR 2/4.
