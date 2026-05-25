# Historical backfill ops + dedup — Three-role review prompts

Three reviewer prompts for the historical-backfill PR. Each is
self-contained — drop the prompt into a fresh chat or hand it to a
human reviewer without needing this conversation's history.

**Branch**: `claude/historical-backfill-ops-and-dedup`
**PR**: #96
**Commit**: title "Historical backfill ops + stale-failed-job dedup"

**Task docs**:
- `docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md` — design + per-quarter ops trace

**Why this PR exists**: A previous PO acceptance review noted "Historical depth: 0 quarters" with `historical_backfill job failed: Unsupported job_type` as a P1 admin task. Surface diagnosis blamed the dispatcher. Real diagnosis: (a) JobRun #4526 was a stale failure from before the wiring was complete; #4553 succeeded 21 minutes later under the same `lock_key` — admin overview just wasn't dedup-ing. (b) No one had ever run a true cross-quarter historical backfill, so the data was empty. This PR fixes both at once: a small dedup change to admin tasks AND a real ops run that backfilled 11 quarters of holdings.

Roles (priority order):

1. **Backend Reviewer (HIGH).** Reviews the dedup code in `_recent_job_alert_tasks`, the harness script in `backend/scripts/run_historical_backfill.py`, test coverage, and the UX risk that dedup hides real problems.
2. **13F Data Quality SME (HIGH).** Reviews the actual ops run trace: linked ratios per quarter, the 28 per-filing ingest failures, the 1,233 new CUSIP mappings, and recommends additional validation queries.
3. **Staff Engineer / SRE (MEDIUM).** Reviews the harness's synchronous-execute pattern that bypasses the worker, real SEC traffic via Rate Guard, idempotency claims, deployment / runbook implications.

---

## 1. Backend Reviewer Prompt

You are a senior backend engineer doing a code-level review. Focus on
the dedup logic, the harness implementation, test coverage, and the
UX risk of accidentally swallowing real failures.

**Read these files in order:**

1. `docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md` — the
   task doc with the per-quarter trace at the bottom (line ~120
   onward).
2. `backend/app/services/thirteenf_admin_dashboard.py` — find
   `_recent_job_alert_tasks` (was at line 1980 before this PR;
   shifted slightly after the dedup expansion). Read the entire
   function including the new docstring and the SAVEPOINT-style
   per-job successor-lookup block.
3. `backend/tests/unit/test_13f_admin_tasks_dedup.py` — the 7 new
   contract tests.
4. `backend/scripts/run_historical_backfill.py` — the ops harness.
   Read the module docstring, then `_historical_depth_quarters`,
   `_holdings_depth_quarters`, `_run_one_range`, `_run_ingest_holdings`,
   `_run_enrich_cusip`, and `main`.

**Eight code-quality questions you must answer.**

### B1 — Dedup correctness on the boundary cases

The dedup checks "any successor on this lock_key created later than this failure". Walk through:

- A failure at T1, success at T2 > T1, another failure at T3 > T2. Current behavior: T1 is dedup-ed (success follows it), T3 still surfaces. Is that the right call? Or should T3's later failure invalidate the prior success and re-surface T1?
- A failure at T1, success at T2 > T1, the success is then manually "cancelled" (status flipped) at T3. The current dedup queries `status IN ('succeeded', 'partial_success')` at READ time, so the moment the success row's status changes, T1 re-surfaces. Is this the right behavior or should we use the `finished_at` snapshot at the time of dedup?
- Two failures at T1 with different lock_keys, but a single success at T2 with `lock_key=None`. Current behavior: T2 is excluded from the successors index (we only build the index for candidates with non-NULL lock_key). Both failures still surface. Correct?

### B2 — N+1 query concern

The implementation builds a single `successors_by_lock_key` dict via one query over `lock_key IN (candidate_lock_keys)`. Verify this:
- Is the candidate_lock_keys set ever pathologically large? With `limit*4 = 20` failed jobs, max 20 distinct lock_keys, so the `IN` clause is bounded.
- The per-iteration `any(t > job.created_at for t in successor_times)` is O(M) per candidate. Total O(N*M) where N≤20, M≤(rows per lock_key) — typically small. Acceptable for a dashboard endpoint?

