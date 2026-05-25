# Historical backfill ops + dedup — Review results

**Branch**: `claude/historical-backfill-ops-and-dedup`  
**PR**: #96  
**Reviewed**: 2026-05-25  
**Commit**: "Historical backfill ops + stale-failed-job dedup"

Verification run:

```bash
docker compose exec -T api pytest -q tests/unit/test_13f_admin_tasks_dedup.py
# 7 passed in 0.07s
```

---

## Part 1 — Backend Reviewer (B1–B8)

### B1 — Dedup correctness on boundary cases

**Scenario A: T1 fail → T2 success → T3 fail.**
Correct. `successor_rows` fetches ALL `succeeded`/`partial_success` rows for each
candidate lock_key. When processing T1, `any(t > T1 for t in [T2])` → True → T1 is
hidden. When processing T3, `any(t > T3 for t in [T2])` → False → T3 surfaces.
This is the right call: T1 is not actionable once a retry resolved the issue, and T3
is the current unresolved signal. **Verdict: accept.**

Suggested improvement (nit): add a test that pins this boundary: `failed(T1) →
succeeded(T2) → failed(T3)` should surface exactly T3 and hide T1.

**Scenario B: T1 fail → T2 success → T2 status manually flipped at T3.**
The successor query reads current status at query time (`status.in_(['succeeded',
'partial_success'])`). Once T2's status changes, it leaves `successor_rows`. On the
next dashboard reload T1 re-surfaces. This is correct behavior (the resolution has been
undone); it is truth-at-read-time, not a historical snapshot. **Verdict: accept
as-is.**

**Scenario C: two failures with different lock_keys; one success with `lock_key=""`.**
`candidate_lock_keys = {job.lock_key for job in jobs if job.lock_key}` excludes empty
strings. The empty-lock_key success contributes nothing to `successors_by_lock_key`.
Both failures surface. **Verdict: correct behavior; accept.**

---

### B2 — N+1 query concern

`fetch_limit = limit * 4 = 20` → max 20 distinct lock_keys → one bounded `IN` clause.
No N+1 issue. The per-job `any(t > job.created_at ...)` inner loop is O(M) where M is
typically ≤ 5 retries per lock_key. Negligible for a dashboard endpoint.

One real finding: at `thirteenf_admin_dashboard.py:2016`, `tuple_` is imported from
sqlalchemy but never used. **Severity: nit.**

Suggested fix: remove the unused `from sqlalchemy import tuple_` import.

**Verdict: accept.**

---

### B3 — `limit*4` widening

**Issue 1 (nit): silent undercount.**
If 18 of 20 fetched failures are superseded, the function returns 2 tasks instead of
5 with no log line. The admin doesn't know the dashboard is showing a thin result set.

Suggested fix: add a `logger.debug` line before return:
```python
logger.debug("_recent_job_alert_tasks: returning %d/%d (fetch=%d, limit=%d, dedup_hidden=%d)",
             len(tasks), fetch_limit, fetch_limit, limit, fetch_limit - len(tasks) - skipped)
```

**Issue 2 (nit): all-superseded edge case.**
If all 20 fetched failures are superseded, the dashboard shows 0 P1/P2 alerts even
though older unresolved failures exist beyond the fetch window. With `limit*4 = 20`
this is a narrow but real blind spot.

Suggested fix: BACKLOG entry; defer a follow-up PR that pages in batches until `limit`
visible tasks are collected or a hard max is reached.

**Severity: both nits. Not blockers.**

---

### B4 — Empty / None lock_key contract

The model (`institutions.py:780`) declares `lock_key: Mapped[str] = mapped_column(String(200), nullable=False)`.
The column is NOT NULL, so `None` can never arrive from the DB. Empty string `""` is
possible with no DB constraint preventing it.

The test `test_failed_job_with_no_lock_key_still_surfaces` uses `lock_key=""`, which
is the only falsy value the code can encounter. The test is accurate; the fixture
comment "no lock key" slightly misleads—rename to `blank_lock_key` for clarity.

