# Backlog — deferred work

Problems discovered but not yet fixed. The capture rule is in
`AGENTS.md` → Workflow → "Deferred work". Each entry stays until the work is
actually done — remove it in the same PR that resolves it.

Severity: **high** = data-loss / security / production risk; should not sit here
long — escalate to the user. **medium / low** = ordinary follow-up.

## Open

### Authority rule 2 ranks admin-`applied` amendments by the accession_no fallback that rules 1 and 3 removed
- **Found:** 2026-07-09, PR #113 self-review (the external review skipped this
  prompt question)
- **Severity:** low (latent — **0 reachable groups on the 355-group real dataset**;
  see reachability below)
- **Problem:** `apply_active_filing_policy` rule 2 picks the owner with
  `max(pool, key=_active_filing_rank)`, and `_active_filing_rank` falls back to
  `(datetime.min, accession_no)` when `accepted_at` is NULL. Rules 1 and 3 guard
  that exact situation (`missing_acceptance`: ≥2 candidates + any NULL → do not
  auto-switch, flag for a human) precisely because the series established that an
  accession prefix identifies the SUBMITTING agent, not the manager, and is not a
  time proxy (231/373 real filings differ from their manager's CIK; 3 real
  lexical-vs-acceptance inversions). Rule 2 has neither a missing-evidence guard
  nor a tie guard, and the accepted_at deploy gate deliberately skips
  `amendment_owned` groups — so on a pre-gate database an operator who applied two
  amendments to one (manager, period) gets an owner chosen by accession string,
  with no warning.
- **Reachability (measured, not assumed):** rule 2 fires only when NO parsed
  non-rejected/-deferred HR-family RESTATEMENT exists (those go to rule 1, which
  IS guarded). Over the 355 real (manager, quarter_end_date) groups the pool kinds
  are `originals 343 / restatement 11 / none 1`, and groups reaching rule 2 with
  ≥2 `applied` amendments: **0**. The two real groups holding ≥2 `applied`
  amendments hold RESTATEMENTs, so they route to rule 1.
- **Fix sketch:** give rule 2 the same guard as rules 1/3 — if ≥2 applied
  amendments and (any NULL `accepted_at` OR a top-two tie), do not auto-switch:
  keep the current active filing if it is in the pool, demote any active row that
  is NOT (a rejected amendment or stale original must never serve), flag the pool,
  and return `missing_acceptance`. Then stop skipping `amendment_owned` in
  `_at_risk_groups`. Consider whether admin intent should be ordered by an
  explicit `resolved_at` rather than by SEC acceptance time at all.
- **Context:** `docs/tasks/2026-07-09_13f-release-readiness-review-results.md`
  (Prompt 2, question 3 — unanswered by the review)

