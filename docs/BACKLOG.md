# Backlog — deferred work

Problems discovered but not yet fixed. The capture rule is in
`AGENTS.md` → Workflow → "Deferred work". Each entry stays until the work is
actually done — remove it in the same PR that resolves it.

Severity: **high** = data-loss / security / production risk; should not sit here
long — escalate to the user. **medium / low** = ordinary follow-up.

## Open

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
