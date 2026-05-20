# 2026-05-20 — /admin/13f operational audit: issue triage

## Goal / Acceptance Criteria

- Walk every `/admin/13f` sub-page on the live site, collect every surfaced
  problem, sort by severity, and resolve them one by one with the user.
- Acceptance: each item below is either resolved (with a sign-off note) or
  consciously deferred. A finding that turns out to be a genuine code/infra bug
  and is *not* fixed now is demoted to `docs/BACKLOG.md` with a reason.

## Scope

- **In:** the runtime/operational issues displayed on `/admin/13f` and its
  sub-pages (Overview, Managers, Daily Sync, Filings, Holdings, Jobs,
  Readiness), reachable via the admin UI's own controls (retry, enrichment,
  quality check, classification, backfill).
- **Out:** code changes — unless diagnosis of a failing job (#1, #2, #5, #6)
  proves a real bug, in which case the fix gets its own task doc / PR.

## How the pages were reviewed

Browser session against `https://invest.richmom.vip/admin/13f` on 2026-05-20,
logged in with admin access. All seven tabs were visited and screenshotted;
the Jobs page was additionally filtered to `Failed` to enumerate failed runs.
Note: the `/admin/13f/daily-sync` path 404s — the Daily Sync tab actually
routes to `/admin/13f/sync` (recorded as a minor finding, see Notes).

## Findings (severity P1 → P3)

Status legend: `open` / `in-progress` / `done` / `deferred`.

### P1 — blocks operations

1. **[P1] No active worker heartbeat — `operations blocked`.**
   `status: done — PR #68 merged + deployed + verified in prod 2026-05-20`
   - **Not an outage.** The worker was healthy throughout (heartbeat age ~1s).
     Two real bugs, neither an outage:
     - *Frontend:* `readiness/page.tsx` calls `operationsHealth()` with a single
       object but the function takes 4 positional args → `hasAvailableWorker`
       always `undefined` → the page unconditionally renders "operations
       blocked / no active worker heartbeat".
     - *Backend:* prod compose runs uvicorn under `sh -c` (shell = PID 1), so
       SIGTERM never reaches uvicorn → no graceful shutdown → the worker never
       records `stopped` and leaks a `stale` heartbeat row every deploy (25 had
       piled up).
   - The container churn itself is just the deploy cadence (every `main` push),
     not a fault.
   - Fix: see `docs/tasks/2026-05-20_readiness-ops-health-worker-shutdown.md`.
     PR #68, merged + deployed 2026-05-20. Verified live: the readiness banner
     reason changed from the false "no active worker heartbeat" to the real
     "1 blocked setup item, 1 warning setup item" (→ items #8 / #7); the reaper
     flipped 25 zombie heartbeat rows to `stopped` on the new worker's startup.

2. **[P1] `fetch_daily_index` failed 3× in a row (Jobs #149/#150/#151).**
   `status: done — diagnosed, self-resolved, no data gap, no action needed`
   - **Root cause: transient EDGAR 403.** All three jobs' `summary_json`
     carried `last_error: "EDGAR 403 for .../form.20260519.idx — check
     User-Agent header or IP block"`. sync_date 2026-05-19 was attempted
     hourly: 00:00 / 01:00 / 02:00 UTC all 403 (attempt 1/2/3) — a ~3h
     IP-level rate-limit/block by SEC.
   - **Not a code bug, not deploy interruption.** Job #152 (attempt 4, 03:00
     UTC) succeeded with the *identical* code/config — so the User-Agent is
     fine; it was a transient IP block that cleared. The built-in hourly retry
     worked as designed.
   - **No data gap.** #152 fetched the index (`raw_document_id: 499`);
     `filings_seen_count: 0` is normal for a non-deadline day.
   - The 3 entries on the Overview Admin Tasks panel are stale diagnostic
     history (the panel is diagnostic, not a retry control — runbook #42).
     They need no action and age out on their own.
   - Watch-item only: if EDGAR 403s recur frequently, revisit the request
     rate / User-Agent. A single self-healed incident does not warrant a fix.

### P2 — data incomplete / quality

3. **[P2] `quarterly_pipeline` 2026-Q2 partial success — 58 failed
   accessions.** `status: done — already resolved, no action needed`
   - #3 and #4 are the **same 58 accessions**: job #92 (`quarterly_pipeline`)
     is `partial_success` only because its sub-stage #106 (`ingest_holdings`)
     was partial.
   - Root cause of #106's failures: the 58 filings' infotable XML files were
     missing on disk (legacy damage from pre-PR#48 deploys that wiped the
     `storage/edgar_raw` bind-mount). #106 ran 2026-05-19 22:11 UTC — *before*
     PR #51 (22:33 UTC) wired the `ensure_filing_infotable_doc` self-heal into
     `ingest_holdings` — so it read the missing files and failed without
     re-fetching (`filings_xml_fetched: 0`, 71ms run).
   - **Already resolved.** Verified via the prod API: all 58 failed accessions
     are present in the filings table as `report_quarter=2026-Q1` filings and
     **all 58 have holdings ingested** (1–602 each). A later pipeline run with
     the self-heal re-fetched and ingested them. The "Retry holdings for
     2026-Q2" dry-run correctly shows 0 filings / 0 failed — nothing to retry.
     ("2026-Q2" = the *filing* quarter; these report on *period* 2026-Q1.)
   - Job #92/#106 remain as historical `partial_success` rows; the Overview
     panel surfaces them as stale diagnostic history. No action; no prod
     change was made (the retry was not queued).

4. **[P2] `ingest_holdings` 2026-Q2 partial success — 58 failed accessions.**
   `status: done — same 58 as #3, already resolved`
   - Job #106 is the `ingest_holdings` stage of #92. See item #3 — resolved.

5. **[P2] `enrich_metadata` failed across 4 quarters.**
   `status: done — stale, already resolved`
   - Verified via prod jobs API: the *latest* `enrich_metadata` run for every
     affected quarter (2026-Q2 #180, 2026-Q1 #175, 2025-Q4 #170, 2025-Q3 #165)
     is `succeeded` (the 2026-05-20 04:04 pipeline re-run). The failures were
     transient 2026-05-19-churn history. No action needed.

6. **[P2] `fetch_quarter_index` 2025-Q4 failed 3×.**
   `status: done — stale, already resolved`
   - Verified via prod jobs API: `fetch_quarter_index:2025-Q4` failed on jobs
     #3/#4/#5, then succeeded from job #6 (2026-05-19 18:47) onward and every
     run since (#17/#37/#57/#77/#97…). No action needed.

7. **[P2] Holdings link rate only 12%.**
   `status: deferred → docs/BACKLOG.md`
   - Real, current gap (verified via the prod coverage API): 2026-Q1 has 4,278
     common holdings, 504 linked (11.8%); ~2,084 distinct unresolved CUSIPs,
     mega-caps included.
   - The admin "Run CUSIP enrichment" (`enrich_metadata`) only applies
     *existing* `CusipTickerMap` rows — it creates none — so re-running it
     cannot raise the rate. "Enrich stocks from EDGAR" was a no-op placeholder.
     Closing the gap needs OpenFIGI enrichment run at scale — a data-completeness
     effort with no single admin-UI trigger.
   - Deferred to `docs/BACKLOG.md`. The no-op "Enrich stocks from EDGAR"
     trigger surface was removed in PR #70.

8. **[P2] Quality check blocked.**
   `status: deferred → docs/BACKLOG.md`
   - "Quality checked" is blocked because the latest quality report is status
     `warning` (0 errors). All 63 (2026-Q1) warnings are the single
     `period_alignment` check — `_check_period_alignment` compares
     `period_of_report` against the *filing* quarter, which is wrong for 13F (a
     13F always reports a prior quarter-end, so it never aligns with the filing
     quarter). Verified: all 63 flagged filings are correctly bucketed
     (`report_quarter` matches `period_of_report`). The check false-positives
     on essentially every 13F.
   - Re-running quality check is futile. Fixing the check needs a product
     decision on its intended semantics. Deferred to `docs/BACKLOG.md`.

### P3 — maintenance

9. **[P3] All 80 managers have `manager_type = unknown`.**
   `status: deferred → docs/BACKLOG.md`
   - Confirmed via the prod API. `manager_type` is not cosmetic — it feeds
     Oracle's Lens scoring (taxonomy / signal weighting). But classifying a
     manager needs an authoritative type plus a mandatory justification note
     (audited via `institution_manager_type_review_events`), and the system
     already has an "unknown-manager priority queue" workflow for it.
   - Ongoing human curation, not a bulk edit. Deferred to `docs/BACKLOG.md`
     for team curation.

10. **[P3] Candidate managers without a CIK.**
    `status: done — PR #71 merged + deployed; seed CLI run on prod`
    - 10 candidate managers (the early "≥3" was the first screen only), all
      `seeded` / no CIK. CIKs researched on SEC EDGAR — each a current active
      13F-HR filer — and added to `confirmed_managers.json` (PR #71). Ruane
      Cunniff uses the active L.P. CIK, not the dormant Inc; RV Capital files
      as the AG entity.
    - Applied on prod after deploy: `seed-confirmed-managers` CLI →
      `Seeded 20 confirmed managers`. Verified: all 10 now `confirmed` with
      their CIKs, `managers_without_cik: 0`, all 86 managers confirmed (the
      run also created 6 curated confirmed managers previously absent from the
      DB). See `docs/tasks/2026-05-20_seed-confirmed-managers-10-ciks.md`.

11. **[P3] Extended backfill recommended.**
    `status: deferred → docs/BACKLOG.md`
    - Overview Admin Tasks P3 entry; optional maintenance. EDGAR rate-limit
      budget was free (600/600). Per the user's decision, skipped this round
      and recorded in `docs/BACKLOG.md` for when it is wanted.

## Notes

- 2026-05-20: audit requested by the user; the seven tabs were browsed live.
  This doc is the persistent record — the in-session task list (#1–#11) is
  ephemeral and does not survive the session.
- Minor finding (not tracked as a numbered item): `/admin/13f/daily-sync`
  returns the 404 page; the Daily Sync tab routes to `/admin/13f/sync`. Worth a
  redirect or a tidy-up if the team cares, but not operationally blocking.

## Sign-off trail

- 2026-05-20 · #1 · Diagnosed: no outage — worker healthy throughout. Root
  causes were a frontend arg-shape bug and a missing `exec` in prod compose.
  Fixed on branch `claude/fix-readiness-ops-health-worker-shutdown` (frontend
  call site + type, prod compose `exec`, stale-heartbeat reaper + tests);
  canonical CI green. **PR #68 merged + deployed + verified in prod.** The
  readiness banner now reports real reasons, not the false worker alarm; 25
  zombie heartbeat rows reaped to `stopped`. DONE.
- 2026-05-20 · #2 · Diagnosed via prod jobs API: all 3 `fetch_daily_index`
  failures were transient EDGAR 403 (IP rate-limit) over a ~3h window;
  self-resolved on attempt 4 (#152). No code bug, no data gap, no action
  needed. DONE.
- 2026-05-20 · #3 + #4 · Same 58 accessions. job #106 failed them pre-self-heal
  (ran 22 min before PR #51 merged). Verified via prod API: all 58 are now in
  the filings table (report_quarter 2026-Q1) with holdings ingested — already
  resolved by a later self-healing run. "Retry holdings" dry-run showed 0
  filings, so it was cancelled, not queued; no prod change made. DONE.
- 2026-05-20 · #5 + #6 · Verified via prod jobs API: both are stale 2026-05-19
  churn history. `enrich_metadata` — latest run per affected quarter all
  succeeded (04:04 re-run). `fetch_quarter_index:2025-Q4` — succeeded from job
  #6 onward and every run since. No action needed. DONE.
- 2026-05-20 · Pattern · Items #2–#6 were all transient failures from the
  heavy 2026-05-19 pipeline-churn window, every one already self-resolved by a
  later run. The Overview Admin Tasks panel surfaces them as stale diagnostic
  history. Consider a recency window on that panel — logged as a watch-item,
  not actioned here.
- 2026-05-20 · #7 · CUSIP link rate (~12%) is a real data-completeness gap;
  the admin enrichment buttons cannot close it. Deferred to `docs/BACKLOG.md`.
  The no-op `enrich_stocks_edgar` trigger surface was removed (PR #70, merged).
- 2026-05-20 · #8 · `_check_period_alignment` mis-compares `period_of_report`
  to the filing quarter → false-positive warning on essentially every 13F →
  "Quality checked" permanently blocked. Deferred to `docs/BACKLOG.md`.
- 2026-05-20 · #9 · `manager_type` all `unknown`; real (feeds Oracle's Lens)
  but a human-curation effort. Deferred to `docs/BACKLOG.md` for the team.
- 2026-05-20 · #10 · 10 candidate managers' CIKs researched on SEC EDGAR,
  added to `confirmed_managers.json` (PR #71, merged + deployed), applied on
  prod via `seed-confirmed-managers`. All managers now confirmed with a CIK.
  DONE.
- 2026-05-20 · #11 · Extended backfill — optional maintenance; skipped this
  round per the user, recorded in `docs/BACKLOG.md`.
- 2026-05-20 · Audit complete · All 11 items triaged. Shipped: #1 (PR #68),
  #7-no-op-button (PR #70), #10 (PR #71). Self-resolved: #2-#6. Deferred to
  `docs/BACKLOG.md`: #7, #8, #9, #11.