**Improvement (nit):** a `CheckConstraint("lock_key != ''")` migration would close the
gap. Out of scope for this PR; BACKLOG entry sufficient.

**Severity: nit.**

---

### B5 — Harness sync-execute bypass

**Issue 1 (blocker for production use): no `lease_expires_at` set.**
The harness claims jobs by setting `status='running'`, `worker_id`, `lease_token` but
leaves `lease_expires_at = NULL` (`run_historical_backfill.py:127-132`, `~199`, `~248`).

`mark_stale_running_jobs_abandoned` (job_worker.py:216–217) filters:
```python
.filter(JobRun.lease_expires_at.isnot(None))
.filter(JobRun.lease_expires_at < now)
```
A harness-crashed job is therefore a ghost `running` row invisible to the reaper. The
partial unique index (`uq_job_runs_active_lock_key`, active statuses only) then blocks
re-enqueueing the same logical operation.

Suggested fix: set `job.lease_expires_at = datetime.now(timezone.utc) + timedelta(hours=4)`
in all three claim sites (`_run_one_range`, `_run_ingest_holdings`, `_run_enrich_cusip`).

**Issue 2 (nit): `historical_backfill` missing from `JOB_TIMEOUT_SECONDS_BY_TYPE`.**
`job_timeout_seconds('historical_backfill')` falls to the 10-minute default
(job_worker.py:278–279). A multi-quarter run takes 15–30 minutes; if a lease is ever
set and the reaper runs, it will abandon the job prematurely.

Suggested fix: add `"historical_backfill": 4 * 60 * 60` to `JOB_TIMEOUT_SECONDS_BY_TYPE`.

**Issue 3 (cosmetic): `worker_id` not in `JobWorkerHeartbeat`.**
Harness worker IDs are visible in `job_runs.worker_id` but have no heartbeat row.
Admin dashboards joining on heartbeat show "unknown worker". Acceptable for a one-shot
ops script.

**Severity: Issue 1 = nice-to-have (low crash probability in dev, but production-blocking). Issues 2–3 = nit.**

---

### B6 — Schema-shape assumptions in harness

**Issue 1 (nit): `partial_success` falls to the error print branch.**
`_run_ingest_holdings` prints summary data only when `res.get("status") == "succeeded"`:
```python
# run_historical_backfill.py:393-401
if res.get("status") == "succeeded":
    print(f"  {q}: filings_processed=... holdings_inserted=...")
else:
    print(f"  {q}: STATUS={res.get('status')} error={summary.get('error')}")
```
If `ingest_holdings` returns `partial_success`, the else branch prints
`STATUS=partial_success error=None`, hiding the actual holdings counts from the
operator.

Suggested fix:
```python
if res.get("status") in ("succeeded", "partial_success"):
    print(...)
```

**Issue 2 (nit): untyped summary dict.**
`summary.get('holdings_inserted')`, `summary.get('filings_xml_fetched')` etc. are
read by string key. A rename in `_execute_job` silently prints `None`. Acceptable for
an ops script; TypedDict would be over-engineering. BACKLOG entry noting the coupling
is sufficient.

**Severity: Issue 1 = nit (print correctness). Issue 2 = nit.**

---

### B7 — Per-filing failure tolerance in Stage 2

**Issue (nice-to-have): no non-zero exit on per-filing failures.**
28 failures across 47,400 filings surfaced only in per-quarter print lines. `main()`
returns 0 regardless. A CI wrapper or ops runbook has no automated signal of
degradation.

Suggested fix: accumulate `total_stage2_failed` and emit a non-zero return (or at
minimum a loud `WARNING:` line) when the count exceeds a threshold.

**Issue (nice-to-have): no admin task for failed accessions.**
The 28 failures are invisible in the admin overview after the run completes. An admin
task code `BACKFILL_HOLDINGS_FAILURES_NEED_REVIEW` would surface them for follow-up.

**Severity: both nice-to-have. Not merge blockers.**

