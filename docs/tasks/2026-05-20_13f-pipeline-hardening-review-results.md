# 13F Pipeline Hardening Review Results

Source prompt: `.claude/worktrees/optimistic-hofstadter-630d85/docs/tasks/2026-05-19_13f-pipeline-hardening-review-prompts.md`

Reviewed code from worktree: `.claude/worktrees/optimistic-hofstadter-630d85`

## Executive Summary

The 13F pipeline now reaches the product-level goal, but I would not start the OpenFIGI throughput work until at least the P1s below are addressed or explicitly accepted. The highest-risk issues are:

- `_execute_ingest_job` has ambiguous and sometimes unsafe transaction boundaries: loop-level `session.rollback()` can discard earlier phase work that has only been flushed, while `ingest_if_needed()` can unexpectedly commit prior phase writes.
- The Phase 4 `is_active_for_manager_period = is_latest_for_period` healing heuristic is not safe for real amendment cases and can activate the wrong HR/A filing.
- Period routing can surface `needs_review` / `failed` routing outcomes without persisting parse status/warning/error, so bad periods can be silent.
- `clean: false` keeps prod alive for now, but persistent EDGAR data should move out of the CI workspace.

I did not make production code changes and did not run tests.

## Review 1 - Pipeline & Job-Orchestration Correctness

### P1 - Loop rollbacks in `_execute_ingest_job` can discard prior phase work and leave summaries lying

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_admin_dashboard.py:3178`

Phase 1 calls `ensure_filing_infotable_doc()` for each filing and only `flush()`es at line 3194. A failure later in the Phase 1 loop calls `session.rollback()` at line 3192, which rolls back all previously flushed but uncommitted XML-link writes in that transaction. Phase 2 has the same shape: `backfill_period_routing()` writes period routing, then its broad handler rolls back the whole transaction at lines 3204-3207. If Phase 3 reaches `ingest_if_needed()`, `_do_ingest_holdings()` currently calls `session.commit()` internally at `thirteenf_holdings_ingest.py:225`, so the first successful parse commits not only that filing but also all pending Phase 1/2 work. That makes the boundary dependent on whether at least one filing parses successfully.

Concrete answer to the prompt's transaction question: yes, a mid-loop `session.rollback()` can lose earlier phase work when that work has only been flushed. Once `_do_ingest_holdings()` commits, later rollbacks will not lose already committed Phase 1/2/3 work, but relying on a nested helper to commit the outer job's pending state is fragile and surprising. The counters (`xml_fetched`, `routing_summary`, `total_holdings`) can also report work that was rolled back.

Recommendation: choose one explicit boundary. Prefer per-filing SAVEPOINTs for Phase 1/3 and a committed barrier after Phase 2, or split the four phases into distinct stage jobs with commits between phases. Also remove the internal `session.commit()` from `_do_ingest_holdings()` when called under a job-owned transaction, or make that commit behavior explicit via a wrapper.

### P1 - Phase 2 swallows programming errors and lets the stage continue as success/partial success

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_admin_dashboard.py:3201`

`backfill_period_routing()` is wrapped in `except Exception`, logs a warning, rolls back, and continues to holdings parsing. This is the exact shape that let the `route_period` import bug reach prod. ImportError, AttributeError, TypeError, and API contract breaks are programming errors; treating them like a filing-level recoverable parse miss can produce "succeeded but zero useful work" states again.

Recommendation: make routing a hard prerequisite for `ingest_holdings` unless the exception is a known per-document load/parse error already handled inside `backfill_period_routing()`. Let module import/API errors fail the stage. At minimum, catch a narrow custom exception and add a test that monkeypatches `backfill_period_routing` to raise `ImportError` and asserts the stage fails.

### P2 - Scoring commits internally, outside the stage job's lifecycle update

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/oracles_lens/signal_weighted_score.py:383`

`compute_signal_weighted_scores()` commits its own writes, then `_execute_pipeline_stage_job()` marks the stage `succeeded` and commits at `thirteenf_admin_dashboard.py:3078-3086`. If the score commit succeeds but the stage job update fails, persisted scores exist while the stage job can remain failed/running. If scoring raises before line 383, `_execute_pipeline_stage_job()` rolls back and stages 1-4 remain committed because they are separate stage jobs, so scoring failure correctly results in `partial_success` without undoing earlier stages. The problem is the split-brain window after the scoring commit and before stage-job completion.

Recommendation: refactor scoring to support `commit=False` for job execution, or have the dispatcher own the commit. Keep standalone CLI/admin callers free to commit explicitly.

### P2 - `ensure_filing_infotable_doc()` self-heal mostly works, but forces both primary and infotable refetch when either file is missing

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/edgar_ingestion.py:609`

