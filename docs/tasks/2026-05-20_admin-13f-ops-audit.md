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
   `status: fix-ready (branch claude/fix-readiness-ops-health-worker-shutdown)`
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
     Canonical CI green. Takes effect on the next prod deploy.

2. **[P1] `fetch_daily_index` failed 3× in a row (Jobs #149/#150/#151).**
   `status: open`
   - Overview Admin Tasks: three P1 entries. Daily Sync page: 2026-05-19 runs
     at 17:00, 18:00, 19:00 all `failed`; 20:00 `succeeded`.
   - Failed accessions = 0 on each — the job crashed before processing, not an
     accession-level error.
   - Action: open each run via Jobs → Review, read the error detail, find the
     root cause; confirm today's run is stable.

### P2 — data incomplete / quality

3. **[P2] `quarterly_pipeline` 2026-Q2 partial success — 58 failed
   accessions.** `status: open`
   - Job #92 (`quarterly_pipeline · partial_success`, Quarter 2026-Q2).
   - Overview lists every retry target. Action: retry the 58 accessions via
     Overview retry controls / Manual Controls → Retry accession.

4. **[P2] `ingest_holdings` 2026-Q2 partial success — 58 failed accessions.**
   `status: open`
   - Job #106 (`ingest_holdings · partial_success`, Quarter 2026-Q2); retry
     target list matches #3.
   - Action: Manual Controls → Ingest holdings / Retry accession.

5. **[P2] `enrich_metadata` failed across 4 quarters.** `status: open`
   - Jobs (Failed filter): one failure each for 2026-Q2, 2026-Q1, 2025-Q4,
     2025-Q3; no worker shown on any.
   - Action: Review each for the error detail, then re-trigger.

6. **[P2] `fetch_quarter_index` 2025-Q4 failed 3×.** `status: open`
   - Jobs (Failed filter): three failures for 2025-Q4, three different workers.
   - Action: Review the error detail, then Manual Controls → Fetch quarter
     index (target 2025-Q4).

7. **[P2] Holdings link rate only 12%.** `status: open`
   - Holdings page (2026-Q1): 4,296 holdings, 504 linked (12%), 3,774
     unresolved common. Readiness checklist "CUSIP enriched" = warning. Top
     unresolved CUSIPs are large issuers (Alphabet, Visa, Amazon, TSMC ADR,
     BofA, …).
   - Action: Overview Manual Controls → Run CUSIP enrichment + Bootstrap
     stocks; re-check link rate reaches the ready threshold (~80%).

8. **[P2] Quality check blocked.** `status: open`
   - Readiness checklist "Quality checked" = blocked ("Run quality check and
     reprocess pending or failed amendments"). Quality Reports: 2026-Q2 = 58
     warnings, 2026-Q1 = 63, 2025-Q4 = 61, 2025-Q3 = 65 (all 0 errors).
   - Action: Manual Controls → Quality check; review warnings, accept or fix;
     reprocess the affected amendments.

### P3 — maintenance

9. **[P3] All 80 managers have `manager_type = unknown`.** `status: open`
   - Managers page: every row shows the orange `unknown` type.
   - Action: classify each via Edit (hedge_fund / mutual_fund / etc.).

10. **[P3] Candidate managers without a CIK.** `status: open`
    - Managers page: ≥3 rows with status `candidate`, match_status `seeded`,
      empty CIK — Bill Nygren · Oakmark Funds, Christopher Davis · Davis
      Advisors, Dodge & Cox Funds.
    - Action: look up each CIK on EDGAR, fill via Edit, promote to `confirmed`.

11. **[P3] Extended backfill recommended.** `status: open`
    - Overview Admin Tasks P3 entry. EDGAR rate limit currently 600/600 free.
    - Action: Manual Controls → Backfill, set a start quarter, run.

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
  canonical CI green. Pending commit/PR/deploy.