---

### B8 — Test isolation in `test_13f_admin_tasks_dedup.py`

**`created_at` override after flush — does it work?**
The fixture (`test_13f_admin_tasks_dedup.py:55–64`) calls `flush()` (which fires
the `server_default = func.now()` on the DB side), then sets `job.created_at =
created_at`, then calls `flush()` again. SQLAlchemy marks the column dirty on
assignment and the second flush issues `UPDATE job_runs SET created_at = ? WHERE
id = ?`. PostgreSQL accepts the explicit value. The pattern works — confirmed by CI
passing and `test_recent_job_alert_tasks_returns_newest_first` exercising exactly this
ordering. **Verdict: accept.**

**Test isolation:**
The `db_session` fixture (conftest.py:44) opens a connection-level transaction and uses
`join_transaction_mode="create_savepoint"`. Every `session.commit()` operates on a
SAVEPOINT. At teardown the outer transaction rolls back, discarding all test rows. Tests
are fully isolated from each other and from any pre-existing DB state.

The `_LOCK_SEQ = count(99100000)` counter generates unique lock_keys per test within
the session, preventing accidental collision. **Verdict: accept.**

---

## Part 2 — 13F Data Quality SME (Q1–Q6)

### Q1 — Linked-ratio drift across quarters

| Quarter | Linked ratio |
|---|---|
| 2025-Q4 | 96.2% |
| 2025-Q3 | 96.1% |
| 2025-Q2 | 94.8% |
| 2024-Q4 | 93.4% |
| 2024-Q1 | 91.0% |
| 2023-Q1 | 85.1% |

**Is the 85% floor acceptable for value-investor use?**
**Verdict: accept with caution flags; temporal CUSIP mapping is correctly deferred.**
85% means ~1 in 7 holdings from 2023-Q1 cannot be resolved to a current ticker.
These are real companies that underwent M&A, spin-offs, ticker changes, or
delisting between 2023 and today. For multi-quarter conviction trends, unlinked
holdings create a systematic under-count bias for older quarters. The initial
backfill is still valuable — longitudinal signals that were impossible with 4 quarters
are now possible. But consumer-facing scoring derived from 2023-Q1 should carry a
caveat.

**Is 11 percentage points of drift over 2 years consistent with expectations?**
Yes. US large/mid-cap public-company turnover runs approximately 5–7% per year through
M&A, delistings, spin-offs, and ticker changes. Over ~2.5 years (2023-Q1 to 2025-Q4),
cumulative drift of ~11 percentage points is consistent with 4–5%/year
OpenFIGI-unresolvable rate. No anomaly.

**Recommended caution flag:**
Add `CAUTION_HISTORICAL_LINKED_RATIO_BELOW_90` on stocks whose conviction evidence
spans quarters with linked_ratio < 90% (inflection point in the data; 2024-Q1 and
earlier). 90% is where we lose roughly 1-in-10 holdings — enough to bias screener
results. This is a follow-up PR, not a merge blocker.

---

### Q2 — Per-filing failure rate

**Stage 2 actual rate: 28 failures out of ~816 filings processed ≈ 3.4% per-filing.**
(The task doc's "0.3%" uses total holdings as the denominator, not filings. The
per-filing rate is higher.)

**Is 3.4% per-filing failure acceptable?**
**Verdict: accept for initial backfill; investigate in a follow-up.**
28 failures is small in absolute terms and does not block use of the 47,400+ successfully
ingested holdings. However, the failing accession numbers should be recorded in a
BACKLOG entry before merge.

**Why does 2025-Q3 have 4 failures despite being recent?**
Expected failure modes for a recent quarter (most likely first):
1. Confidential treatment (CT) still in force — infotable.xml redirects to a CT notice.
2. Off-schema XML namespace or non-standard field ordering.
3. Rate Guard retryable errors that exhausted retries during the run.