### B3 — `limit*4` widening

The original `limit=5` is widened to `fetch_limit=limit*4=20` before dedup. Two concerns:
- What if post-dedup we still have fewer than `limit` items (e.g., 18 of 20 are dedup-ed)? The function returns the smaller count silently — no log line, no "we cut N rows". Should we surface that count somewhere for admin observability?
- What if every one of the top-20 failures is superseded? The dashboard would show 0 P1/P2 alerts, but there are older failures further back that ARE still unresolved. Edge case but possible — should `fetch_limit` adapt?

### B4 — Empty / None lock_key contract

Test `test_failed_job_with_no_lock_key_still_surfaces` uses `lock_key=""` (empty string), not `lock_key=None`. The model declares `lock_key: Mapped[str] = mapped_column(String(200), nullable=False)` so `lock_key` is always a string and never NULL. Is the empty-string defense correct, or is it impossible in practice (i.e., should we add a server-default or check constraint to enforce non-empty)?

### B5 — Harness sync-execute bypass

The harness in `run_historical_backfill.py` manually claims a JobRun (sets `status=running`, `worker_id`, `lease_token`), runs `_execute_job` inline, then calls `complete_leased_job`. This bypasses `claim_next_job` which has the `SELECT ... FOR UPDATE SKIP LOCKED` pattern.

- Is the bypass safe? The harness is explicitly run by a human; concurrent harness invocations would race, but the lock_key uniqueness constraint catches them at INSERT.
- The `lease_expires_at` is NEVER set by the harness — if the script crashes mid-run, the job sits in `running` forever with no lease, and `mark_stale_running_jobs_abandoned` won't catch it (it requires `lease_expires_at IS NOT NULL AND lease_expires_at < now`). Should we set a sentinel `lease_expires_at = now + 4h` for safety?

### B6 — Schema-shape assumptions in the harness

The harness reads specific keys from each stage's summary dict
(`holdings_inserted`, `filings_xml_fetched`, `mappings_created`, etc.).
These are returned by `_execute_job` in scattered handlers and aren't typed.

- If a future PR adds a new field or renames one, the harness silently prints `None`. Is that acceptable for an ops script, or should we add a TypedDict / Pydantic model to type the summary contract?
- The `ingest_holdings` summary also has `status='partial_success'` when degraded; the harness treats only `'succeeded'` as success. Is that the right strictness?

### B7 — Per-filing failure tolerance in Stage 2

The Stage 2 trace shows 28 total per-filing failures across 11 quarters (~0.3%). These are caught and recorded in `failed_accessions` but the job overall is `'succeeded'`. The harness prints `failed=N` per quarter but never aggregates.

- Should the harness fail (non-zero exit) if any quarter has > N% per-filing failures?
- Should it emit a follow-up admin task code (e.g., `BACKFILL_HOLDINGS_FAILURES_NEED_REVIEW`) so the failures show up in the admin overview?

### B8 — Test isolation in `test_13f_admin_tasks_dedup.py`

