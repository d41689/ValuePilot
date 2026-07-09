# Review results — T1–T4 13F stabilization series

**Review date:** 2026-07-09  
**Scope:** merged series `a786cfb..47bf92a` on `main`, per
`2026-07-09_13f-t1-t4-series-review-prompts.md`.  
**Verdict:** changes are mostly coherent, but I found two cross-ticket
correctness issues and two ops/docs gaps. The stale `ownership_changes` issue is
the one I would treat as merge-blocking for the series sign-off.

## Findings

### [P1] Active-filing freezes can leave stale ownership changes serving as current data

**Files:** `backend/app/services/thirteenf_admin_dashboard.py:3135`,
`backend/app/services/thirteenf_admin_dashboard.py:3138`,
`backend/app/services/thirteenf_ownership_changes.py:83`,
`backend/app/services/thirteenf_user_api.py:302`

T1-FU intentionally allows a manager-period to have **no active filing**:
`original_tie`, `none_eligible`, or missing-acceptance with no current active.
T2's quarter stage, however, only enumerates managers that currently have an
active HR-family filing:

```text
filings_13f.report_quarter == quarter
form_type in HR_FORM_TYPES
is_active_for_manager_period = true
```

That means a manager that used to have an active filing and already has
`ownership_changes` rows, then later loses the active filing due to an authority
freeze, is never passed to
`compute_ownership_changes_for_manager_quarter`. The delete-at-start logic in
that function never runs, so the old rows remain. The manager changes API then
picks the latest row from `ownership_changes` without checking the current
active filing state, so the end user sees stale changes as available instead of
"unknown / no active filing".

Rollback-only reproduction in `valuepilot_test`:

```text
{'before': 1, 'after': 1,
 'result': {'quarter': '2099-Q1', 'managers_processed': 0,
            'rows_created': 0, 'status': 'succeeded'}}
```

Wrong product result: a disputed/frozen period can keep showing old buy/sell
activity, violating the "unknown is not zero" doctrine. The stage also reports
`succeeded`, so operators get no signal that materialized changes were skipped
for a now-unavailable manager-period.

Required fix: make the quarter compute stage include managers with existing
`ownership_changes` rows for that quarter in addition to active HR managers, and
let the per-manager compute delete or replace them with an explicit unavailable
record/reason. The API should not render rows for a quarter whose current active
filing is absent/disputed unless the row itself records that unavailable state.

### [P1] Failed reparse has a committed no-current-ParseRun window, and a crash can make it permanent

**Files:** `backend/app/services/thirteenf_holdings_ingest.py:392`,
`backend/app/services/thirteenf_holdings_ingest.py:402`,
`backend/app/services/thirteenf_holdings_ingest.py:320`,
`backend/app/services/thirteenf_holdings_ingest.py:326`,
`backend/app/services/thirteenf_holdings_ingest.py:410`

T4 correctly routes CLI `reparse-filing` / `reparse-all` through
`reparse_accession`, and `active_hr_holdings_query` correctly joins both the
active filing and the current ParseRun. The failure path still has a transaction
split:

1. `reparse_accession` demotes the old current ParseRun and flushes.
2. `_do_ingest_holdings` fails, writes a failed ParseRun audit record, and
   commits.
3. Control returns to `reparse_accession`, which restores the old current run
   and commits again.

During the committed gap between steps 2 and 3, product queries can observe an
active filing with **no current ParseRun**, so holdings disappear. If the
process crashes or is killed after the failed-audit commit and before restore,
the product-invisible state persists until manual repair.

Wrong product result: a failed `reparse-all` can briefly, or after a crash
permanently, blank out holdings for an otherwise valid active filing. This is
exactly the class T4 intended to remove from CLI reparse workflows.

Required fix: do not commit the failed audit while the old current run is
demoted. Either write the failed audit and restore the old current run in the
same outer transaction, or create the failed run without first demoting the old
current run. Add a crash-window regression by asserting no committed state ever
has zero current succeeded ParseRuns for an accession that had a prior good run.

### [P2] Production deploy needs an explicit accepted_at backfill before any sweep/reparse/admin authority path

**Files:** `backend/app/services/edgar_ingestion.py:1295`,
`backend/app/services/thirteenf_admin_dashboard.py:3540`,
`backend/app/services/thirteenf_admin_dashboard.py:3658`,
`backend/scripts/t3_attribution_rollout.py:3`

The quarterly ingest job is ordered correctly: Phase 2
`backfill_period_routing` fills `accepted_at` before Phase 5 sweeps active
filings. That makes a normal quarter job safe for the quarter it processes.

The deployment story is still incomplete for existing production data. Before
T1-FU, bulk-ingested filings can have `accepted_at IS NULL`. Any path that calls
`apply_active_filing_policy` for an old group before a global accepted-at
backfill can now hit the missing-acceptance rule and flag/freeze a group that a
later routing pass would heal. Paths include admin resolve, controlled reparse,
CLI `reparse-all`, and any manual/queued `ingest_holdings` for old quarters.

Verdict on Prompt 1 item 4: plain deploy plus "next scheduled quarter job"
converges only the quarters that job touches. It does not prove historical
groups are safe before admin/reparse/sweep-bearing paths run.