Recommended pre-merge query:
```sql
SELECT id, quarter, summary_json -> 'failed_accessions' AS failed_accessions
FROM job_runs
WHERE job_type = 'ingest_holdings'
  AND COALESCE(jsonb_array_length(summary_json -> 'failed_accessions'), 0) > 0
ORDER BY finished_at DESC;
```

---

### Q3 — 145 unmapped CUSIPs → 0 unmapped

**Is 1,233 new mappings from ~47,400 holdings (2.6%) plausible?**
Yes. Historical quarters introduce older tickers and small-cap/micro-cap names not yet
in the OpenFIGI lookup cache. A 2–4% new-CUSIP rate for a 10-quarter backfill of ~80
active managers is consistent with prior enrichment runs. **Verdict: accept.**

**Is "0 unmapped" a sufficient success criterion?**
Necessary but not sufficient. The 1,233 new mappings could include
`confidence='needs_review'` rows (probable but not definitive OpenFIGI matches). If a
significant fraction are low-confidence, signal scores built on them carry hidden
uncertainty.

**Recommended pre-merge verification:**
```sql
SELECT confidence, COUNT(*) AS cnt
FROM cusip_ticker_mappings
WHERE created_at::date = '2026-05-25'
GROUP BY confidence
ORDER BY cnt DESC;
```
If `needs_review` > 5% of the 1,233 new mappings, add a BACKLOG entry for manual
review of the low-confidence batch.

---

### Q4 — Spot-check known managers

Run the following query against the dev DB before merge to verify manager-level
completeness:

```sql
SELECT
    im.name,
    h.report_quarter,
    COUNT(*) AS holdings_count,
    COUNT(*) FILTER (WHERE h.stock_id IS NOT NULL) AS linked
FROM holding13f h
JOIN filing13f f ON h.filing_id = f.id
JOIN institutionmanager im ON f.manager_id = im.id
WHERE im.cik IN (
    '0001067983',  -- Berkshire Hathaway
    '0001336528',  -- Pershing Square
    '0001167483',  -- Tiger Global
    '0000732905',  -- Tweedy Browne
    '0001279936'   -- Cantillon
)
GROUP BY im.name, h.report_quarter
ORDER BY im.name, h.report_quarter;
```

Expected results per manager:
- **Berkshire**: 12 quarters, 40–50 holdings each, high overlap between adjacent quarters.
- **Pershing Square**: 6–10 holdings per quarter, concentrated activist.
- **Tiger Global**: significant quarter-to-quarter churn.
- **Tweedy Browne**: long holding streaks, many positions continuous across quarters.
- **Cantillon**: pre-existing Q1/Q2/Q3 amendment rows should be PRESENT and UNCHANGED
  (verify by comparing `filing13f.id` values with pre-PR snapshot).

---

### Q5 — Activists / small-cap distinct universes

**With 12 quarters, does the Activists preset show more shared names?**
With only 4 quarters, each activist held different names and the preset returned ≤ 3
candidates. With 12 quarters, the longitudinal dimension is now meaningful: names that
appear in ≥ 2 activist managers' filings across ≥ 3 consecutive quarters are a real
consensus signal. Candidates to spot-check: Alphabet/Google, Uber, Charter
Communications (common cross-activist holdings in 2023–2025).

**Small-cap Sleuths preset:**
12 quarters should surface names appearing in ≥ 3 small-cap managers' filings even
if no single manager held them for many consecutive quarters.

**Recommended verification:**
Navigate to Oracle's Lens on dev, run the Activists preset across multiple quarters,
and record the candidate count. Compare to the "≤ 3" baseline documented before this
PR. Record the before/after count in the PR body.

---

### Q6 — Caveats that should be loud in the response

**Caveat 1: 2023-Q1 low linked ratio.**
Any Oracle's Lens candidate with a 2023-Q1 contributor inherits the 85% linked ratio
as a structural confidence limit. Consumers shown `conviction_score = 0.87` without
context may over-weight historical depth.

Recommended: add `CAUTION_HISTORICAL_DEPTH_LINKED_BELOW_THRESHOLD` to
`caution_flag_codes` for candidates where any contributing quarter has linked_ratio <
90%.