The test fixtures insert JobRun rows with explicit `created_at` overrides AFTER initial flush, to control ordering. Verify:
- Are the SQLAlchemy mappings cooperative? Setting `created_at` after `flush()` and then re-flushing — does PG actually accept the explicit value when `server_default=func.now()` already ran?
- The test queries `_recent_job_alert_tasks(db_session)` without any explicit cleanup. If the dev DB has accumulated test rows, do the tests pollute each other's results?

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-25_historical-backfill-ops-and-dedup-review-results.md`
with sections matching B1–B8. For each issue, give file + line +
severity (blocker / nit) + suggested fix.

---

## 2. 13F Data Quality SME Prompt

You are a 13F domain expert reviewing the actual data trace from a
real ops run. The dispatcher worked; this PR's value is whether the
ingested data is correct, complete, and useful.

**Context**: This PR ran a 3-stage backfill end-to-end on the dev
environment for 11 quarters (2023-Q1 → 2025-Q3). The numbers below
are real, from a real SEC fetch.

**Read these files in order:**

1. `docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md` —
   focus on the "Per-quarter trace (actual run, 2026-05-25)" section
   at the bottom.
2. `backend/scripts/run_historical_backfill.py` — for context on
   exactly what the script ran.

**Six data-quality questions you must answer.**

### Q1 — Linked-ratio drift across quarters

| Quarter | Linked ratio |
|---|---|
| 2025-Q4 | 96.2% |
| 2025-Q3 | 96.1% |
| 2025-Q2 | 94.8% |
| 2024-Q4 | 93.4% |
| 2024-Q1 | 91.0% |
| 2023-Q1 | 85.1% |

The drift from 96% (recent) → 85% (oldest) is presumably from corporate actions: stocks that merged, spun off, went private, or changed ticker between filing date and today. OpenFIGI's current snapshot can't resolve those back-in-time.

- Is the 85% floor acceptable for value-investor use, or do we need temporal CUSIP mapping (a separate PR — already noted as out-of-scope) before this data is trustworthy?
- Are 11-percentage-point drift over 2 years consistent with what you'd expect from US-equity public-company turnover? (Roughly 6%/yr of S&P 500 names change identity through M&A or spin-offs.)
- Should we add a CAVEAT_HISTORICAL_LINKED_RATIO_BELOW_X caution flag on stocks whose holders' linked ratio for the period is below some threshold? Where would you set it?

### Q2 — Per-filing failure rate

Stage 2 totals: **28 per-filing failures across 47,400+ filings = 0.06% of holdings** (or ~0.3% of filings). Distribution by quarter:

| Quarter | Failures |
|---|---|
| 2023-Q4 | 5 |
| 2025-Q3 | 4 |
| 2023-Q2 | 3 |
| 2023-Q1 | 2 |
| (others) | 0–3 |

- Is 0.3% per-filing failure rate acceptable for production use, or should the PR include investigating WHICH filings failed before claiming "done"?
- The 2025-Q3 having 4 failures despite being recent is notable (we'd expect older filings to fail more). What investigation would you want here — likely candidates: confidential treatment expiration timing, missing infotable.xml URL, off-schema XML?
- Should the harness's exit code reflect per-filing failures, not just stage-level success?

### Q3 — 145 unmapped CUSIPs → 0 unmapped

Stage 3 created 1,233 new CUSIP mappings and now reports 0 unmapped CUSIPs. The 145 unresolved CUSIPs from the PO acceptance review (a P2 admin task at the time) are now resolved.

- Sanity-check: 1,233 new mappings from 47,400 new holdings ≈ 2.6% new-CUSIP rate. Plausible for ~10 historical quarters?
- Is "0 unmapped" the right success criterion, or should we also verify that high-confidence (`confidence='high'`) mappings dominate (vs `needs_review`)?
- Spot-check candidates: pull 5 of the 1,233 newly-created mappings at random and validate ticker assignment manually against SEC company search. Are they correct?

### Q4 — Spot-check known managers

For each of these managers, verify their dev DB now has 12 quarters of holdings:

- **Berkshire Hathaway** (CIK 0001067983) — should have all 12 quarters; top 10 should overlap heavily across adjacent quarters (Buffett's low turnover).
- **Pershing Square** (CIK 0001336528) — concentrated activist; expect 6–10 names per quarter.
- **Tiger Global** (CIK 0001167483) — high turnover; expect significant churn between quarters.
- **Tweedy Browne** (CIK 0000732905) — classic deep value; expect long holding streaks.
- **Cantillon** (CIK 0001279936) — already had Q1/Q2/Q3 amendments pre-PR; should still be present after backfill (not overwritten).

Run a query to confirm each manager's holdings_count per quarter. If any are missing, that's a data-completeness gap.

### Q5 — Activists / small-cap distinct universes

The Oracle's Lens "Activists" preset (Pershing/Trian/ValueAct/TCI/Engaged/Icahn/Third Point) returned 0 candidates on the dev environment last PR review because each activist holds different names. Now that we have 12 quarters of data:

- Does the Activists preset still return ≤ 3 candidates per quarter (their actual overlap rate), or has the broader history found more shared names?
- Does the Small-cap Sleuths preset now show candidates? (Pre-PR it was also sparse because small-cap funds rotate frequently.)
- Spot-check: any candidates that appear in the Activists preset across multiple quarters → real consensus signal. Without time depth this signal was impossible.

### Q6 — Are there caveats that should be loud in the response now?

The 12-quarter universe enables longitudinal signals (streak length, holding persistence, conviction trajectory) that were inert before. But it also brings new caveats that the consumer must respect:

- 2023-Q1 holdings have 85% linked ratio. Any candidate built on 2023-Q1 contributors has structurally weaker confidence. Should the response signal this via `caution_flag_codes` or score_confidence demotion?
- Quarters that were just backfilled (today) may not have had `compute_signal_weighted_scores` re-run yet — the persisted `oracles_lens_signals` table only has fresh data for periods the score job ran on. Is there a verification step we're missing that ensures the persisted scoring caught up with the new holdings?

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-25_historical-backfill-ops-and-dedup-review-results.md`
with sections matching Q1–Q6. For each finding, give a verdict
(accept / change / investigate) and any SQL queries that should be
run before merge.