Required production order:

1. Deploy code.
2. Run a one-time global `backfill_period_routing` / accepted-at backfill over
   stored primary docs and verify `accepted_at NULL = 0`.
3. Run the active-filing sweep or the first ingest jobs only after step 2.
4. Run T3 attribution rollout / changes / Lens recompute after authority data is
   clean.

### [P2] Backlog entry for NT/A is stale and overstates unfixed consumer risk

**File:** `docs/BACKLOG.md:7`

The open backlog item says "`13F-NT/A` is not ingested and NT-family consumers
only recognize exact `13F-NT`". The first half is still true: automated NT/A
ingestion is deliberately deferred. The second half is no longer true in the
current code: `NT_FORM_TYPES = ("13F-NT", "13F-NT/A")` is used by
`thirteenf_user_api`, `thirteenf_ownership_changes`, `oracles_lens/base_primitives`,
`thirteenf_filing_detail`, and `nt_only_manager_ids`.

This is not a runtime bug, but it breaks the backlog's deferral contract: a
reviewer now cannot tell whether the remaining work is "ingest NT/A" or "fix
consumer semantics". Update the entry to keep only the ingestion/authority scope
that remains open.

## Cross-Prompt Answers

**Lock layering:** I did not find a JobRun-lock/advisory-lock deadlock cycle in
the merged paths. JobRun locks are claimed and committed before job bodies take
period locks; admin resolve takes only the period lock; the Phase 5 sweep sorts
groups and commits per group. Phase 3 per-filing reparse can take period locks
in filing order, but it does not hold multiple period locks at once because
`_do_ingest_holdings` commits per filing.

**Activation x attribution x Lens:** The intended pending-amendment machinery is
present: active filings with `amendments_pending` are excluded from Lens
aggregate contributions and caveats flow to the signal. DFND/OTR now map to
`direct`, and `active_hr_holdings_query` filters HR/HR-A + active + current
ParseRun, so I did not find an NT/non-direct leak into consensus.

**PO acceptance spot-check on dev:** current dev is healthy on the invariants
but the prompt's sample numbers are stale. Read-only checks showed 373 filings,
355 manager-period groups, 354 active filings, 0 duplicate active groups,
25,070 current-ParseRun holdings, 373/373 `accepted_at`, and 0 sort warnings.
The seven flagship managers are visible with direct holdings / changes / Lens
components:

```text
Berkshire 3984: 539 holdings, 210 changes, 278 components
Cantillon 3988: 375 holdings, 191 changes, 332 components
Egerton 3998: 123 holdings, 148 changes, 214 components
Engaged 3999: 42 holdings, 46 changes, 20 components
Fairfax 4000: 144 holdings, 154 changes, 154 components
Oaktree 4028: 832 holdings, 830 changes, 102 components
Scion 4037: 30 holdings, 50 changes, 14 components
```

`investment_discretion IN ('SOLE','DFND','OTR') AND status != direct` returned
0 rows; legacy `reported_for_other/shared` returned none. Berkshire counted as
one holder per stock/quarter in the checked direct-holder grouping.

**Deliberate decisions:** I accept all seven listed decisions as product/ops
positions, with one deployment caveat: decision 4 (`merge_accepted_at` overwrite)
is acceptable only because the current source is the same stored primary doc;
introducing a second source should add conflict review. Decision 7 (NT/A not in
ingestion whitelist) is acceptable only if the backlog entry is narrowed as
above.

**Three highest-value missing tests:**

1. End-to-end quarterly pipeline with real stage bodies: ingest/routing,
   authority sweep, quality, ownership changes, and Lens scoring on a
   multi-manager/multi-quarter fixture. Existing tests mostly stub the pipeline
   stage bodies.
2. Authority freeze followed by `compute_ownership_changes` stage: seed stale
   change rows, remove/freeze the active filing, run the quarter stage, and
   assert stale rows are cleared or replaced with explicit unavailable state.
3. Failed reparse crash-window invariant: simulate failure after old current run
   demotion and assert no committed state can leave an accession with prior good
   holdings but no current succeeded ParseRun.

**Useful third guard:** add a source guard for direct `Holding13F` product
queries outside sanctioned low-level modules. Today several services must query
`Holding13F` directly for scoring/admin internals, so the guard should whitelist
`thirteenf_holdings_query`, ownership-change/scoring internals, and admin
diagnostics, but fail user/API surfaces that bypass `active_hr_holdings_query`.

**Observability:** authority freezes surface through `amendment_sort_warning`,
`amendments_pending`, admin pending queues, readiness/health counts, and Lens
caveats when the kept active filing is non-terminal. `deferred` intentionally
does not block health counts. The remaining observability gap is the stale
changes finding above: a manager skipped by the compute stage produces no warning
and may leave old rows visible.

## Verification Performed

I did not run the full canonical CI gates for this review. Commands performed:

- Read-only dev SQL checks through the API container.
- Rollback-only `valuepilot_test` reproduction for stale ownership changes after
  no-active manager selection.
- Static review of the five ticket docs, review-result docs, backlog, and the
  entry-point code named in the prompt.