**Caveat 2 (BLOCKER — must verify before merge): persisted scoring gap.**
The `oracles_lens_signals` table is populated by `compute_signal_weighted_scores`.
That job runs on a schedule and processes quarters present at run time. The backfilled
holdings (2023-Q1 through 2025-Q2) were inserted AFTER the last scoring run. Unless
the scoring job was re-run against these quarters immediately after Stage 3 completed,
the persisted signal rows are stale or absent for the backfilled period. Oracle's Lens
would then silently exclude all backfilled holdings from scored candidates.

**Required pre-merge verification query:**
```sql
SELECT report_quarter, COUNT(*) AS signal_rows, MAX(updated_at) AS last_updated
FROM oracles_lens_signals
WHERE report_quarter BETWEEN '2023-Q1' AND '2025-Q2'
GROUP BY report_quarter
ORDER BY report_quarter;
```
If any backfilled quarter returns 0 signal rows, the PR must either:
(a) Run `oracles_lens_score_backfill` as a Stage 4 step in the harness, OR
(b) Document explicitly in the Acceptance Criteria that Oracle's Lens will not reflect
    backfilled data until the next scheduled scoring run.

**Verdict: investigate before merge.**

---

## Part 3 — Staff Engineer / SRE (O1–O7)

### O1 — Worker bypass without lease expiry

**Issue: no `lease_expires_at` set (blocker for production use).**
The harness creates `status='running'` rows at `run_historical_backfill.py:127–132`,
`~199`, and `~247` without setting `lease_expires_at`. The stale-job reaper
(`job_worker.py:216–217`) filters `lease_expires_at IS NOT NULL AND lease_expires_at < now`.
A harness-crashed job is invisible to the reaper and its active lock_key blocks
re-entry.

**Recommended fix (this PR):**
```python
job.lease_expires_at = datetime.now(timezone.utc) + timedelta(hours=4)
```
Apply in `_run_one_range`, `_run_ingest_holdings`, and `_run_enrich_cusip`. Also add
`"historical_backfill": 4 * 60 * 60` to `JOB_TIMEOUT_SECONDS_BY_TYPE` so the reaper's
grace period matches the actual expected runtime.

**`worker_id` not in `JobWorkerHeartbeat`:** cosmetic. Admin dashboards show "unknown
worker" for harness jobs. Acceptable for a CLI ops script.

**Priority: nice-to-have for dev-only use; required before production deployment.**

---

### O2 — Rate Guard interaction

**429/503 handling:**
The actual run completed with 0 Stage 1 failures (816/816 filings), indicating Rate
Guard's retry logic handled any transient errors transparently. No code change needed
for correctness.

**Shared throttle risk:**
Rate Guard's EDGAR throttle is per-environment. Running the harness in production
alongside an active job scheduler could double the effective EDGAR request rate, degrade
scheduler throughput, or trigger EDGAR's per-IP rate limiter.

**Recommended startup check:**
```python
if settings.THIRTEENF_JOB_WORKER_ENABLED and not args.dry_run:
    print("WARNING: THIRTEENF_JOB_WORKER_ENABLED=true. "
          "Running this harness shares the Rate Guard EDGAR throttle "
          "with the active scheduler. Disable the worker or use --dry-run.")
```

**Priority: nice-to-have for dev; required in the runbook before any production run.**

---

### O3 — Idempotency and resume

**Issue: no crash-resume.**
If the harness crashes mid-run (e.g., during quarter 5 of 11), re-invoking from the
top will:
1. Re-enqueue quarters 1–4 → Stage 1 skips already-present filings (`already_present`
   bumps), no error.
2. For the crashed quarter: `enqueue_historical_backfill` raises `HistoricalBackfillError`
   because the ghost `running` row's lock_key is in `ACTIVE_JOB_STATUSES`. The harness
   catches this and continues — the quarter is silently skipped.