---

## 3. Staff Engineer / SRE Prompt

You are a staff engineer / SRE reviewing the ops practices in this
PR. Focus on the harness's deployment story, what happens at scale,
and the gap between "this ran once on dev" and "this is ready for
production / staging".

**Read these files in order:**

1. `backend/scripts/run_historical_backfill.py` — the entire script
   including module docstring.
2. `docs/tasks/2026-05-25_historical-backfill-ops-and-dedup.md` —
   sections "Per-quarter trace" and "Decisions / gotchas".
3. `backend/app/services/thirteenf_job_worker.py` — for context on
   the lease/heartbeat/timeout pattern the worker normally uses.
4. `backend/app/edgar/client.py` and `backend/app/rate_guard/` (if
   it exists) for Rate Guard integration.

**Seven ops questions you must answer.**

### O1 — Worker bypass without lease expiry

The harness manually creates a JobRun with `status='running'` and a
`worker_id` of the form `backfill-harness-<8-char-uuid>` but does NOT
set `lease_expires_at`. The model declares `lease_expires_at` as
nullable so this is permitted.

`mark_stale_running_jobs_abandoned` reaps jobs where
`lease_expires_at IS NOT NULL AND lease_expires_at < now`. So a
harness-crashed job is invisible to that reaper.

- Is the "no lease_expires_at" the right call (the harness owner is
  responsible), or should we set `lease_expires_at = now + 4 hours`
  as a safety net? The 4-hour stage-job timeout for `backfill_*` is
  in `thirteenf_job_worker.py:25` for reference.
- The `worker_id` includes a UUID but isn't registered in `JobWorkerHeartbeat`. Is that a problem (jobs from "unknown workers" floating around)?

### O2 — Rate Guard interaction

Per the task doc: "~2,000-3,000 SEC requests over the run. At Rate Guard's edgar throttle (~10 req/s), expect ~16-30 seconds per quarter plus parse time."

- Verify: when running through Rate Guard, are 429s / 503s handled
  gracefully? Is there an exponential backoff?
- What if Rate Guard's edgar throttle is shared with the production
  scheduler? Running this harness in a production environment with
  an active scheduler could double the request load — does the
  harness need a "production check" guard, or is the existing
  THIRTEENF_JOB_WORKER_ENABLED enough?

### O3 — Idempotency and resume

If the harness crashes mid-run (e.g., quarter 5 of 11), the next
invocation starts from quarter 1 again because each `_run_one_range`
call re-enqueues a JobRun via `enqueue_historical_backfill`. But:

- `enqueue_historical_backfill` raises `HistoricalBackfillError` if
  an active job exists with the same lock_key — that's good for
  concurrent invocation but bad for resume after a crash (the
  half-running JobRun is stuck in `running` with no lease).
- The `ingest_holdings` per-quarter calls have their own lock_key
  pattern (`ingest_holdings:{quarter}`) and check `ACTIVE_JOB_STATUSES`. Same crash-resume issue.
- Should the harness clean up stale `running` JobRuns at startup if
  their `worker_id` matches the `harness-*` prefix and the job is
  older than e.g. 1 hour?

### O4 — Quality check coverage

Stage 1 runs `_historical_backfill_validation_gate` which calls
`run_quality_checks(session, quarter)`. The trace shows all 11 quarters
"passed validation" but Stage 2 separately had 28 per-filing failures.

- Are the per-filing failures (Stage 2) caught by validation in
  Stage 1? It looks like Stage 1 validation runs BEFORE Stage 2
  ingestion of holdings — so failures in Stage 2 wouldn't roll back
  Stage 1's "passed" status. Is the temporal ordering right?
- Should the harness re-run quality_check at the END after Stages 2
  and 3 complete, to validate the holdings data, not just the filing
  metadata?

### O5 — Observability: stdout vs JobRun audit trail

The harness prints per-stage progress to stdout. The JobRun rows
also have summary_json. If someone runs this in CI, the stdout is
the artifact; if someone runs it manually, both are available.

- Is the stdout format machine-parseable (e.g., for a downstream
  alerting pipeline)? Currently it's pretty-printed columns.
- For long ops runs, would a progress estimate ("ETA: 7 minutes")
  be valuable, or is the current "one line per completion" enough?

### O6 — Deployment story

This PR adds `backend/scripts/run_historical_backfill.py` but does
NOT wire it into:
- Any cron / scheduled job
- The admin Manual Controls UI
- A Kubernetes Job manifest
- A documented runbook

- For prod deployment of the same data ops, what's the recommended
  invocation pattern? `docker compose exec` is dev-only.
- Should the admin "Bootstrap quarters" / "Backfill quarters" UI
  button be re-wired to call the full 3-stage pipeline, OR is the
  harness intended to remain CLI-only?

### O7 — Dedup observability gap

The dedup change in `_recent_job_alert_tasks` silently skips failed
JobRuns that are superseded by later success. Admin no longer sees
those failures.

- Is there an audit trail that the dedup decision was made? E.g.,
  could a reviewer ask "show me all failed JobRuns hidden by dedup
  in the last 7 days"?
- If a recurring failure pattern starts up, the latest failure WOULD
  surface (no later success), but the prior 5 might be hidden — does
  the admin lose the "this has been failing for a week" signal?
- Consider adding a debug-only admin endpoint
  `GET /admin/13f/jobs?include_dedup_hidden=true` for triage. Worth
  this PR or its own follow-up?

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-25_historical-backfill-ops-and-dedup-review-results.md`
with sections matching O1–O7. For each finding, give the recommended
fix (in this PR / follow-up PR / acceptable as-is) and the priority
(blocker / nice-to-have).

---

## Notes for all three reviewers

- The dev environment had pre-existing test isolation issues in
  `_clear_13f` helpers (see `docs/BACKLOG.md`). This PR does NOT
  touch those tests; CI passed on fresh DB.
- The actual ops run happened on the dev DB — it inserted ~52k real
  Holding13F rows that future PRs (and this PR's PO smoke check)
  will rely on.
- Reviewers can run, at minimum:
  ```
  docker compose exec -T api pytest -q tests/unit/test_13f_admin_tasks_dedup.py
  ```
  to confirm the dedup contract.
- The historical_backfill harness has been verified end-to-end on
  dev. Running it again is **not** idempotent in the simple sense:
  Stage 1 will skip filings already present (filings_already_present
  bumps); Stage 2 will skip already-ingested holdings (parse runs
  with same fingerprint dedup); Stage 3 will skip already-mapped
  CUSIPs. So re-running the harness should be safe but will print
  zeros across the board.