### No end-to-end quarterly-pipeline test with real stage bodies
- **Found:** 2026-07-09, T1–T4 series review (test-gap recommendation #1)
- **Severity:** low (every stage body is unit/composition tested individually;
  the untested surface is the full stage CHAIN — ingest/routing → authority
  sweep → quality_check → compute_ownership_changes → Lens scoring — on a
  multi-manager/multi-quarter fixture; existing pipeline tests stub stage bodies)
- **Fix sketch:** one integration test driving `quarterly_pipeline` with real
  stage bodies over stored primary/infotable docs for ≥2 managers × 2 quarters
  (reuse the T1-FU composition-test harness), asserting changes rows + Lens
  signals + quality report exist and agree.
- **Context:** `2026-07-09_13f-t1-t4-series-review-results.md` missing test #1
  (#2 and #3 landed with the series-review fixes)

### No source guard for direct `Holding13F` product queries
- **Found:** 2026-07-09, T1–T4 series review (guard recommendation)
- **Severity:** low (review found no current violation; the guard prevents a
  future user/API surface from bypassing `active_hr_holdings_query` — the PRD
  §7.3 contract T4/F6 was about)
- **Fix sketch:** T4-style source guard scanning user/API-facing services for
  `query(Holding13F` with a whitelist for sanctioned low-level modules
  (`thirteenf_holdings_query`, ownership-changes/scoring internals, admin
  diagnostics).
- **Context:** `2026-07-09_13f-t1-t4-series-review-results.md` "Useful third guard"

### `13F-NT/A` has no first-class automated ingestion
- **Found:** 2026-07-09, T1-FU external review (P2, latent); narrowed
  2026-07-09 by the series review (the original entry's "consumers only
  recognize exact 13F-NT" half is RESOLVED — `NT_FORM_TYPES` is now used by
  `nt_only_manager_ids`, `thirteenf_user_api` (holdings/quarter/caveats),
  `oracles_lens/base_primitives._is_nt_quarter`, `thirteenf_ownership_changes`,
  and `thirteenf_filing_detail` report-type/coverage normalization; the
  authority guards a parsed NT/A RESTATEMENT from ever competing for the HR
  holdings slot).
- **Severity:** low (latent — `INGESTION_FORMS` and the form.idx whitelist
  exclude `13F-NT/A`, so none enter the data layer automatically; SEC defines
  it as the amendment form for a 13F Notice and raw form indexes contain many)
- **Remaining problem:** ONLY the ingestion scope — `13F-NT/A` filings are not
  ingested automatically (`INGESTION_FORMS`, `_DAILY_13F_FORM_TYPES`), and
  NT-slot activation semantics (an NT/A superseding an NT for the notice slot)
  are undefined in the authority. Rows that arrive via `ingest_accession` /
  admin apply are already handled consistently by every consumer.
- **Fix sketch:** add `13F-NT/A` to the ingestion whitelists + define NT-slot
  succession in `apply_active_filing_policy`, or formally document NT/A
  ingestion as out of scope in the PRD.
- **Context:** `docs/tasks/2026-07-08_13f-t1fu-active-filing-authority.md` 评审处置
  P2-9 / 三审处置;series review `2026-07-09_13f-t1-t4-series-review-results.md`

### ~~CLI `reparse-filing` / `reparse-all` write product-invisible legacy holdings~~ (F7 — RESOLVED T4 rework)
- **Found:** 2026-07-08, T4 external review (correctness finder)
- **Severity:** medium (product-visibility / footgun — no audit-trail loss)
- **Resolved:** 2026-07-08, T4 rework (second review escalated F7 to a merge
  blocker: the commands are advertised in `README.md` and destructive). Both
  `reparse_filing` and `reparse_all` (`backend/app/cli/edgar.py`) now delegate to
  the ParseRun-backed `reparse_accession` job via the locked runner
  (`run_locked_job`). `reparse_accession` swaps `is_current` and RETAINS the
  prior run's holdings — non-destructive. Verified on real dev data: reparsing
  `0001325447-26-000009` created a new current parse_run (602 rows) and retained
  the old run's 602, with 0 NULL-parse_run rows globally. (That accession is the
  *inactive* original — superseded by restatement `0001325447-26-000018` — so
  `active_hr_holdings_query` correctly returns 0 for it and 602 for the active
  restatement; ParseRun currency alone is not product visibility.) Regression:
  `test_13f_cli_ingest.py` — source guard + CliRunner wiring + a real
  `run_locked_job('reparse_accession')` integration test asserting
  `active_hr_holdings_query` visibility on an active filing (and 0 on an inactive
  one), plus a runtime `reparse-all` partial-failure non-zero-exit test. README
  copy updated.

### `backfill` retries by missing-infotable, not by failed-parse (recoverability edge)
- **Found:** 2026-07-08, T4 external review (correctness finder)
- **Severity:** low (narrow; job/admin-retry path is the intended recovery)
- **Problem:** T4's `backfill` decides which quarters to (re)ingest via
  `pending_ingest_quarters`, whose "pending" test is `raw_infotable_doc_id IS
  NULL`. In the ingest job, Phase 1 fetches + commits the infotable doc BEFORE
  Phase 3 parses holdings; a filing whose infotable is fetched but whose holdings
  then fail to parse ends up with `raw_infotable_doc_id` set and no current
  ParseRun — so it drops out of `pending_ingest_quarters`. If it is the LAST
  pending filing in its quarter, `backfill` won't re-invoke the job for that
  quarter and the failed-parse filing is not retried by backfill. (The job
  reprocesses ALL filings in an invoked quarter, so the gap only bites when no
  other pending filing keeps the quarter in scope; the admin retry surface /
  `reparse_accession` is the intended recovery either way.)
- **Fix sketch:** define "needs ingest" as "no current, product-visible ParseRun"
  (or `raw_infotable_doc_id IS NULL OR parse_status = 'failed'`) rather than
  missing-infotable alone; bound to the same `--quarters` scope T4 already applies.
- **Context:** `docs/tasks/2026-07-08_13f-t4-cli-ingest-hygiene.md`

### ~~Active-filing selection is scattered; accepted_at unpopulated; restatement ties + concurrency unhandled~~ (RESOLVED T1-FU)
- **Found:** 2026-07-08, T1 external review (`2026-07-08_13f-t1-restatement-activation-fix-review-results.md`)
- **Severity:** medium (correctness/robustness; no active data loss — T1 made the
  winner deterministic and crash-free)
- **Resolved:** 2026-07-08, T1-FU (`docs/tasks/2026-07-08_13f-t1fu-active-filing-authority.md`).
  One authority `apply_active_filing_policy` (thirteenf_filing_detail) now makes
  every activation decision — `apply_amendment_policy`,
  `reconcile_restatement_activation` (thin delegate), and the ingest job's
  per-group sweep (replacing the Phase-4c solo-HR heuristic + Phase-5 loop) all
  call it under a `pg_advisory_xact_lock` keyed on (manager_id,
  quarter_end_date). `accepted_at` is populated on the bulk path
  (`apply_primary_doc_metadata` + `backfill_period_routing`; 373/373 real
  filings backfilled, 0 NULL). Ties = equal AND non-NULL accepted_at
  (NULL→accession_no fallback preserves T1); restatement ties don't auto-switch
  (warning + amendments_pending). Also fixed in passing: rejected restatements
  can no longer be re-activated by a pipeline re-run; an NT can no longer beat
  an HR for the active slot; the tie-recovery dead code. Real-data sweep over
  355 groups: 0 flips, 0 dup-active. Tests: `test_13f_active_filing_authority.py`
  (15, incl. a two-session lock-serialization test).

### ownership_changes has no first-class "position" layer — per-lot rows fragment a stock held under multiple CUSIPs
- **Found:** 2026-07-08, T2 external review (design verdict)
- **Severity:** low (cleanliness / consumer ergonomics; no crash, no data loss —
  shares are all accounted for, just split across rows)
- **Problem:** the normal `_compute_rows` path keys change rows per-CUSIP (via
  the PRD §7.4 fallback). A stock held under two CUSIPs that both persist across
  quarters yields two change rows for one stock_id (one keyed `stock:<id>`, one
  keyed `cusip:<other>`), and merged provenance fields (current_holding_id,
  current_cusip) reference one lot. T2 aggregates only the unavailable branch
  (where rows collide on the unique key); it deliberately does NOT aggregate the
  matched path (pre-aggregating breaks cross-quarter CUSIP-fallback — see the
  T2 review's [P1] #1). Fine for now, but consumers that treat one change row as
  "the position" see fragments.
- **Fix sketch:** a first-class positions read-model derived from raw holdings
  (sum shares/value per (stock, ssh_prnamt_type, position_type), honest lot
  provenance), consumed by the changes/holders APIs — instead of duck-typing
  `Holding13F` at compute time. Also covers put/call aggregation separation and
  representative-CUSIP semantics. Raw infotable rows stay the audit trail.
- **Context:** `docs/tasks/2026-07-08_13f-t2-ownership-changes-orchestration-review-results.md` (Design Verdict)

### Cross-filer double-count review guard for combination attribution (deferred)
- **Found:** 2026-07-08, T3 (combination attribution) — deferred from the PO ruling
- **Severity:** low (not currently triggerable)
- **Problem:** T3 attributes DFND/OTR holdings to the filer (`direct`). If a
  combination filer AND one of its included sub-managers were BOTH tracked as
  separate universe managers that each report the same position, consensus/
  holder counts could double-count. Not possible in the current 82-manager
  universe (sub-managers are not tracked separately), so no guard was built.
- **Fix sketch:** when adding managers, or in a periodic quality check, flag any
  two universe managers reporting the same (stock, quarter) via a combination
  linkage for human review rather than silently double-counting.
- **Context:** `docs/tasks/2026-07-08_13f-t3-combination-attribution.md` (Scope: Out)

### ~~CLI ingest commands write product-invisible legacy holdings (no ParseRun)~~ (F6 — RESOLVED T4)
- **Found:** 2026-07-08, during first real-data ingestion into dev
- **Severity:** medium
- **Resolved:** 2026-07-08, T4 (`docs/tasks/2026-07-08_13f-t4-cli-ingest-hygiene.md`).
  `backfill` / `ingest-holdings` in `backend/app/cli/edgar.py` no longer call the
  legacy `ingest_filing_holdings`; they delegate to the modern `ingest_holdings`
  job (`execute_job_payload` → `_execute_ingest_job` → `ingest_if_needed`), so CLI
  ingest is ParseRun-backed and product-visible, with the Phase-4 heal + solo-HR
  activation the legacy path lacked. Regression: `test_13f_cli_ingest.py`
  (`test_ingest_pending_holdings_delegates_to_job_per_quarter`).

### ~~CLI `backfill` skips the newest report quarter's holdings (period-proxy window miss)~~ (F5 — RESOLVED T4)
- **Found:** 2026-07-08, during first real-data ingestion into dev
- **Severity:** medium
- **Resolved:** 2026-07-08, T4. `backfill` Step 2 now selects pending filings via
  `pending_ingest_quarters` (grouping by each un-ingested filing's *proxy*
  `period_of_report` = `filed_at`, i.e. the filing quarter) and delegates each
  quarter to the ingest job — so the newest report quarter's filings, filed the
  following calendar quarter, land in the right job window instead of being
  silently skipped. Regression: `test_13f_cli_ingest.py`
  (`test_pending_ingest_quarters_covers_newest_report_quarter`).

### Rate Guard public path has no auth-failure / abuse observability
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** medium
- **Problem:** No metric or alert exists for 401s or for public traffic hitting
  `rate-guard.richmom.vip`. A leaked key or brute-force spray would first surface
  as our egress IP getting banned by SEC/OpenFIGI. `/v1/metrics` tracks upstream
  volume only; the auth middleware emits no 401 signal and no source-IP visibility.
- **Fix sketch:** (1) a counter on 401s in the auth middleware + alert on 401-rate
  spikes; (2) a Cloudflare WAF rate-limit rule on `rate-guard.richmom.vip` +
  source-IP via CF logs (CF sees the real client IP before the tunnel); (3) alert
  on anomalous `/v1/fetch` volume.
- **Context:** `docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md` (#9);
  see also `docs/architecture/rate-guard-public-exposure.md` → Deferred hardening

### Rate Guard shared key — split dev/prod values; consider edge auth
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** low
- **Problem:** One static `RATE_GUARD_API_KEY` value is shared across dev, prod,
  and the remote dev box. The two-slot mechanism (`RATE_GUARD_API_KEY` +
  `RATE_GUARD_API_KEY_PREVIOUS`) now supports distinct/rotating keys, but distinct
  values are not yet provisioned. A leak grants full egress-proxy access under our
  IP/User-Agent, and the same key also gates dev.
- **Fix sketch:** (1) give the remote box its own key (second slot), revocable on
  its own; (2) as a future option, move auth to Cloudflare Access service tokens /
  mTLS for per-client identity + revocation, keeping the app bearer as
  defense-in-depth (Option B keeps the app bearer for now).
- **Context:** `docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md` (#4)

### `_clear_13f` test helper raises FK violation when dev DB has committed quality_findings_13f / oracles_lens_signals rows
- **Found:** 2026-05-24, while running canonical CI for the manager-taxonomy-v2 change
  (`docs/tasks/2026-05-24_manager-taxonomy-v2.md`)
- **Severity:** medium (dev-only — CI passes because CI starts from an empty volume)
- **Problem:** `backend/tests/unit/test_13f_user_api.py::_clear_13f` deletes
  `OraclesLensScoreComponent` / `OraclesLensSignal` / `OwnershipChange13F` /
  `Holding13F` / `ParseRun13F` / `Filing13F` / `InstitutionManagerCikReviewEvent`
  / `InstitutionManager` in that order, but the dev DB also accumulates
  `quality_findings_13f` (FK → `institution_managers.id`) and several other
  tables with FK references to managers. When the dev DB has those committed
  rows from prior bootstrap / ingestion runs, every test that calls
  `_clear_13f` and a few sibling helpers fails with
  `psycopg2.errors.ForeignKeyViolation`. Confirmed pre-existing: reproduces
  on `main` with all taxonomy-v2 changes stashed. Verified non-regressing
  by my own work — fresh-DB CI passes, and isolating the new
  `test_13f_manager_taxonomy_v2.py` (23 cases) and existing
  `test_13f_mvp4_manager_taxonomy.py` / `test_13f_mvp5_05_manager_type_editor.py`
  / `test_13f_mvp5_01_wire_behavior_manager_type.py` (28 cases) all pass.
- **Fix sketch:** Either (a) expand `_clear_13f` to also delete `quality_findings_13f`
  and `quality_reports_13f` (and any other FK-bearing tables) before
  `institution_managers`; or better (b) switch the conftest to a real
  test-DB fixture (e.g. a transient `valuepilot_test` schema) so dev data
  never bleeds into test runs. Option (b) is the AGENTS.md-aligned long-term
  fix — it's the same class of "long-lived branches mask failures" issue
  the workflow already warns about.
- **Context:** PR for manager-taxonomy-v2 change

### 13F CUSIP enrichment — monitor MUTUAL FUND / OPEN-END FUND / UNIT auto-confirms in production
- **Found:** 2026-05-22, PR #93 review (advisory #1)
- **Severity:** low
- **Problem:** The new `_EQUITY_LIKE_SECURITY_TYPES` allowlist in
  `backend/app/services/cusip_enrichment.py` includes `MUTUAL FUND`,
  `OPEN-END FUND`, `CLOSED-END FUND`, and `UNIT`. These are the most permissive
  entries on the list — a 13F filer's common-holding row (`put_call IS NULL`)
  legitimately resolves to a mutual-fund / closed-end-fund ticker in some
  cases, but a `UNIT` could also be a SPAC pre-business-combination unit
  bundling common + warrants. Once production accumulates a few quarters of
  data, scan `cusip_ticker_map.confidence='high'` rows where the matched
  securityType is one of these four, eyeball the auto-confirmed tickers
  against the issuer name, and tighten or split the allowlist if any tier
  shows mis-routes.
- **Context:** [docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md](docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md);
  [docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins-review-results.md](docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins-review-results.md)
- **Issue:** —

### 13F `_check_period_alignment` quality subcheck still uses filing-quarter
- **Found:** 2026-05-22, PR #90 review round 1 (P2)
- **Severity:** low
- **Problem:** Every other check in `run_quality_checks()` scopes by
  `period_of_report` (report quarter) via `_quarter_filter()`, but
  `_check_period_alignment()` (`backend/app/services/edgar_quality.py`) still
  interprets its `quarter` arg as a *filing* quarter — it filters
  `filed_at BETWEEN :f_start AND :f_end` and expects `period_of_report` in
  `quarter-1`. After the F1/F2 report-quarter fix, `quality_check` receives a
  report quarter, so this subcheck inspects the wrong filing set (the filings
  *filed in* that quarter, which report on the prior quarter) and can miss
  period anomalies for the requested report quarter. Non-blocking — it only
  emits info/warning lines. Fix needs a rethink of what the check should assert
  under the report-quarter model (likely: verify each filing's `report_quarter`
  matches its actual `period_of_report`).
- **Context:** `docs/tasks/2026-05-21_13f-web-validation.md` (Review round 1, R-P2)
- **Issue:** —

### 13F test suite is not isolated from dev-database data
- **Found:** 2026-05-22, 13F web-validation run
- **Severity:** low
- **Problem:** The pytest suite runs against the dev `valuepilot` database and
  assumes it starts empty (`conftest.py`: "assuming fresh DB from
  docker-compose"). `test_13f_admin_dashboard.py` bulk-deletes `job_runs` in a
  fixture; when a normal app/web run has left `job_runs` rows that
  `quality_reports_13f.source_job_id` (and other tables) reference, that delete
  raises `ForeignKeyViolation` and ~50 tests fail — even though the code is
  correct (verified: 907 pass on a fresh `valuepilot_test` DB). Real CI runs on
  a fresh DB so CI is unaffected, but local `pytest` is fragile after any web
  use of the dev stack. Fix: point the suite at a dedicated, migrated test
  database, or make the fixtures delete dependents first / rely solely on the
  transactional rollback.
- **Context:** `docs/tasks/2026-05-21_13f-web-validation.md` (F5)
- **Issue:** —

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

### Value Line parser: full OCR integration for scanned archives
- **Found:** 2026-07-02, Value Line parser historical-readiness review (for
  quant Phase 1 / 1-R0 archive ingestion)
- **Severity:** high — historical Value Line archives are largely scans; until
  OCR lands they cannot be ingested at all. Pages are now honestly reported as
  `requires_ocr` (F7) instead of silently skipped, but nothing OCRs them.
- **Problem:** `PdfExtractor` is native-text-only. The `requires_ocr` /
  `text_extraction_method="ocr"` enums existed unused; F7 wired the detection
  but real OCR (tesseract in the api image + an OCR extraction path) is not
  implemented.
- **Fix sketch:** add tesseract to the api Docker image; OCR pages flagged
  `requires_ocr`; set `text_extraction_method="ocr"`; validate against real
  scanned samples per decade acquired in 1-R0. Do not build before samples
  exist.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —

### Value Line parser: x0-coordinate column alignment for annual tables
- **Found:** 2026-07-02, parser historical-readiness review (P1-5)
- **Severity:** high — count-based year↔value alignment (`_align_years` +
  drop-leading-outlier heuristics) can silently assign values to wrong years;
  for backtests this is the most toxic error class (no error, plausible value,
  wrong year).
- **Problem:** `_parse_time_series_tables` aligns rows to the year header by
  token count, not by word x0 coordinates, although `page_words` layout data
  is already extracted. The ADS/insurance "drop leading outlier" patches are
  symptoms of this design.
- **Fix sketch:** rewrite table row extraction to bucket value tokens by the
  year-header column x-ranges. Requires per-era historical fixtures (1-R0) as
  the safety net before refactoring — current heuristics pass all 55 modern
  fixtures.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —

### Value Line parser: verify fiscal column-year labeling convention
- **Found:** 2026-07-02, parser historical-readiness review (P1-8)
- **Severity:** medium
- **Problem:** the parser assumes the annual-table column year equals the
  calendar year the fiscal year ends in (`date(year, fye_month, last_day)`).
  For companies whose FY ends early in the calendar year (e.g. January FYE),
  Value Line's column-labeling convention may be off by one vs this
  assumption. Also `fiscal_year_end_month` is inferred solely from the
  quarterly table month order and silently falls back to December.
- **Fix sketch:** verify against real non-calendar-FYE samples (ADBE Nov,
  AAPL Sep, Jan-FYE retailers) across eras; add fixtures pinning the
  convention.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —

### Value Line page JSON: era-hardcoded key names
- **Found:** 2026-07-02, parser historical-readiness review (P2-13)
- **Severity:** low
- **Problem:** page JSON keys are hardcoded to the 2026-era layout
  (`annual_financials_and_ratios_2015_2026_with_projection_2028_2030`,
  `projection_2028_2030`) and will be semantically wrong (though functional)
  for historical reports. `docs/metric_facts_mapping_spec.yml` depends on the
  literals.
- **Fix sketch:** era-neutral key names behind a schema-version bump; blast
  radius = mapping spec + all 55 fixture expected JSONs, so do it as its own
  ticket.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —

### Value Line parser: industrial-layout percent rows are not divided by 100
- **Found:** 2026-07-02, parser historical-readiness review (found while
  fixing F4)
- **Severity:** medium
- **Problem:** in `_parse_time_series_tables`, rows like `IncomeTaxRate`,
  `ReturnonShrEquity`, `RetainedtoComEq`, `AllDivToNetProf` pass
  `percent_ratio=insurance_layout` — so on industrial layouts the same
  economic quantity is stored as `21.0` where an insurance layout stores
  `0.21`. Downstream unit conventions may rely on this (fixtures lock it), but
  it is an inconsistency waiting to bite a cross-layout consumer.
- **Fix sketch:** decide one convention, migrate the mapping spec + fixtures
  in a dedicated pass; confirm whether the asymmetry is intentional first.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —

### 13F: follow-manager affordance
- **Found:** 2026-07-03, PO value-investor review of the 13F surface
  (`docs/tasks/2026-07-03_13f-po-review-value-investor.md` §3)
- **Severity:** medium
- **Problem:** There is no way for a user to follow specific managers; the
  filing-season digest (investor-workflow ticket 03) is featured-managers-only
  in V1, and the manager pages (ticket 01) have no personalization. The 13F
  habit loop ("my managers reported") needs per-user follows eventually.
- **Fix sketch:** small `manager_follows(user_id, manager_id)` table + star
  toggle on the manager list/detail pages; digest targeting switches from
  is_featured to followed-or-featured.
- **Context:** `docs/tasks/2026-07-03_13f-investor-workflow-03-filing-season-digest.md`
- **Issue:** —

### 13F: holding-streak saturation recalibration after historical backfill
- **Found:** 2026-07-03, PO value-investor review (§3)
- **Severity:** low (becomes medium once backfill lands)
- **Problem:** Conviction/persistence saturate at a 4-quarter streak — an
  artifact of the 2023+ data window, not an investment judgment. A value
  investor cares about 5+ year holders; once historical backfill extends the
  window, 4-quarter saturation materially understates long-tenure conviction.
- **Fix sketch:** revisit `_PERSISTENCE_STREAK_FULL` (conviction_score.py) and
  the streak bonus threshold together with a `SCORE_VERSION` bump, gated on
  backfilled data depth (readiness `historical depth` metric).
- **Context:** `docs/tasks/2026-07-03_13f-po-review-value-investor.md`
- **Issue:** —

### 13F: watchlist quarter-over-quarter trend + export
- **Found:** 2026-07-03, PO value-investor review (§4/§5)
- **Severity:** low
- **Problem:** Watchlist 13F columns show only the latest period (no QoQ
  conviction/Δ-holders trend sparkline), and no surface offers CSV export of
  candidates/holdings for offline research.
- **Fix sketch:** trend mini-viz on the watchlist 13F drawer once ≥3 quarters
  of persisted score history exist; simple CSV export endpoints for the
  Oracle's Lens candidates table and manager holdings.
- **Context:** `docs/tasks/2026-07-03_13f-po-review-value-investor.md`
- **Issue:** —

### 13F: `enrich_metadata` reports `new_stocks: 0` while creating thousands of stocks
- **Found:** 2026-07-10, prod-zero rehearsal (`claude/13f-prod-zero-rehearsal`)
- **Severity:** low (observability, not correctness)
- **Problem:** `enrich_all_unmapped_holdings` calls `bootstrap_stocks_from_cusip_map`
  once *after* its loop, but the per-batch path has already created the Stock
  rows, so the post-loop call returns 0. The sandbox created 1896 stocks and
  every `enrich_metadata` summary reported `new_stocks: 0`. An operator reading
  the job summary would conclude no stocks were created.
- **Fix sketch:** count created stocks inside the batch loop, or drop the
  post-loop bootstrap's return value from the summary and report the delta in
  `stocks` instead.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md`
- **Issue:** —

### 13F: a Rate Guard HTML error page is stored verbatim in `job_runs.summary_json`
- **Found:** 2026-07-10, prod-zero rehearsal
- **Severity:** low (observability)
- **Problem:** When the Rate Guard tunnel returns a Cloudflare 502, the whole
  HTML body (with IE conditional comments) is embedded in the daily-sync
  `last_error` and persisted into `JobRun.summary_json`. The actual signal — the
  HTTP status — has to be recovered by reading HTML out of JSONB. `edgar_fetch`
  errors should carry a status code and a truncated body.
- **Fix sketch:** in the Rate Guard client, raise with `status_code` and the
  first ~200 chars of the body; store both as structured fields.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md`
- **Issue:** —

### 13F: M5 (turn on the prod switches) must not ship before the pipeline fixes land
- **Found:** 2026-07-10, prod-zero rehearsal
- **Severity:** high (blocking dependency, no action needed until M5 opens)
- **Problem:** Turning on `EDGAR_SCHEDULER_ENABLED` / `THIRTEENF_JOB_WORKER_ENABLED`
  / `THIRTEENF_START_QUARTER` in prod *before* the `_ingest_candidate_filings`
  and `enrich_metadata` fixes would ingest holdings that never get scored, and
  would leave the newest report quarter permanently `pending` — while every job
  reported green. M5 depends on `claude/13f-prod-zero-rehearsal`.
- **Fix sketch:** land the rehearsal branch first; the cross-stage
  `pipeline_warning` guard then makes a regression visible in the admin job list.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md`
- **Issue:** —

### 13F: M5 needs startup-path tests the current suite does not have
- **Found:** 2026-07-10, external review of PR #115 (Missing Tests §7)
- **Severity:** medium (blocks M5, not this PR)
- **Problem:** `MANAGER_SEED_ON_STARTUP` is fail-loud by design, but no test covers
  what the API does when the database is unavailable at boot, when the seed's
  `pg_advisory_xact_lock` waits behind another container, or when real prod data
  puts managers in the `ambiguous_name_match` / `awaiting_confirmation` buckets.
  Fail-loud, hang, and degraded-start are three different outcomes and only one is
  acceptable.
- **Fix sketch:** boot-path tests with a refused connection, a held advisory lock
  in a second session, and a seeded ambiguous row; assert the process exits rather
  than hangs, and that the exit is distinguishable in the container logs.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md` (external review round)
- **Issue:** —

### 13F: 11 curated managers have a CIK that never files a 13F
- **Found:** 2026-07-10, verifying the from-zero rehearsal's claim that the pipeline "parses 13F data correctly"
- **Severity:** high — silent, product-visible, changes Oracle's Lens consensus
- **Problem:** `institution_managers` holds 82 confirmed managers; only 71 have ever
  produced a filing. The other 11 carry a CIK that is not the entity filing the 13F
  (Chou and Trian are off by one digit). `ingest_quarter_index` whitelists by CIK, so
  a wrong CIK matches nothing, forever, silently. `min_holders = 3` means Oracle's
  Lens consensus has been computed over 71 managers, missing Icahn, Einhorn, Tepper,
  Dalio, Peltz, ValueAct, Bridgewater, FPA, Third Avenue, Chou and Fundsmith.
  Verified against 45 319 13F records across 5 stored `form.idx` quarters: none of
  the 11 seeded CIKs appears as a filer in any of them. The other 71 are name-consistent
  with their EDGAR filer — no manager ingests the wrong filer's holdings.
  `match_cik_candidates()` cannot catch it: it only scans `cik IS NULL AND
  match_status IN ('seeded','candidate')`.
- **Fix sketch:** see the ticket. Correct the 11 CIKs; add a read-only
  `audit_seed_ciks` job that checks each confirmed CIK against EDGAR; add a readiness
  check for "confirmed manager, zero filings in the last N quarters"; then recompute
  ownership_changes + Lens for every quarter, because fixing this IS a universe change.
- **Context:** `docs/tasks/2026-07-10_13f-seed-cik-audit.md`
- **Issue:** —

### 13F: fixing the seed CIKs cannot repair an existing database — RESOLVED 2026-07-10 (PR #116)
- **Found:** 2026-07-10, while correcting `confirmed_managers.json`
- **Resolved:** `previous_ciks` + an audited `seed_cik_repoint` event make re-seed idempotent on an existing DB (`created=0`, one row per manager). The downstream recompute remains in the ticket.
- **Severity:** high (blocks applying the CIK fix to dev/prod)
- **Problem:** `seed_confirmed_managers` looks a manager up by `cik`, then by
  `dataroma_code`. A **changed** CIK is found by neither for 10 of the 11 corrected
  managers (only Bridgewater carries a dataroma_code). The seed therefore takes the
  CREATE path: where the normalized name still collides it refuses
  (`ambiguous_name_match`, loud and safe), and where the legal_name also changed —
  Icahn (`ICAHN CAPITAL MANAGEMENT LP` → `ICAHN CARL C`) and Greenlight
  (`GREENLIGHT CAPITAL INC` → `DME Capital Management, LP`) — it would mint a
  DUPLICATE confirmed manager row. An empty database is unaffected; dev and prod are not.
- **Fix sketch:** teach the seed a `previous_ciks` field (or an explicit re-point
  admin action that writes an `InstitutionManagerCikReviewEvent`), so a CIK change is
  an audited identity edit rather than a create. Then re-seed, backfill the 11
  managers' filings, and re-run `compute_ownership_changes` +
  `oracles_lens_score_backfill` for every quarter — adding 11 managers IS a universe
  change and `min_holders = 3` makes it a scoring change.
- **Context:** `docs/tasks/2026-07-10_13f-seed-cik-audit.md`
- **Issue:** —

### 13F: six managers report values in thousands under a dollars schema
- **Found:** 2026-07-10, from-zero rehearsal with the corrected seed
- **Severity:** medium (absolute values wrong by 1000x; weights and Lens unaffected)
- **Problem:** Every holding is tagged `value_unit_raw='dollars'`,
  `value_parse_rule='schema_dollars'`. Six managers file in **thousands** anyway, so
  their `value_usd` is 1000x too small. Detected by median implied share price
  (`value_usd / shares`), which should be $1–$1,000,000 for a US equity:
  Olstein $0.08, **Baupost / Klarman $0.12**, Vulcan $0.15, Triple Frond $0.22–0.25,
  AKO $0.28–0.29, Aquamarine $0.48–0.50. Compliant filers land where you'd expect:
  Berkshire $92–97, Bridgewater $77–80, Greenlight $25–30.
  The reconciliation check cannot catch this — the filer's own `tableValueTotal` is
  in the same wrong unit, so computed and reported agree exactly. Oracle's Lens is
  unaffected (portfolio weight is a within-manager ratio, hence scale-invariant), but
  every absolute dollar figure the product shows for those six is 1000x low.
- **Fix sketch:** an implied-price sanity check at ingest (median `value/shares`
  outside $0.50–$1e6 → flag), feeding the existing `effective_value_unit_override`
  mechanism instead of `infer`. Add it to `edgar_quality` as a warning first.
- **Context:** `docs/tasks/2026-07-10_13f-seed-cik-audit.md`
- **Issue:** —