3. Same behavior in `_run_ingest_holdings`: returns `{"status": "conflict"}` and the
   harness moves on.

Without `lease_expires_at` (see O1), the ghost rows are never reaped automatically.

**Recommended fix (follow-up PR):**
Add `--cleanup-stale-harness-jobs` flag that queries for `running` jobs with
`worker_id LIKE 'backfill-harness-%' OR worker_id LIKE 'holdings-harness-%'`
older than 1 hour and marks them `failed`. Operator runs this before any retry.
Setting `lease_expires_at` (O1) provides the automatic path.

**Priority: latent issue. Dev run succeeded without interruption.**

---

### O4 — Quality check coverage

**Issue: Stage 1 validation runs BEFORE Stage 2 holdings ingestion.**
`_historical_backfill_validation_gate` runs inside `execute_historical_backfill` (Stage 1).
It validates filing METADATA (submissions API, primary_doc.xml presence, filing counts).
The 11 quarters "passed validation" refers only to filing metadata — `Holding13F` rows
don't exist yet. Stage 2's 28 per-filing failures are NOT captured by Stage 1
validation.

**Missing post-Stage-2 quality gate:**
After Stage 2 and Stage 3 complete, the harness does not verify:
- Holdings count per quarter is within expected bounds
- Linked ratio per quarter meets a minimum threshold
- No quarter ended with 0 holdings (silent Stage 2 total failure)

**Recommended fix:**
Add a lightweight post-run check in `main()` after Stage 3:
```python
with SessionLocal() as s:
    for q in quarters_for_holdings:
        total = s.query(func.count(Holding13F.id)).filter(Holding13F.report_quarter == q).scalar()
        linked = s.query(func.count(Holding13F.id)).filter(
            Holding13F.report_quarter == q, Holding13F.stock_id.isnot(None)
        ).scalar()
        if total == 0:
            print(f"  WARNING: {q} has 0 holdings — Stage 2 may have failed silently")
        elif linked / total < 0.80:
            print(f"  WARNING: {q} linked ratio {linked/total:.1%} below 80% floor")
```

**Priority: nice-to-have for the dev run; important before production use.**

---

### O5 — Observability: stdout vs JobRun audit trail

**Stdout format:**
Current output uses `f"{c:>20}"` right-justified columns — human-readable but not
machine-parseable. A CI step grep-parsing this output would be fragile. A `--jsonl`
flag would make the output pipeline-friendly.

**ETA:**
No ETA is provided. Given 15–30 minutes total, a simple
`print(f"  ({remaining} quarters remaining, ~{remaining*2} min)")` would help operators
monitoring a long run.

**Durable audit trail:**
`JobRun.summary_json` is the authoritative record. However, because the harness does
not propagate `partial_success` status from `_execute_job` summaries back to
`complete_leased_job` (see B6), the JobRun row may record `succeeded` when the
underlying execution was degraded.

**Priority: nit for stdout format. The status propagation fix is in B6.**

---

### O6 — Deployment story

**Current state:**
`backend/scripts/run_historical_backfill.py` is CLI-only. No K8s Job manifest, no
cron entry, no admin UI wiring, no runbook.

**Recommended invocation for production:**
```bash
docker exec -it valuepilot-prod-api-1 python -m scripts.run_historical_backfill \
    --start-quarter <Q> --end-quarter <Q>
```
(Mirrors the `prod_db_one_off_scripts` pattern.)

**Admin UI vs. CLI:**
Keep the harness CLI-only for now. The admin "Bootstrap quarters" button is a
scheduler-driven trigger; wiring the full 3-stage pipeline to a web endpoint would
create a 15–30 minute synchronous HTTP request. If self-service backfill becomes a
product requirement, it needs a background job dispatch mechanism, not an inline HTTP
handler.

**Deliverable for this PR (minimum):**
Add a runbook note in the task doc or a `docs/runbooks/historical-backfill.md` covering:
- Invocation command
- Pre-run checks (scheduler enabled? shared throttle?)
- Expected output / success verification
- What to do if the harness crashes mid-run

