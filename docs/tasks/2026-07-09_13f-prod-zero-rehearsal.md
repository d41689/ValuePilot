# 13F prod-topology zero rehearsal — M2 + the three switches

Date: 2026-07-09 / 2026-07-10
Branch: `claude/13f-prod-zero-rehearsal`
Status: implementation + rehearsal complete; awaiting review

## Goal

Stand up the **prod topology** locally against a **brand-new, empty database**,
turn on the three 13F switches, let the system seed its manager universe and
ingest 13F data through Rate Guard with **no human step**, then verify that every
13F artefact it produced is correct — and fix what is not.

This is the Data Gate the release checklist demands, run against Branch A (prod
has no 13F data) instead of guessing at it.

## Acceptance criteria

- [x] Fresh database, migrated from zero by the prod container command.
- [x] Managers seeded automatically at boot (M2), not by a CLI step.
- [x] `EDGAR_SCHEDULER_ENABLED`, `THIRTEENF_JOB_WORKER_ENABLED`,
      `THIRTEENF_START_QUARTER` all on; pipeline runs unattended.
- [x] Holdings fetched live through Rate Guard.
- [x] Every 13F invariant verified against the resulting data.
- [x] Every real defect found is fixed, test-first, and re-verified on real data.
- [x] Canonical CI green.

## Scope

**In:** the deploy-time manager seed (M2); the `quarterly_pipeline` stage
contract; the enrichment stage's convergence; verification of the resulting data.

**Out:** turning the switches on in real prod (that is M5, and it needs the
`13f-data-v1` Data Gate first); `dataroma_sync` scheduling (M3); the unified
problem view (M4).

## The sandbox

Its own compose project (`valuepilot-prodsim`), its own database
(`valuepilot_prodsim` on the shared Postgres), its own `edgar_raw` volume, its
own port. It never touches `valuepilot`, `valuepilot_prod`, or `valuepilot_test`.

    THIRTEENF_START_QUARTER=2025-Q4      # two quarters: 2025-Q4 and 2026-Q1
    MANAGER_SEED_ON_STARTUP=true
    EDGAR_SCHEDULER_ENABLED=true
    THIRTEENF_JOB_WORKER_ENABLED=true
    EDGAR_FETCH_MODE=live                # through Rate Guard

## What the rehearsal produced, before any fix

    managers seeded            82  (all confirmed → status=active)
    quarterly_pipeline runs     2  (2025-Q4 succeeded, 2026-Q1 partial_success)
    filings                   148
    holdings                 5023
    ownership_changes           0
    oracles_lens_signals        0     ← the product surface is empty

Thirteen of fourteen jobs were green. Both invariants a reviewer would check
(`dup_active_groups`, `holdings_null_parse_run`) were zero. The database looked
healthy and the product had nothing to show.

## D1 (P1) — the pipeline's two stages disagreed about what `quarter` means

`ingest_quarter_index(Q)` treats `Q` as a **report quarter**. A 13F for period Q
is filed within 45 days after Q ends, so it deliberately downloads the form.idx
of `next_quarter_label(Q)`.

`_execute_ingest_job`'s `ingest_holdings` branch windowed on
`Filing13F.period_of_report`. For an **un-ingested** filing that column is only a
**proxy** equal to `filed_at`; `backfill_period_routing` overwrites it with the
true period at parse time. So the rows the index stage had just inserted carried
a proxy period of Q+1 and sat outside the window `Q`.

Observed, from zero:

| job | result |
|---|---|
| `fetch_quarter_index:2025-Q4` | 75 filings inserted |
| `ingest_holdings:2025-Q4` | **0 processed, 7 ms, "succeeded"** |
| `quality_check` / `compute_ownership_changes` / `oracles_lens_score_backfill` for 2025-Q4 | ran on an empty quarter |
| `fetch_quarter_index:2026-Q1` | 73 filings inserted |
| `ingest_holdings:2026-Q1` | 75 processed — **the 2025-Q4 batch** |

Two consequences:

1. **No pipeline run ever both ingests and scores its own quarter.** Scoring
   happens one pipeline too early. The sandbox only produced signals because a
   container restart re-enqueued the quarter (`reconcile_start_quarter_coverage`
   skips quarters that already have Lens signals, and 2025-Q4 had none).
2. **The newest report quarter is unreachable.** 2026-Q1's filings are filed in
   2026-Q2, so only an `ingest_holdings(2026-Q2)` would match them — and
   `latest_scoreable_quarter()` will not enqueue a 2026-Q2 pipeline until
   mid-August. 73 filings sat `pending` with no path forward.

This is **F5**, the defect T4 fixed in the CLI `backfill` path
(`scoped = {q} ∪ {next_quarter_label(q)}`), alive in the automated pipeline. The
CLI fix never propagated to the job.

**Fix** — `_ingest_candidate_filings(session, quarter)`, a named helper next to
`quarter_window`, selects two disjoint arms:

* parsed rows by the **report-quarter** window (the heal / re-run path);
* un-ingested rows (`raw_infotable_doc_id IS NULL`) by the **filed-quarter**
  window `Q+1` (the rows the index stage just inserted).

The `raw_infotable_doc_id IS NULL` guard keeps the arms disjoint, so a parsed
2025-Q4 filing is never reclaimed by `ingest(2026-Q1)`.

## D2 (P2) — a pipeline that ingested nothing still reported green

No per-stage status could catch D1: `ingest_holdings` legitimately returns
`succeeded` when its query matches nothing. Only the *pair* is diagnostic —
75 filings inserted, 0 processed.

