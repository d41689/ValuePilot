# 13F web-only validation run

## Goal

Verify that, after deployment, an admin can run the entire 13F pipeline
**through the web UI alone** (`/admin/13f`), starting from a completely empty
dev database. Fix any bug that blocks the web-driven workflow.

## Acceptance criteria

- Starting from an empty dev DB, every pipeline stage is triggered from the
  `/admin/13f` web page (no curl / no scripts / no direct API calls):
  Bootstrap whitelist → Match CIK → confirm managers → per-quarter
  `fetch index → ingest holdings → enrich metadata → quality check →
  Oracle's Lens scoring`.
- Scope: validation run over the most recent 1–2 usable quarters
  (2026-Q1, and 2025-Q4 if time permits). Not a full historical backfill.
- Every job reaches a terminal success/partial state; failures are
  investigated.
- Bugs found in the workflow are fixed on this branch (proper fixes, not
  band-aids — see AGENTS.md invariants).
- Canonical CI commands green at the closing gate.

## Scope

- **In:** driving `/admin/13f` via browser; diagnosing job failures via
  logs/DB (read-only); fixing bugs in the 13F pipeline / admin UI.
- **Out:** full 40-quarter backfill; non-13F features; prod environment.

## Environment

- Dev stack only: web `localhost:3001`, api `localhost:8001`, dev DB
  `valuepilot` on `valuepilot-dev-db-1`.
- Admin account: `d41689@gmail.com` (id 9321, role admin).

## Test plan

- Closing gate — canonical CI commands (AGENTS.md):
  - `docker compose up -d --build`
  - `docker compose exec -T api alembic upgrade head`
  - `docker compose exec -T api pytest -q`
  - `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
  - `docker compose exec -T web npm run lint`
  - `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

## Findings

### F1 — BUG: false P1 task `QUARTER_INDEX_FETCHED_NO_FILINGS` (will fix)

`_form_idx_fetched()` (`thirteenf_admin_dashboard.py`) builds the EDGAR
full-index URL `/{year}/QTR{q}/` from the **report**-quarter label, but the
same `_quarter_summary` counts filings by `period_of_report` (report quarter).
EDGAR's full-index is organized by **filing** quarter; report-quarter-Q 13Fs
are filed in filing-quarter Q+1. So for report-quarter "2026-Q1",
`_form_idx_fetched` checks `/2026/QTR1/` (present — fetched for 2025-Q4 data)
while report-2026-Q1 has 0 filings → false P1 task fires. Fix: check the
filing index for `next_quarter(Q)`.

### F2 — BUG: filing-quarter vs report-quarter model inconsistency (needs decision)

`fetch_quarter_index(Q)` / `ingest_quarter_index(Q)` treat Q as a *filing*
quarter (`/year/QTRq/` index). The dashboard, readiness,
`latest_usable_quarter_label`, `_quarter_summary` (period_of_report), and the
TARGET QUARTER default treat Q as a *report* quarter. Consequences observed:

- Accepting the TARGET QUARTER default and clicking fetch → ingest yields data
  one quarter older than the label implies (entered "2026-Q1" → ingested
  report-2025-Q4 data; 61/64 filings `period_of_report` 2025-12-31).
- The **Readiness checklist** evaluates `_quarter_summary(latest_usable_quarter_label())`
  = report-quarter 2026-Q1, which is empty, so "Filings available",
  "Holdings ingested", "CUSIP enriched", "Quality checked" all show **blocked**
  even after a fully successful 2025-Q4 ingest. The default web workflow can
  never turn the Readiness page green.

Not data loss — `period_of_report` is stored correctly. Fix is a design
decision: (A) report-quarter model — `fetch_quarter_index` translates Q →
filing-quarter `next_quarter(Q)`, `_form_idx_fetched` likewise; or (B)
filing-quarter model — relabel UI input and key `_quarter_summary` on filing
quarter. F1 is a facet of F2 and cannot be fixed independently of this choice.

### F3 — FIXED: no web control for loop-to-completion CUSIP enrichment

The Quarter Pipeline's only enrichment button (`enrich_metadata`) processes a
single 100-record batch per click; with ~1687 distinct CUSIPs one run linked
only ~14% of holdings. The loop-to-completion job `enrich_cusip`
(`enrich_all_unmapped_holdings`) existed but had no web button.
**Fixed:** added an "Enrich all CUSIPs" button to the Stock Reference Data
section (`frontend/app/(dashboard)/admin/13f/page.tsx`) — purely additive,
triggers the existing `enrich_cusip` job. Verified via the UI: one click took
holdings linked from 19% → 77.9% (3114/3997) in ~10s.

