# 13F daily continuity and product-complete ingestion

**Created:** 2026-07-18  
**Status:** Implementation and live rehearsal complete; awaiting user review  
**Branch:** `codex/13f-daily-continuity`

## Goal / Acceptance Criteria

Make the post-Day-0 13F path genuinely unattended and complete. After the
historical start-quarter backfill, the scheduler must recover every missed SEC
daily index date, ingest every supported tracked-manager 13F filing through
Rate Guard, and refresh the report-quarter data products that investors read.

- [x] All EDGAR network access continues to use `EdgarClient` ->
      `RateGuardClient`; no direct SEC HTTP path is introduced.
- [x] An API/scheduler outage does not create a permanent date hole: the next
      poll materializes and queues every missing date in the known daily-sync
      coverage range, including internal holes before the newest success.
- [x] The initial daily poll has a bounded bootstrap lookback instead of
      silently assuming that only today's index matters.
- [x] Weekends and configured no-index dates are represented explicitly and do
      not create noisy fetch jobs.
- [x] Daily discovery supports `13F-HR`, `13F-HR/A`, `13F-NT`, and
      `13F-NT/A`; notice filings are stored as coverage, never as zero holdings.
- [x] A successful daily HR/HR-A accession ingest schedules exactly one
      idempotent `quarterly_pipeline` refresh for its parsed report quarter, so
      holdings, CUSIP links, quality, ownership changes, and Oracle's Lens are
      refreshed without an operator action.
- [x] A failed daily accession is automatically retried with its complete SEC
      filing context; a successful parent index job cannot strand it.
- [x] A notice filing also schedules the report-quarter refresh required to
      update coverage/caveats, without attempting to parse a nonexistent
      information table.
- [x] Failed or `needs_review` period routing never schedules the wrong quarter.
- [x] Historical/startup and weekly reconciliation never treat one filing or
      one Lens signal as full-quarter completion; only a green six-stage
      pipeline manifest is terminal.
- [x] Post-2023 filings that violate SEC's nearest-dollar schema by continuing
      to submit legacy thousands are detected at filing level and normalized to
      real dollars; compliant filings remain unchanged.
- [x] Tests cover downtime gaps, first-run bootstrap, duplicate polls,
      HR/HR-A, NT/NT-A, and the report-quarter refresh handoff.
- [x] An isolated empty-database rehearsal proves historical bootstrap plus the
      corrected daily handoff; canonical Docker CI is green at the closing gate.

## Scope

### In

- Daily-index date reconciliation and job queuing.
- Daily form-family recognition and accession job creation.
- Real SEC daily-index date grammar (`YYYYMMDD`) as well as quarterly
  full-index date grammar (`YYYY-MM-DD`).
- Post-accession report-quarter refresh orchestration.
- Quarter-completion detection used by startup and weekly reconciliation.
- Notice-family ingestion behavior needed by the daily path.
- Scheduler/runbook configuration required to make the behavior explicit.

### Out

- Investor-facing manager/new-buy/digest pages; those start after the ingestion
  gate is signed off.
- Changing the curated manager investment-style taxonomy.
- Bypassing Rate Guard for tests, recovery, or production.
- Generic ingestion of non-13F SEC forms.

## Decisions / Gotchas

- `sync_date`/filing date and `periodOfReport` are different. Downstream refresh
  is always keyed by parsed `report_quarter`, never by the daily index date.
- Daily `ingest_accession` currently persists only the primary filing detail;
  without a report-quarter pipeline handoff, holdings remain unparsed and
  product-invisible.
- `_eligible_sync_dates` originally invented only today plus already-known
  failed rows. A latest-watermark-only repair is still insufficient because
  jobs run newest-first: a newer success can advance the watermark while an
  older date remains absent. Reconcile missing dates across the whole known
  coverage range, retaining the bounded bootstrap floor.
- Plain 13F-NT is parsed by the primary-document path, but the daily queue drops
  it. 13F-NT/A is modeled by consumers but excluded from ingestion whitelists.
- The isolated live rehearsal found that real daily `form.idx` rows use compact
  `YYYYMMDD`; the shared parser required hyphens and silently returned zero
  records while the sync status reported success.