The helper now correctly short-circuits when both linked files exist, refetches when a linked body file is gone, and returns `None` when the manager lacks CIK. Calling it unconditionally from `_execute_ingest_job` costs one DB lookup and two `stat()` calls on cache hits, which is acceptable. The only inefficiency is that if either primary or infotable is missing, `force_refresh=True` refetches both documents.

Recommendation: acceptable for now. If EDGAR volume grows, split primary and infotable refresh decisions to avoid unnecessary network requests.

### P3 - `route_period` import is fixed at the reviewed call site

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/edgar_ingestion.py:959`

The reviewed code imports `route_period`, not `_route_period`, and `rg` did not find remaining `_route_period` references. This part is fixed.

## Review 2 - Data-Healing & Data-Contract Safety

### P1 - `is_active_for_manager_period = is_latest_for_period` is unsafe for real amendments

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_admin_dashboard.py:3259`

The bulk update mirrors `is_latest_for_period` into `is_active_for_manager_period` for all `13F-HR` and `13F-HR/A` filings in the quarter. That works for the observed no-real-amendment universe, but it conflicts with the amendment policy in `thirteenf_filing_detail.py:344-403`: amendments start inactive, non-restatement amendments should remain inactive/pending, and only RESTATEMENT amendments become active after successful parse. The bulk heuristic can activate a later `13F-HR/A` simply because `_recalculate_version_ranks()` made it latest by filed date/accession, even when it is not a restatement. The unique partial index at `models/institutions.py:395-402` prevents two active rows per manager/quarter, but it does not prevent the wrong row from being active.

Recommendation: do not keep this heuristic as the long-term contract. Move active-filing selection into a single policy function shared by accession ingest, quarterly ingest, and reparses. It should account for `is_amendment`, `amendment_type`, parse success, sort ties, and pending/failed amendment status. For existing rows, run an explicit data repair using that policy, not a blanket `is_latest` mirror.

### P1 - Phase 4 healing is useful as a repair, but the proper end state is to populate columns in the ingest path

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_admin_dashboard.py:3226`

The bulk `UPDATE`s for `Holding13F.quarter_end_date`, `Holding13F.report_quarter`, and `Filing13F.is_active_for_manager_period` repaired production rows and are idempotent. That is acceptable as a temporary data-healing layer. But the comments admit the modern ingest path leaves required columns unset. Repeated job-level healing is a workaround for a write-path contract problem.

Recommendation: keep the repair for historical rows, but fix the source write path so new holdings and filings are born with `quarter_end_date`, `report_quarter`, and correct active status. If there are already-prod rows that need one-time repair outside normal job execution, prefer an Alembic data migration or explicitly named backfill job with clear audit trail. Do not rely indefinitely on every `ingest_holdings` run to heal shape that should be invariant.

### P1 - `backfill_period_routing()` does not persist routing warnings/errors

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/edgar_ingestion.py:993`

`route_period()` returns `parse_status`, `parse_warning`, and `parse_error` for missing/invalid/suspicious periods (`thirteenf_filing_detail.py:139-194`), but `backfill_period_routing()` only applies `period_of_report`, `quarter_end_date`, `report_quarter`, and `official_filing_deadline`. A `PERIOD_TOO_FAR_FROM_QUARTER_END` or invalid period can be skipped or partially applied without marking the filing as `needs_review`/`failed`. That weakens operator visibility and can make the job appear clean while routing degraded.

Recommendation: copy the same status/warning/error fields used by `ingest_accession_filing_detail()` into `Filing13F` during routing. For invalid/missing periods, include counts in the job summary and make the stage `partial_success` rather than quietly proceeding.

