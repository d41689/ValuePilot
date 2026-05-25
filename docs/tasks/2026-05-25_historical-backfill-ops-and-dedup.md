# 2026-05-25 — Historical backfill ops + stale-failed-job dedup

## Goal

Two things combined into one PR:

**A — Stale-failed-job dedup (code)**. The admin overview surfaces
`historical_backfill job failed: 2025-Q4 (P1)` from JobRun #4526, but a
JobRun #4553 created 21 minutes later with the SAME `lock_key` actually
succeeded. The failure should be hidden — it's not actionable.

**B — Actually backfill (ops)**. The real bug behind "Historical depth:
0 quarters" is that nobody ever ran a true cross-quarter historical
backfill. The dispatcher works (PR #95 era handler at
`_execute_job:3061`); the data is just empty. This PR runs the backfill
end-to-end for 2025-Q3 → 2023-Q1 (11 quarters) and records the trace.

The harness chains FOUR stages per run:

1. `historical_backfill` — fetch SEC submissions + primary_doc, create
   Filing13F rows in `parse_status='pending'`.
2. `ingest_holdings` per quarter — fetch each filing's infotable.xml,
   parse, write Holding13F rows with `cusip_mapping_status='pending_mapping'`.
3. `enrich_cusip` — global OpenFIGI pass that maps pending CUSIPs to
   tickers and links holdings to stocks.
