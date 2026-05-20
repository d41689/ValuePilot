# 13F Pipeline Hardening PR #56 Re-Review Results

Reviewed worktree: `.claude/worktrees/optimistic-hofstadter-630d85`

Reviewed commit: `26591b6 Address external review of PRs #45-#55: pipeline txn boundaries + safety`

## Summary

PR #56 materially improves the riskiest parts of the pipeline. The explicit phase commit barriers, per-filing savepoints in Phase 1, fail-loud routing behavior, routing-degradation status, and CUSIP NULL-quarter guard are all directionally correct.

I found one should-fix regression risk before merge: `_has_meaningful_coverage()` now treats any succeeded `oracles_lens_score_backfill` job as terminal. That can freeze an incomplete quarter if scoring succeeded with zero signals because upstream data was missing, managers were not seeded yet, routing/activation was partial, or enrichment had not linked holdings. This reintroduces the same class of "intermediate/insufficient success means reconcile will never self-heal" bug the earlier review was trying to avoid.

## Findings

### P1 - Succeeded zero-signal scoring job can make reconcile skip an incomplete quarter forever

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_start_quarter.py:143`

`_has_meaningful_coverage()` now returns true if either an `OraclesLensSignal` row exists or any `JobRun` with lock key `oracles_lens_score:<quarter>:%` has `status == "succeeded"`. This fixes the legitimate "zero eligible stocks" case, but it also makes a zero-output scoring job terminal even when upstream work was incomplete.

Concrete failure modes:

- If `quarterly_pipeline` runs before managers are seeded, `fetch_quarter_index` can find no filings, scoring can succeed with `filings_scored=0`, and the quarter will be skipped forever after managers are later added.
- If `ingest_holdings` returns `partial_success` due routing degradation but the pipeline continues to stage 5, scoring can succeed with zero or partial signals; reconcile will skip because the scoring stage succeeded.
- If CUSIP enrichment/linking is temporarily weak and scoring produces zero eligible stocks, the job status still marks the quarter covered even though a later enrichment fix should cause a re-run.

This is a variant of the previous bug: using a job status as terminal proof without validating the data state behind it.

Recommendation: do not use a bare succeeded scoring job as coverage. Add an explicit terminal marker with reason and prerequisites, for example:

- `oracles_lens_score_backfill` summary has `filings_scored == 0` only counts as terminal when upstream coverage is known complete: active routed filings exist for the quarter, ingest stage succeeded cleanly, and scoring evaluated a nonzero eligible universe or records `zero_eligible_stocks_confirmed`.
- Or add a persisted `quarter_pipeline_completions` / coverage table keyed by quarter and score version with fields for `indexed_filings`, `active_filings`, `linked_holdings`, `scoring_completed`, and `zero_signal_reason`.
- At minimum, require the parent `quarterly_pipeline` job to have `status == "succeeded"` and the scoring summary to indicate upstream data was present, not just the scoring stage status.

### P2 - Phase 3 still uses full rollback on per-filing parse errors and can lose failed-parse audit rows

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_admin_dashboard.py:3232`

PR #56 fixed the major earlier-phase rollback problem by committing Phase 1 and Phase 2 before parsing. But Phase 3 still catches non-programming parse/load exceptions and calls `session.rollback()` at line 3246. `ingest_if_needed()` delegates to `_do_ingest_holdings()`, whose failure path writes a failed `ParseRun13F` in a nested transaction and then re-raises; the outer `session.rollback()` can roll that failed audit record back. This does not undo Phases 1-2 anymore, but it weakens parse-run auditability.

Recommendation: wrap each Phase 3 filing in its own `session.begin_nested()` at the caller level, or adjust `_do_ingest_holdings()` so failed parse-run audit records are committed/persisted independently before re-raise. Add a test that a bad infotable leaves a failed parse run after `ingest_holdings` returns `partial_success`.

### P2 - Phase 4 solo activation is safer for amendments but still bypasses the shared active-filing policy

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_admin_dashboard.py:3297`

The new `group_counts == 1` guard closes the biggest HR/A corruption risk from the previous blanket `is_latest` mirror. However, the update still sets `is_active_for_manager_period=True` directly for any solo filing with a `quarter_end_date`, without using `_apply_amendment_policy()` or checking parse status, coverage type, or whether the form is a holdings report. That may be acceptable as a short-term repair for old rows, but it is still a bypass around the canonical active-filing policy.

Recommendation: if kept, narrow this repair to original, non-amendment filings with successful/usable routing and an allowed coverage type. Longer term, replace it with a shared active-filing reconciliation function and add regression tests for solo HR, solo NT, original HR + non-restatement HR/A, original HR + restatement HR/A, and tie cases.

### P3 - Routing warning persistence is improved, but stale warnings are not cleared on clean reroute

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/edgar_ingestion.py:1008`

`backfill_period_routing()` now stamps `parse_warning` / `parse_error` for degraded routing. On a later clean routing result, it does not clear old `parse_warning` or `parse_error` values. A filing that was previously `needs_review` could remain visually degraded after the source XML or parser behavior is corrected.

Recommendation: when `routing.parse_status == "pending"` or equivalent success, clear stale period-routing warnings/errors that were set by this routing path, or namespace the warning/error so unrelated parse errors are not accidentally cleared.

## Confirmed Improvements

- R1-P1 transaction boundary: Phase 1 and Phase 2 now commit explicitly, so later per-filing errors no longer roll back XML links or routing writes from those phases.
- R1/R4 fail-loud routing: the broad Phase 2 swallow is gone. A routing import/API programming error now fails the stage.
- R2-P1 amendment heuristic: the previous blanket `is_latest_for_period` mirror is gone; multi-filing groups are no longer activated by Phase 4.
- R2-P1 routing degradation: `needs_review` / `failed` counts now surface in the ingest job summary and mark the job `partial_success`.
- R2-P2 CUSIP NULL-quarter guard: enrichment now leaves NULL-quarter holdings pending rather than linking without temporal validity.
- Tests: the new tests cover programming-error propagation, data-error tolerance, routing degradation status, latest scoreable quarter, and zero-signal job terminal behavior. The remaining test gap is integration coverage for true transaction/audit behavior and amendment policy.

## Deferred Items Still Valid

- Scoring internal commit split-brain window remains real but narrow.
- Moving persistent storage out of the CI workspace remains the right infra end state.
- `FOR UPDATE`/concurrency hardening for period routing remains a follow-up.
- Full transaction-integration and amendment-regression tests are still needed.

## Recommendation

I would ask for one more PR #56 fix before merge: replace the bare "succeeded scoring job means coverage" shortcut with a terminal marker or stricter data-state predicate. The other items can be tracked as follow-ups if the team accepts the residual risk.