**Priority: nice-to-have for the PR; required before production use.**

---

### O7 — Dedup observability gap

**Audit trail:**
`superseding_keys` is built at `thirteenf_admin_dashboard.py:2027–2035` but never
logged. An admin asking "what did the dashboard hide?" has no built-in path. They can
reconstruct it with:

```sql
SELECT jr_f.id, jr_f.job_type, jr_f.lock_key,
       jr_f.created_at AS failed_at,
       jr_s.created_at AS superseded_by_at,
       jr_s.status AS superseder_status
FROM job_runs jr_f
JOIN job_runs jr_s
  ON jr_f.lock_key = jr_s.lock_key
  AND jr_f.status IN ('failed', 'partial_success')
  AND jr_s.status IN ('succeeded', 'partial_success')
  AND jr_s.created_at > jr_f.created_at
WHERE jr_f.created_at > NOW() - INTERVAL '7 days'
ORDER BY jr_f.created_at DESC;
```

**Persistent-failure blindness:**
Dedup only hides a failure when a LATER SUCCESS exists. A recurring failure pattern
(failure-after-failure) still surfaces the latest failure. But the prior 5 attempts are
hidden, so the admin loses the "this has been failing for a week" frequency signal.

**Recommended fixes:**
1. (This PR, quick win) Add `logger.info("dedup: hiding %d failures superseded by
   later success on %d lock_keys", hidden_count, len(superseding_keys))` before return.
2. (Follow-up PR) Add `GET /admin/13f/jobs?include_dedup_hidden=true` debug endpoint.

**Priority: logger.info = quick win for this PR. Debug endpoint = follow-up.**

---

## Summary table

| ID | Severity | In this PR | Follow-up |
|---|---|---|---|
| B1 — add `T1→T2→T3` boundary test | nit | add test | — |
| B2 — unused `tuple_` import | nit | remove import | — |
| B3 — silent undercount; all-superseded blind spot | nit | add `logger.debug` + BACKLOG | adaptive fetch_limit PR |
| B4 — empty lock_key no DB constraint | nit | BACKLOG entry | migration PR |
| B5 — no `lease_expires_at`; `historical_backfill` missing from timeout dict | nice-to-have | set lease + add timeout entry | — |
| B6 — `partial_success` prints wrong branch | nit | fix condition | — |
| B7 — no exit-code or aggregate for per-filing failures | nice-to-have | — | follow-up PR |
| Q2 — investigate 2025-Q3 per-filing failures | investigate | document failed accessions in PR | — |
| Q3 — verify confidence distribution of new mappings | investigate | run verification SQL | — |
| Q6 — **scoring backfill for new quarters** | **BLOCKER (investigate)** | run verification SQL + document or add Stage 4 | — |
| O1 — no `lease_expires_at` (ghost job risk) | nice-to-have | set lease | — |
| O2 — shared throttle warning | nice-to-have | add startup warning | runbook |
| O3 — no crash-resume | latent | BACKLOG entry | `--cleanup-stale` flag PR |
| O4 — no post-Stage-2 quality gate | nice-to-have | add print check | formal gate PR |
| O5 — stdout not machine-parseable | nit | — | `--jsonl` flag PR |
| O6 — no runbook | nice-to-have | add runbook note | production runbook doc |
| O7 — dedup decision not logged | nit | add `logger.info` | debug endpoint PR |

**Merge blockers: 1** — Q6 (scoring backfill verification). Must confirm
`oracles_lens_signals` has data for the backfilled quarters before claiming Oracle's
Lens reflects the new history, or explicitly document the gap in Acceptance Criteria.

**Recommended actions before merge:**
1. Run the Q6 verification SQL and record results in the PR body.
2. Fix the B6 `partial_success` print branch (one-liner).
3. Remove the unused `tuple_` import (B2).
4. Add `logger.info` for dedup decisions (O7 quick win).
5. Document the 28 failed accessions from Stage 2 in a BACKLOG entry (Q2).