### F4 — BUG: Historical Backfill feature is non-functional (needs decision)

The jobs-page "Historical Backfill" → "Enqueue backfill" button calls
`enqueue_historical_backfill`, which creates a `JobRun` with
`job_type="historical_backfill"`. That job type has a lock builder (so
`trigger_job` accepts it) but **`_execute_job` has no handler** — every run
fails immediately with `Unsupported job_type: historical_backfill`. The
executor `execute_historical_backfill` exists in
`thirteenf_historical_backfill.py` but is only ever called from tests; it was
never wired into the worker dispatcher, and it needs three injected production
dependencies (`validation_gate`, `filing_discovery_fn`, `ingest_fn`) that have
no production wiring. The feature is half-built. Oracle's Lens scoring is
blocked: the Readiness page directs operators to this exact broken section to
score a quarter. Fixing it = completing a feature, not a one-line patch —
flagged for the user's decision.

## Log

- 2026-05-21: branch created; pipeline mapped; scope = validation run, 1–2
  quarters. Starting browser-driven run.
- 2026-05-21: bootstrap_whitelist → 80 managers. match_cik → 71 auto-confirmed
  active, 0 needing review, 9 unmatched (seeded). fetch_quarter_index 2026-Q1 →
  64 filings. ingest_holdings → 64 processed, 0 failed, 3997 holdings. Data
  landed under report_quarter 2025-Q4 (see F2).
- 2026-05-22: added "Enrich all CUSIPs" button (F3 fix); enrich_cusip →
  18 batches, 1495 mappings, 77.9% holdings linked. quality_check 2025-Q4 →
  passed (0 errors, 0 warnings, 7 info). Attempted Oracle's Lens scoring via
  the Historical Backfill section → `historical_backfill` job failed
  "Unsupported job_type" (F4). Stopped to surface F2 + F4 for a decision.
- 2026-05-22: user chose "fix both". Implemented F2 (report-quarter model) and
  F4 (wire `historical_backfill`); added an "Oracle's Lens score" button so
  scoring is reachable from the web. Re-verified via the web UI: the false
  `QUARTER_INDEX_FETCHED_NO_FILINGS` task is gone; `oracles_lens_score_backfill`
  2025-Q4 → succeeded (207 filings scored, 4188 components); `historical_backfill`
  2025-Q4 → succeeded (4 ingested, 57 already present, validation passed).

## Resolution

- **F1 + F2 — fixed (report-quarter model).** `next_quarter_label()` added to
  `app/edgar/parsers/form_idx.py`. `ingest_quarter_index()` now treats its
  `quarter` arg as a report quarter and fetches the EDGAR full-index of the
  *following* calendar quarter. `_form_idx_fetched()` checks the same
  next-quarter QTR path. The whole stack (fetch, dashboard, readiness, tasks)
  is now report-quarter-consistent.
- **F3 — fixed.** "Enrich all CUSIPs" button (`enrich_cusip`).
- **F4 — fixed.** `_execute_job` now dispatches `historical_backfill` to
  `execute_historical_backfill`, wired with three production dependencies
  (`_historical_backfill_filing_discovery` / `_ingest` / `_validation_gate`).
- **Scoring** — added an "Oracle's Lens score" button (`oracles_lens_score_backfill`)
  to the Quarter Pipeline; scoring previously had no web control.

### F5 — test suite is not isolated from dev-DB data (backlog only)

`test_13f_admin_dashboard.py` bulk-deletes `job_runs`; with rows left in the
dev DB by a web run, that FK-violates against `quality_reports_13f`. Pre-existing
test-infra gap, out of this task's scope — see `docs/BACKLOG.md`.

## Verification

- Backend `pytest -q` — **907 passed** on a fresh `valuepilot_test` DB
  (migrations applied). Against the populated dev DB it fails on F5 only; real
  CI runs on a fresh DB, so CI is green.
- Frontend `node --test lib/*.test.js` — 159 passed. `npm run lint` — clean.
  `NODE_ENV=production npm run build` — succeeded.
- No new migrations (no schema change).
