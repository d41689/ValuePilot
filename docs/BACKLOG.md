# Backlog — deferred work

Problems discovered but not yet fixed. The capture rule is in
`AGENTS.md` → Workflow → "Deferred work". Each entry stays until the work is
actually done — remove it in the same PR that resolves it.

Severity: **high** = data-loss / security / production risk; should not sit here
long — escalate to the user. **medium / low** = ordinary follow-up.

## Open

### Rate Guard rollout is in-place, with no staged probe or rollback
- **Found:** 2026-05-20, PR #79 (Rate Guard deploy integration) review
- **Severity:** low
- **Problem:** `scripts/deploy_prod_from_main.sh` brings Rate Guard up with
  `docker compose up -d --build` — an in-place stop→start with no blue-green
  swap and no automatic rollback. If a deploy ships a broken `rate-guard/`
  change, the previously-healthy shared instance is already replaced before
  `/healthz` fails. PR #79 itself is safe (nothing depends on Rate Guard yet,
  and a failed healthcheck aborts before the prod stack), and in-place rebuild
  is the existing model for all services. But once PR 2/4 routes live EDGAR
  traffic through Rate Guard, a safer rollout (staged probe of the new image
  before swap, or keep-old-on-failure) is worth doing.
- **Context:** `docs/tasks/2026-05-20_rate-guard-deploy-integration-review-result2.md`
  (follow-up 2); address as part of Rate Guard PR 2/4.
- **Issue:** —

### Admin metrics panel is EDGAR-only — no OpenFIGI / Dataroma view
- **Found:** 2026-05-21, Rate Guard PR 4/4 (admin panel reads `/v1/metrics`)
- **Severity:** low
- **Problem:** Rate Guard now tracks per-upstream metrics for all three
  upstreams (EDGAR, OpenFIGI, Dataroma) at `GET /v1/metrics`, but the admin
  panel still shows only EDGAR (`build_edgar_rate_limit_status()` calls
  `metrics("edgar")`). OpenFIGI / Dataroma rate-limit budget, 403/429 counts,
  cache hit rate, and global-pause state are collected but not surfaced. A
  multi-upstream admin view (or three panels) would make the whole egress layer
  observable. Out of PR 4's scope, which the design scoped to the EDGAR panel.
- **Context:** `docs/tasks/2026-05-21_rate-guard-pr4-admin-metrics.md`
- **Issue:** —

### Refresh tokens have no revocation / reuse detection
- **Found:** 2026-05-20, PR #64 (refresh-token flow)
- **Severity:** medium
- **Problem:** Access and refresh tokens are stateless JWTs. A stolen refresh
  token is usable for up to 7 days unless the account is disabled — there is no
  reuse detection, no rotation blacklist, and no revocation list.
- **Context:** `docs/tasks/2026-05-20_auth-hardening-followups.md` (item 1)
- **Issue:** —

### Interceptor-level tests for `frontend/lib/api/client.ts`
- **Found:** 2026-05-20, PR #64 (refresh-token flow)
- **Severity:** low
- **Problem:** The response interceptor's single-flight / retry / recursion
  behaviour has no unit test; only the pure helpers in `authSession.js` are
  covered.
- **Context:** `docs/tasks/2026-05-20_auth-hardening-followups.md` (item 2)
- **Issue:** —

### 13F holdings CUSIP link rate stuck at ~12%
- **Found:** 2026-05-20, /admin/13f operational audit (item #7)
- **Severity:** medium
- **Problem:** Only ~12% of common-stock 13F holdings are linked to a `Stock`
  (2026-Q1: 504/4278; similar for other quarters). ~2,084 distinct CUSIPs are
  unresolved, including mega-caps (Alphabet, Visa, Amazon, BofA). The admin
  "Run CUSIP enrichment" job (`enrich_metadata`) only applies *existing*
  `CusipTickerMap` rows — it creates no new mappings — so re-running it cannot
  raise the rate. Resolving the gap needs the OpenFIGI-backed enrichment
  (`enrich_cusips_from_openfigi` / `enrich_unmapped_holdings`) run at scale to
  populate `CusipTickerMap`, then `bootstrap_stocks_from_cusip_map` +
  `backfill_stock_ids`. That is a data-completeness effort (OpenFIGI API key,
  rate limits, batching — `enrich_unmapped_holdings` does 100/run) with no
  single admin-UI trigger today.
- **Context:** `docs/tasks/2026-05-20_admin-13f-ops-audit.md` (item #7)
- **Issue:** —

### Manager `manager_type` classification (all `unknown`)
- **Found:** 2026-05-20, /admin/13f operational audit (item #9)
- **Severity:** medium
- **Problem:** All managers have `manager_type = unknown`. It is not cosmetic —
  it feeds Oracle's Lens scoring (`manager_taxonomy` / signal weighting). Each
  classification needs an authoritative type plus a mandatory justification
  note (audited in `institution_manager_type_review_events`); the system has an
  "unknown-manager priority queue" workflow for it. This is ongoing human
  curation for the team, not a bulk edit.
- **Context:** `docs/tasks/2026-05-20_admin-13f-ops-audit.md` (item #9)
- **Issue:** —

### Extended historical backfill
- **Found:** 2026-05-20, /admin/13f operational audit (item #11)
- **Severity:** low
- **Problem:** The Overview surfaces an "Extended backfill recommended" P3
  task — run a historical backfill to deepen quarter coverage. Optional
  maintenance; skipped during the audit. Run via Manual Controls → Backfill
  when the EDGAR rate-limit budget allows.
- **Context:** `docs/tasks/2026-05-20_admin-13f-ops-audit.md` (item #11)
- **Issue:** —

### Content-Security-Policy response header
- **Found:** 2026-05-20, admin/13f security-header review
- **Severity:** medium
- **Problem:** `next.config.js` now sets HSTS, X-Frame-Options, nosniff,
  Referrer-Policy, and Permissions-Policy, but no `Content-Security-Policy`. A
  correct CSP for the Next.js runtime (inline scripts / nonces / allowed
  origins) must be built and tested against the running app — a wrong policy
  breaks the site, so it cannot be added blind.
- **Context:** `docs/tasks/2026-05-20_admin-13f-page-fixes.md`
- **Issue:** —