### P2 - Period routing recompute is not concurrency-safe across same manager/period

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/edgar_ingestion.py:1023`

The clear-all then recalculate dance for `is_latest_for_period` is correct in a single worker for one manager/period, but there is no row lock around affected filings. The quarterly pipeline lock serializes by quarter, not by manager/period. A manual accession ingest or another quarter job touching the same manager's corrected period could interleave.

Recommendation: lock affected `Filing13F` rows for each `(manager_id, old_period/new_period)` with `FOR UPDATE`, or route all same-manager affected periods inside a single policy function that can be safely retried after serialization failures.

### P2 - CUSIP null-quarter guard can leave historical mis-links in place

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/cusip_enrichment.py:321`

Skipping temporal validity when `Holding13F.quarter_end_date IS NULL` avoids the SQLAlchemy `<= None` crash, but it can select an active mapping across a corporate-action boundary. Because the current quarterly pipeline runs period routing before enrichment, future normal runs are less exposed. However, rows enriched during the earlier broken state may already have `stock_id` set using no temporal filter, and Phase 4 later fills `quarter_end_date` without revalidating those mappings.

Recommendation: after backfilling `quarter_end_date`, reset/revalidate linked holdings whose mapping was made with NULL quarter date, or make `_apply_mappings_to_holdings()` refuse to link when `quarter_end_date` is NULL and instead leave `pending_mapping`/`needs_period_routing`.

### P2 - Final reconcile anchor is terminal, but zero-signal and incomplete-quarter cases need bounding

File: `.claude/worktrees/optimistic-hofstadter-630d85/backend/app/services/thirteenf_start_quarter.py:68`

Anchoring on `oracles_lens_signals` is better than anchoring on job status or routed filings because it is the current terminal output. The known edge case is real: a quarter with no stocks above `min_holders` will enqueue every boot forever. There is another operational edge: `current_quarter()` defaults to the current calendar quarter (`thirteenf_start_quarter.py:46`), so before 13F filings are due, the reconcile can repeatedly enqueue an inherently incomplete quarter with zero terminal signals.

Recommendation: either record a terminal "scoring completed with zero eligible stocks" marker, or treat a succeeded `oracles_lens_score_backfill` with `filings_scored=0` as terminal for a bounded TTL. Also default `end_quarter` to latest complete/usable 13F quarter rather than current calendar quarter.

## Review 3 - Deploy & Infrastructure

### P1 - Move persistent storage out of the CI/CD workspace

File: `.claude/worktrees/optimistic-hofstadter-630d85/.github/workflows/deploy.yml:32`

`clean: false` prevents `actions/checkout` from deleting `storage/edgar_raw` and `storage/uploads`, but the runner workspace is still the wrong physical home for persistent application data. Future workflow edits, manual cleanup, runner maintenance, or a different checkout path can still wipe or orphan data. Persistent data should not depend on checkout semantics.

Recommendation: move bind-mount sources to a stable path outside the repository workspace, such as `$HOME/valuepilot-data/edgar_raw` and `$HOME/valuepilot-data/uploads`, and update `docker-compose.prod.yml` / env config accordingly. Keep `clean: false` only as a short-term protection until that migration lands.

### P2 - `clean: false` allows untracked workspace drift

File: `.claude/worktrees/optimistic-hofstadter-630d85/.github/workflows/deploy.yml:40`

With checkout cleaning disabled, untracked files accumulate indefinitely: stale generated assets, old build outputs, `.pyc` trees, removed files, and abandoned temporary directories. Untracked files cannot normally shadow tracked files with the same path, but they can influence tooling that scans directories or globs. The deploy script may also see files that no longer exist in git.

Recommendation: if storage cannot move immediately, add a targeted cleanup step that deletes known-safe transient paths while explicitly preserving `storage/edgar_raw`, `storage/uploads`, and env files. Better: move storage outside the workspace and restore normal checkout cleaning.

### P3 - Env install step is not weakened by #48

File: `.claude/worktrees/optimistic-hofstadter-630d85/.github/workflows/deploy.yml:43`

The `.env` / `.env.prod` copy step still requires files under `$HOME/.config/valuepilot` and overwrites workspace env files each deploy. `clean:false` does not directly weaken that path. The remaining concern is general workspace drift, not env installation.

## Review 4 - Error-Masking & Test-Adequacy Audit