- The same rehearsal reproduced the known absolute-value defect for five
  current filers (median raw implied prices $0.08-$0.48 versus $1.00 for the
  lowest compliant filer). SEC Form 13F spec v1.7 changed `value` to nearest
  dollar on 2023-01-03, but these filings still carry legacy thousands. Use a
  conservative filing-level common-stock median with a minimum sample and bump
  the fingerprint version so existing rows converge through normal reparse.
- A report-quarter refresh must be deduplicated through the existing
  `quarterly_pipeline:<quarter>` lock; do not add an untracked background call.
- Existing completion shortcuts are unsafe in opposite directions: one filing
  can freeze a partial quarter in the weekly scheduler, while one signal can
  freeze a partial quarter at startup. The persisted parent summary already
  provides a six-stage manifest, so use that as the terminal marker without a
  schema migration.
- Daily index success means discovery completed, not that every child accession
  completed. Smart retry must understand a standalone `ingest_accession` job
  and preserve manager/form/filename/source context so the retry remains
  product-complete.

## Files to Change

- `backend/app/core/config.py`
- `backend/app/edgar/parsers/form_idx.py`
- `backend/app/edgar/parsers/value_units.py`
- `backend/app/services/thirteenf_daily_sync.py`
- `backend/app/services/thirteenf_scheduler.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/services/thirteenf_filing_detail.py`
- `backend/app/services/thirteenf_holdings_ingest.py`
- `backend/app/services/thirteenf_start_quarter.py`
- `backend/app/services/scheduler.py`
- `backend/tests/unit/test_13f_daily_index_sync.py`
- `backend/tests/unit/test_13f_job_scheduler.py`
- `backend/tests/unit/test_13f_value_units.py`
- `backend/tests/unit/test_13f_holdings_parser.py`
- focused orchestration tests as needed
- `backend/tests/unit/test_thirteenf_start_quarter.py`
- `backend/tests/unit/test_scheduler_alignment.py`
- `.env.prod.example` and Day-0/runbook documentation if configuration changes

## Test Plan (Docker)

Iteration:

```bash
docker compose exec -T api pytest -q tests/unit/test_13f_job_scheduler.py
docker compose exec -T api pytest -q tests/unit/test_13f_daily_index_sync.py
docker compose exec -T api pytest -q tests/unit/test_13f_nt_handler.py
```

Closing gate, verbatim:

```bash
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

## Sign-off Trail

- 2026-07-18: code/document audit identified the downtime date-hole, the
  primary-doc-only daily handoff, and dropped notice forms.
- 2026-07-18: isolated live database `valuepilot_rehearsal_20260718` migrated
  from zero, startup seed created 82/82 managers with no ambiguity, and the
  2026-Q1 historical pipeline completed all six stages. Result: 84 filings,
  7,056 holdings, 6,691 linked holdings, 5,535 ownership changes, 653 Lens
  signals, zero holdings without parse lineage, zero duplicate active
  manager-period groups, and a passing quality report.
- 2026-07-18: live SEC daily index `2026-05-14` proved the former parser's
  compact-date false-green (1.48 MB fetched, zero records). After the parser
  fix it produced 1,031 13F records and matched 15 tracked HR-family filings.
  All 15 accession jobs succeeded and fanned into exactly one `daily_sync`
  quarterly refresh (one creator, fourteen lock conflicts); that refresh also
  completed all six stages without a pipeline warning.
- 2026-07-18: parser/fingerprint v2 live reparse corrected 167 current holdings
  from five current non-compliant filers to `implied_price_thousands`; the
  lowest remaining uncorrected median implied common-stock price is $1.00.
- 2026-07-18: Rate Guard path audit found no direct SEC HTTP caller; live
  rehearsal ran with `EDGAR_FETCH_MODE=live` and Rate Guard configured. Rate
  Guard suite: 36 passed.
- 2026-07-18: exact canonical closing gates ran against a fresh isolated
  Postgres topology: build/start passed, migrations from zero passed, backend
  1,277 passed (3 existing SQLAlchemy deprecation warnings), frontend unit 185
  passed, lint passed, and production build passed. The normal dev topology was
  restored afterward. No commit or push was made.