**Fix** — a cross-stage invariant in `quarterly_pipeline`: if the index stage
inserted filings and the ingest stage processed none, record `pipeline_warning`
and downgrade the run to `partial_success`. An idempotent re-run (0 inserted,
0 processed) stays green.

## D3 (P1) — the automated enrichment never converged

Two entry points into CUSIP → ticker → `stock_id`, and only one converged:

| entry point | implementation |
|---|---|
| `enrich_cusip` job (admin / CLI) | `enrich_all_unmapped_holdings` — loops until no enrichable holding remains |
| `enrich_metadata` stage (pipeline) | `enrich_cusips_from_openfigi` — **one batch of 100** |

So the manual path converged and the automated path did not. Against real data:
2084 distinct CUSIPs across 10707 holdings; after five `enrich_metadata` runs
only **363** CUSIPs were mapped, each run adding ~90-100 and stopping.

`stock_id` is the join key for the Watchlist × 13F columns, the stock-detail
drawer, and Oracle's Lens eligibility (`_eligible_stock_ids`). An unlinked
holding is invisible to all of them — **"unknown" silently rendered as absent**.

**Fix** — the pipeline stage calls `enrich_all_unmapped_holdings`, the same
converging loop the standalone job has always used. It already bootstraps stocks
and backfills `stock_id` after its loop, is resumable, and is bounded by
`max_batches`. The summary now also carries `batches_run` and
`holdings_still_unmapped`, because leftovers are a finding, not a log line.

## Verified on real data, after the fixes

|  | before | after |
|---|---|---|
| pending filings | 73 | **0** |
| holdings | 5023 | **10707** |
| holdings with `stock_id` | 3907 (36.5%) | **10180 (95.1%)** |
| CUSIPs mapped | 363 / 2084 | **2082 / 2084** |
| `oracles_lens_signals` | 309 | **859** |
| `ownership_changes` | 4207 | 8464 (two quarters) |

The remaining 527 unlinked holdings are `needs_review` (504, the human
adjudication queue, excluded from the enrichable pool by design), `unresolved`
(21) and `invalid_cusip` (2) — 4.9%, consistent with the ~10% README figure.

Every invariant holds:

    dup_active_groups          0        groups with 0 active filings   0
    holdings_null_parse_run    0        groups with >1 active filing   0
    accepted_at_null           0        holdings_orphan_run            0
    frozen_sort_warnings       0        attr_misattributed             0
    filings_pending            0        managers_zero_direct           0
    deferred                   0

`amendments_pending = 1` is **correct**: a `NEW_HOLDINGS` 13F-HR/A whose original
remains active, awaiting human adjudication — exactly the T1-FU design, and not
frozen (`amendment_sort_warning = false`).

## Not a defect

`fetch_daily_index` failed once with a `richmom.vip | 502: Bad gateway` HTML
page. That is the **Rate Guard tunnel**, not SEC and not the parser. Non-404
failures are correctly classified `failed` and retried
(`THIRTEENF_DAILY_SYNC_MAX_ATTEMPTS = 3`). Two observability nits are backlogged.

## M2 — deploy-time manager seeding

The three prerequisites the M1 PR named are now answered:

1. **Transaction boundary** — `run_startup_manager_seed(session_factory)` opens
   the session, lets the seed take its `pg_advisory_xact_lock`, commits on
   success, rolls back and re-raises on failure.
2. **A bad seed file blocks the deploy.** Not wrapped in `try/except`, unlike the
   neighbouring start-quarter reconcile — that reconcile is idempotent and
   retried next boot, whereas an API on an empty manager universe ingests nothing
   and scores nothing, silently. A missing / empty seed file is refused too
   (`seed_confirmed_managers` merely warns and returns an empty report).
   `test_the_curated_seed_file_is_valid` keeps a malformed file out of the image,
   so failing loud cannot crash-loop prod on anything CI could have caught.
3. **A universe change is a scoring event.** Creating managers on a database that
   already holds 13F data logs a WARNING naming the created CIKs and stating that
   `ownership_changes` / Lens signals / readiness are now stale. Nothing is
   recomputed automatically. Day 0 (no holdings yet) is not a universe change.

`MANAGER_SEED_ON_STARTUP` defaults **off**, so dev and test boots never write to
`institution_managers`. Verified idempotent on the sandbox: a restart re-ran the
seed with `created = 0`, `updated = 82`, and 82 managers still present.

## Test plan (all green)

    docker compose exec -T api alembic upgrade head
    docker compose exec -T -e DATABASE_URL=...valuepilot_test api pytest -q      # 1200 passed
    docker compose exec -T web sh -lc 'node --test lib/*.test.js'                # 175 pass
    docker compose exec -T web npm run lint                                      # clean
    docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'        # green

New tests:

* `tests/unit/test_13f_manager_seed_startup.py` (11) — boundary, fail-loud,
  universe-change warning, idempotency, the curated-file guard.
* `tests/unit/test_13f_pipeline_quarter_window.py` (8) — the proxy-period
  premise, both selection arms, disjointness, newest-quarter reachability, and
  the green-on-zero guard.
* `tests/unit/test_13f_pipeline_enrichment_convergence.py` (3) — the stage must
  delegate to the converging loop; summary keys preserved; leftovers reported.

## Follow-ups

Recorded in `docs/BACKLOG.md`: the misleading `new_stocks` counter, the HTML
error page stored in `JobRun.summary_json`, and M5's dependency on this fix.