### Broad exception blocks to narrow

- P1: `thirteenf_admin_dashboard.py:3201-3207` catches all routing failures and continues. Narrow or fail hard for programming errors.
- P1: `thirteenf_admin_dashboard.py:3191-3193` and `3222-3224` catch all per-filing fetch/parse failures and call full `session.rollback()`. Use per-filing savepoints and catch expected EDGAR/load/parse exceptions, not all `Exception`.
- P2: `edgar_ingestion.py:984-989` catches all exceptions from `load_body()` / `parse_primary_doc()` inside routing. This is acceptable for per-document bad data, but should not catch import/API programming errors. Consider catching `OSError`, parser-specific errors, and XML parse errors.
- P2: `_resolve_infotable_url()` / `_resolve_primary_doc_url()` catch all exceptions around `client.head()` at `edgar_ingestion.py:832-856`. Acceptable as fallback probing, but it will also hide client programming errors. Consider catching HTTP/not-found exceptions only.
- P2: `_execute_pipeline_stage_job()` catches all stage exceptions at `thirteenf_admin_dashboard.py:3092`. This boundary is acceptable if stage summaries visibly fail and tests assert programming errors become failed jobs. It should not be paired with inner broad catches that convert bugs into success.
- P3: worker notification/heartbeat catches at `thirteenf_job_worker.py:307`, `348`, `403` are operationally reasonable.

### Missing tests - highest value first

1. Integration test for `_execute_ingest_job` against a real test DB with two filings: first routes/fetches successfully, second raises during fetch or parse. Assert earlier phase data is not rolled back unexpectedly and summary counts match committed DB state.
2. Integration test where `backfill_period_routing` raises `ImportError` or `AttributeError`. Assert `ingest_holdings` fails loudly rather than returning success/partial success with zero useful work.
3. End-to-end quarterly pipeline test with real `ensure_filing_infotable_doc`, `backfill_period_routing`, `ingest_if_needed`, enrichment stubbed only at the external OpenFIGI boundary, and scoring run against actual holdings. Current stage tests heavily monkeypatch the pieces that broke.
4. Amendment policy regression: original HR plus non-restatement HR/A for the same manager/quarter. Assert quarterly ingest does not activate the HR/A via `is_latest_for_period`.
5. RESTATEMENT regression: original HR plus RESTATEMENT HR/A. Assert only the restatement is active after successful parse and original is demoted.
6. Routing warning regression: primary doc with period too far from quarter end. Assert `parse_status` / warning is persisted and job summary reports partial success.
7. Reconcile zero-signal test: a quarter with completed scoring but zero eligible stocks should not enqueue forever, or the repeated enqueue should be explicitly bounded/accepted.
8. Storage self-heal test for the full call path: linked DB rows with missing files, `ingest_holdings` unconditionally calls `ensure_filing_infotable_doc`, files are restored, routing and parsing proceed.

### Reconcile criterion stability

Answer: mostly stable, but not complete. `oracles_lens_signals` is terminal for quarters that produce at least one signal, and it fixed the observed skip-too-early failures. It is not stable for zero-signal quarters or incomplete current quarters. Add a terminal scoring-complete marker or bounded TTL behavior.

### Idempotency spot-check

- `ensure_filing_infotable_doc`: idempotent on cache hits; reissues network calls only when linked files are missing or `force_refresh=True`.
- `backfill_period_routing`: intended idempotent, but it rewrites routing and ranking fields and can be affected by concurrent manager/period changes. It is safe in the normal serialized quarterly pipeline, less safe under manual concurrent jobs.
- `compute_signal_weighted_scores`: upsert/replacement pattern is semantically idempotent for scores, but it commits internally and rewrites `computed_at`/components on every run. It is not side-effect-free, though product values should converge.

## Recommended Follow-Up Order

1. Fix `_execute_ingest_job` transaction boundaries and Phase 2 fail-loud behavior.
2. Replace the `is_active_for_manager_period = is_latest_for_period` heuristic with shared active-filing policy.
3. Persist routing status/warnings/errors from `backfill_period_routing`.
4. Move persistent storage outside the CI workspace.
5. Add the missing integration tests above.
6. Bound reconcile re-enqueue behavior for zero-signal/incomplete quarters.