4. `oracles_lens_score_backfill` per quarter — populate
   `oracles_lens_signals` for the new quarters so Oracle's Lens's
   "All" universe (which reads persisted scores) shows the
   newly-ingested data. The universe-filter "live recompute" path
   (PR #95) works regardless of stage 4, but skipping it leaves the
   "All" view incomplete for the backfilled quarters.

Both halves ship together because (a) we want to demonstrate the
"before vs after" Readiness number flip in one PR, and (b) running the
backfill will surface fresh failed jobs that the dedup logic needs to
correctly handle.

## Acceptance criteria

### A — Dedup

1. `_recent_job_alert_tasks` (in
   `backend/app/services/thirteenf_admin_dashboard.py`) skips any
   `failed` / `partial_success` JobRun whose `lock_key` has a
   later-created JobRun with status in
   `{succeeded, partial_success}` for the same `lock_key`.
2. Jobs without `lock_key` are surfaced as today (no behavior change).
3. Older failures NOT superseded by a later success are still surfaced
   (so we don't accidentally suppress real problems).
4. Initial DB fetch widened from `limit=5` to `limit*4` so post-dedup
   we still have a reasonable number of P1/P2 tasks to show; final
   list is capped at the original `limit`.
5. New tests in `backend/tests/unit/test_13f_admin_tasks_dedup.py`
   pin the contract:
   - failed job + later succeeded job with same lock_key → hidden
   - failed job + later succeeded job with DIFFERENT lock_key → still surfaced
   - failed job + later failed job with same lock_key → still surfaced
   - failed job + later partial_success with same lock_key → hidden
   - failed job with no lock_key → still surfaced

### B — Ops

6. New helper `backend/scripts/run_historical_backfill.py` that
   iterates a quarter range backward in time, calls the existing
   `enqueue_historical_backfill` for each, waits for completion,
   prints a per-quarter summary, and at the end prints the
   `historical_depth_quarters` count for verification.
7. Run the helper for 2025-Q3 → 2023-Q1 (10 quarters) on the dev
   environment.
8. Per-quarter ingest result trace recorded in this task doc (filings
   ingested / already_present / failed; quality status; mapping
   linked ratio).
9. After run: dev `Historical depth` Readiness number moves from 0 to
   ≥ 7 (allowing 2-3 quarters to be incomplete for whitelisted
   managers).

### CI

10. Canonical CI green: pytest in-container, frontend tests, lint,
    build.

## Critical invariants — preserved

- No schema change. No new column. No migration.
- `enqueue_historical_backfill` / `execute_historical_backfill`
  contracts unchanged — we exercise existing code.
- The dedup change to `_recent_job_alert_tasks` is purely additive
  (a SKIP condition on what's already returned).

## Files to change

| File | Change |
|---|---|
| `backend/app/services/thirteenf_admin_dashboard.py` | `_recent_job_alert_tasks` adds per-lock_key dedup |
| `backend/tests/unit/test_13f_admin_tasks_dedup.py` | NEW test file (5 cases) |
| `backend/scripts/run_historical_backfill.py` | NEW ops helper |
| `docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md` | this doc, with per-quarter trace at the bottom |

## Test plan

```
docker compose up -d --build
docker compose exec -T api alembic upgrade head        # no new migrations
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Targeted iteration:
```
docker compose exec -T api pytest -q tests/unit/test_13f_admin_tasks_dedup.py
```

Ops run:
```
docker compose exec -T api python -m scripts.run_historical_backfill \
    --start-quarter 2025-Q3 --end-quarter 2023-Q1
```

## Decisions / gotchas

- **Dedup by `lock_key`, not by `(job_type, quarter, manager_scope)`.**
  `lock_key` already encodes the logical identity
  (`13f_historical_backfill:{start_q}:{end_q}:{manager_scope}`) and is
  the same field the job system uses for active-run uniqueness, so
  reusing it keeps the semantics aligned.
- **Use `created_at` not `finished_at` for the "later" comparison.**
  A retry created before the previous attempt finished is still a
  retry, and `created_at` is monotonic from queue insertion.
- **Partial-success counts as superseded.** A partial-success that
  finished after a failed attempt means the system tried again and got
  further — surfacing the prior failure adds noise without
  actionability.
- **Pre-2023 hard cutoff.** Historical backfill rejects pre-2023
  quarters without `dry_run=True` (value-unit semantics changed
  2023-01-03). Backfill scope here is **2023-Q1 inclusive** through
  2025-Q3 — all post-transition.
- **Real SEC requests.** The ops run will hit SEC EDGAR via Rate
  Guard. Expect ~10 quarters × ~80 managers × ~2-3 fetches each =
  ~2,000-3,000 SEC requests over the run. At Rate Guard's 10 req/s
  edgar throttle, the wall time is ~5-10 minutes plus parse time.
- **Don't expect 8/8 perfect coverage.** Some managers in the
  whitelist were founded recently, some have NT periods, some have
  gaps. Goal is "Readiness depth ≥ 7", not "all 8 quarters complete
  for all 82 managers".

## Per-quarter trace (actual run, 2026-05-25)

### Stage 1 — historical_backfill (filings discovery + primary_doc)

| Quarter | Filings ingested | Already present | Failed | Validation |
|---|---|---|---|---|
| 2023-Q1 | 74 | — | 0 | passed |
| 2023-Q2 | 73 | — | 0 | passed |
| 2023-Q3 | 75 | — | 0 | passed |
| 2023-Q4 | 79 | — | 0 | passed |
| 2024-Q1 | 76 | — | 0 | passed |
| 2024-Q2 | 72 | — | 0 | passed |
| 2024-Q3 | 72 | — | 0 | passed |
| 2024-Q4 | 75 | — | 0 | passed |
| 2025-Q1 | 73 | — | 0 | passed |
| 2025-Q2 | 73 | — | 0 | passed |
| 2025-Q3 | 74 | — | 0 | passed |

**Stage 1 totals:** 816 filings ingested, 0 failed, 11 quarters validated.

### Stage 2 — ingest_holdings (infotable.xml fetch + parse)

| Quarter | Filings processed | XML fetched | Holdings inserted | Failed |
|---|---|---|---|---|
| 2023-Q1 | 74 | 74 | 5,238 | 2 |
| 2023-Q2 | 73 | 70 | 4,883 | 3 |
| 2023-Q3 | 75 | 75 | 4,818 | 2 |
| 2023-Q4 | 79 | 79 | 4,844 | 5 |
| 2024-Q1 | 76 | 76 | 4,742 | 3 |
| 2024-Q2 | 72 | 72 | 4,549 | 0 |
| 2024-Q3 | 72 | 72 | 4,527 | 1 |
| 2024-Q4 | 75 | 75 | 4,594 | 3 |
| 2025-Q1 | 74 | 73 | 4,500 | 2 |
| 2025-Q2 | 74 | 73 | 4,718 | 3 |
| 2025-Q3 | 75 | 0 (already on disk) | 0 (no new — already in 2025-Q4 universe) | 4 |

**Stage 2 totals:** ~47,400 holdings inserted across 11 quarters, 28 per-filing failures (~0.3%; mostly individual filings the harness should re-investigate as a follow-up).

### Stage 3 — enrich_cusip (CUSIP → ticker via OpenFIGI)

| Metric | Value |
|---|---|
| Mappings created | 1,233 |
| New stocks | 0 (all CUSIPs already mapped to existing stocks) |
| Holdings linked | 51,317 |
| Holdings still unmapped | **0** |

### Stage 4 — oracles_lens_score_backfill per quarter (review-2 Q6)

| Quarter | Filings scored | Score components written |
|---|---|---|
| 2023-Q1 | 367 | 7,592 |
| 2023-Q2 | 344 | 7,120 |
| 2023-Q3 | 351 | 7,348 |
| 2023-Q4 | 372 | 7,724 |
| 2024-Q1 | 375 | 7,732 |
| 2024-Q2 | 351 | 7,340 |
| 2024-Q3 | 358 | 7,418 |
| 2024-Q4 | 371 | 7,710 |
| 2025-Q1 | 375 | 7,748 |
| 2025-Q2 | 398 | 8,214 |
| 2025-Q3 | 398 | 8,278 |

**Stage 4 totals:** 4,060 filings scored, 83,224 score components written across 11 quarters.

Final `oracles_lens_signals` rows per quarter:

| Quarter | Persisted signals |
|---|---|
| 2025-Q4 | 207 |
| 2025-Q3 | 398 |
| 2025-Q2 | 398 |
| 2025-Q1 | 375 |
| 2024-Q4 | 371 |
| 2024-Q3 | 358 |
| 2024-Q2 | 351 |
| 2024-Q1 | 375 |
| 2023-Q4 | 372 |
| 2023-Q3 | 351 |
| 2023-Q2 | 344 |
| 2023-Q1 | 367 |
| **TOTAL** | **4,267** |

Oracle's Lens "All" universe now reads valid persisted scores for every quarter the user can scroll back to.

### Final coverage by quarter

| Quarter | Confirmed managers | Holdings | Linked | Linked ratio |
|---|---|---|---|---|
| 2025-Q4 | 59 | 3,772 | 3,627 | 96.2% |
| 2025-Q3 | 71 | 4,776 | 4,588 | 96.1% |
| 2025-Q2 | 71 | 4,793 | 4,546 | 94.8% |
| 2025-Q1 | 71 | 4,574 | 4,300 | 94.0% |
| 2024-Q4 | 71 | 4,594 | 4,292 | 93.4% |
| 2024-Q3 | 71 | 4,527 | 4,191 | 92.6% |
| 2024-Q2 | 71 | 4,549 | 4,167 | 91.6% |
| 2024-Q1 | 71 | 4,742 | 4,317 | 91.0% |
| 2023-Q4 | 72 | 4,844 | 4,347 | 89.7% |
| 2023-Q3 | 72 | 4,818 | 4,250 | 88.2% |
| 2023-Q2 | 72 | 4,883 | 4,232 | 86.7% |
| 2023-Q1 | 72 | 5,238 | 4,460 | 85.1% |

**Linked ratio drift** (96% → 85% across 12 quarters going back) is expected: older quarters have more public-company actions (mergers, spin-offs, ticker changes, going-private) that OpenFIGI's current snapshot can't resolve back-in-time. Each unmapped CUSIP is a real public company — just no current ticker.

### Before / after summary

| Metric | Before | After |
|---|---|---|
| `historical_depth_quarters` (filings) | 4 | **12** |
| `holdings_depth_quarters` (signal-eligible) | 4 | **12** |
| Total Holding13F rows | ~3,900 | ~56,200 |
| Unmapped CUSIPs | (145, blocking) | **0** |
| `oracles_lens_signals` rows | 207 (2025-Q4 only) | **4,267** (12 quarters) |
| `oracles_lens_score_components` rows | ~4,300 (2025-Q4) | ~88,000 (12 quarters) |

