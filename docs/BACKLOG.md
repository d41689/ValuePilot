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

### Expired `refresh_tokens` rows are never purged
- **Found:** 2026-05-21, refresh-token revocation work
- **Severity:** low
- **Problem:** The `refresh_tokens` store gains one row per `/auth/refresh`
  (plus one per login). Nothing deletes rows whose `expires_at` has passed, so
  the table grows unbounded. Safe to defer — a row past `expires_at` is already
  rejected by the JWT `exp` check regardless, and the v0.1 user base is small —
  but a periodic purge (`DELETE FROM refresh_tokens WHERE expires_at < now()`,
  with a supporting index on `expires_at`) should land before broader rollout.
- **Context:** `docs/tasks/2026-05-21_refresh-token-revocation.md` (Scope → Out)
- **Issue:** —

### `refresh_tokens` FOR UPDATE concurrency path has no test
- **Found:** 2026-05-21, PR #86 review (both reviewers, advisory E14)
- **Severity:** low
- **Problem:** `rotate_refresh_token` (`backend/app/core/refresh_tokens.py`)
  serializes two concurrent refreshes of the same token with
  `SELECT ... FOR UPDATE`, so a self-race is caught as reuse instead of
  double-minting a successor. The branch is correct by inspection but has no
  automated test — a reliable one needs two real DB connections racing the same
  `jti` on separate threads, which the shared-session unit harness
  (`backend/tests/conftest.py`) cannot express. Add a multi-connection
  integration test before broader / multi-user rollout.
- **Context:** `docs/tasks/2026-05-21_refresh-token-revocation-review-result.md`
  and `..._review-results.md`, both item E14.
- **Issue:** —

### Interceptor-level tests for `frontend/lib/api/client.ts`
- **Found:** 2026-05-20, PR #64 (refresh-token flow)
- **Severity:** low
- **Problem:** The response interceptor's single-flight / retry / recursion
  behaviour has no unit test; only the pure helpers in `authSession.js` are
  covered.
- **Context:** `docs/tasks/2026-05-20_auth-hardening-followups.md` (item 2)
- **Issue:** —

### 13F CUSIP mappings flagged `needs_review` — human triage queue
- **Found:** 2026-05-21, after the OpenFIGI enrichment run (the original
  "link rate stuck at ~12%" item, PR #84, is resolved — see below)
- **Severity:** low
- **Problem:** The 2026-05-21 `enrich_cusip` run lifted the holdings link rate
  from 12.5% to 77.8% (12,443 / 15,995 linked). Of the residual: **2,160
  holdings are `needs_review`** — OpenFIGI returned an ambiguous result
  (multiple US-common-stock listings with conflicting tickers, or no
  US-common-stock listing), so `evaluate_openfigi_matches` flagged the mapping
  `review_needed:*` instead of auto-confirming. They need human triage via the
  existing admin CUSIP-mappings review surface
  (`GET /admin/13f/cusip-mappings/unresolved`). A further ~1,390 holdings are
  `unresolved` — OpenFIGI has no usable match (non-US, bonds, delisted, …), a
  genuinely hard tail. This is ongoing curation, not a code defect; the
  enrichment pipeline itself works and is re-runnable for future quarters.
- **Context:** `docs/tasks/2026-05-21_cusip-link-rate-diagnosis.md`
- **Issue:** —

### Manager `manager_type` first-pass classification needs human review
- **Found:** 2026-05-21 — supersedes the 2026-05-20 audit #9 "all `unknown`"
  item, which is now resolved (every manager is classified).
- **Severity:** low
- **Problem:** A Claude first-pass `manager_type` classification has been
  applied to all managers in prod — 86 at the time, now 82 after the
  duplicate-manager dedup (audited; `reviewed_by_user_id` NULL;
  every note prefixed `[auto-classified by Claude, first pass — pending human
  review]`; every `evidence_json` carries `classified_by: claude_first_pass`).
  The team should review and correct via the admin manager-type editor. Check
  the 10 scoring-relevant (off-1.00-weight) rows first — 6 `activist`,
  2 `multi_strategy`, 1 `quant`, 1 `high_turnover` — plus the ~8
  medium-confidence judgement calls. The most debatable single call is **TCI
  Fund Management (id 12)** — classified `value_concentrated` on its current
  stable concentrated book, but it has an activist heritage; if it runs a
  significant campaign it should move to `activist` (0.80 vs 1.00 — a real
  scoring difference). Find all first-pass rows:
  `institution_manager_type_review_events` rows with
  `reviewed_by_user_id IS NULL`.
- **Context:** `docs/tasks/2026-05-21_manager-type-classification.md`
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

### CSP `script-src` still allows `'unsafe-inline'`
- **Found:** 2026-05-21, CSP work (the original "no `Content-Security-Policy`
  header" item is resolved — a static CSP now ships, see below)
- **Severity:** low
- **Problem:** The CSP added in `frontend/lib/csp.js` is a *static* policy, so
  `script-src` keeps `'unsafe-inline'` — it does not block an injected inline
  script. Every other directive is locked down (`object-src 'none'`, `base-uri`,
  `form-action`, `frame-ancestors`, source-restricted
  `default`/`connect`/`img`/`font`/`style`), so this is the one remaining CSP
  gap. A genuinely strict `script-src` needs either a per-request nonce (Next.js
  then forces every page into dynamic rendering — see the task doc trade-off) or
  the experimental `experimental.sri` hash-based CSP once it is stable. Revisit
  before broader / multi-user rollout.
- **Context:** `docs/tasks/2026-05-21_content-security-policy.md`
- **Issue:** —
