# Re-review — 13F web-validation review-round-1 fixes

Reviewed branch: `claude/13f-web-validation`

Baseline: `git diff main...HEAD`

Prompt: `docs/tasks/2026-05-22_13f-web-validation-fixes-review-prompts.md`

## Overall Verdict

FAIL. The two original P1 fixes are directionally correct:

- `backfill_quarters()` now enumerates from `latest_usable_quarter_label()`.
- `execute_historical_backfill()` no longer writes terminal `JobRun.status`
  before the worker finalizes the lease.

However, the `app/cli/edgar.py backfill` command now has inconsistent quarter
sets between its index and holdings phases. This fails prompt A3/E10 and should
block approval until the CLI uses the same usable-report-quarter list for both
steps.

## Findings

### [P1] CLI `backfill` indexes one quarter set but ingests holdings for another

Evidence:

- Step 1 calls the fixed `backfill_quarters()`, which now walks backward from
  `latest_usable_quarter_label()`:
  `backend/app/services/edgar_ingestion.py:912-936`.
- Step 2 still builds its own list with `_recent_quarters(today.year,
  today.month, quarters)`, which starts at the current calendar quarter:
  `backend/app/cli/edgar.py:224-238`,
  `backend/app/services/edgar_ingestion.py:1119-1129`.

On May 22, 2026, `latest_usable_quarter_label()` is `2026-Q1`. With
`quarters=4`, Step 1 indexes report quarters:

`2026-Q1`, `2025-Q4`, `2025-Q3`, `2025-Q2`

Step 2 scans local filing rows for:

`2026-Q2`, `2026-Q1`, `2025-Q4`, `2025-Q3`

So the command skips holdings ingestion for `2025-Q2` rows it just indexed and
wastes a pass over `2026-Q2`, a quarter it did not index and which is not a
usable report quarter. This is not only a harmless local scan; it breaks the
CLI command's stated "form.idx + holdings for recent N quarters" behavior.

The fix should make Step 2 reuse the exact ordered quarter list returned by
Step 1, or factor the usable-quarter enumeration into a helper shared by
`backfill_quarters()` and the CLI.

## Prompt Checklist

### A. R-P1a — `backfill_quarters` quarter source

1. PASS for `backfill_quarters()` itself. It starts from
   `latest_usable_quarter_label()` and walks backward with
   `previous_quarter_label()` (`backend/app/services/edgar_ingestion.py:922-936`).
   Because `latest_usable_quarter_label()` only returns a report quarter after
   its 45-day filing deadline, `next_quarter_label(q)` is always a calendar
   quarter that has already started.

2. PASS. The imports from `thirteenf_admin_dashboard` are function-local inside
   `backfill_quarters()` (`backend/app/services/edgar_ingestion.py:922-925`).
   `thirteenf_admin_dashboard.py` does not import `edgar_ingestion` at module
   load, only in local branches, so this avoids a module-load cycle.

3. FAIL. CLI Step 1 inherits the fixed `backfill_quarters()`, but Step 2 still
   uses `_recent_quarters()` and therefore scans a different quarter set. See
   P1 finding above.

### B. R-P1b — `historical_backfill` finalization

4. PASS. `execute_historical_backfill()` no longer sets `job.status` or
   `job.summary_json`; it commits per-run work and returns a dict containing
   `status` (`backend/app/services/thirteenf_historical_backfill.py:268-283`).
   The worker will still see the leased job as `running` and can finalize via
   `complete_leased_job()`.

5. PASS. Direct callers in
   `backend/tests/unit/test_13f_mvp3_historical_backfill.py` and
   `backend/tests/unit/test_13f_mvp4_quality_report_source_linkage.py` assert
   return values and quality report/finding rows, not terminal `job.status`.

6. PASS. The worker summary will now be the return dict minus `status`:
   `job_run_id`, `impact_summary`, `per_quarter`, and `scope`. That contains
   the same operational data plus `job_run_id`; I found no caller depending on
   the removed intermediate `summary_payload` shape.

7. PASS with note. The executor still commits before returning
   (`backend/app/services/thirteenf_historical_backfill.py:269-275`), so work is
   durable on normal completion while leaving the job row for caller
   finalization.

### C. Regression Tests

8. PASS with coverage note. The two new tests would fail against the pre-fix
   code:

- `test_backfill_quarters_does_not_request_a_future_filing_quarter` would catch
  current-quarter enumeration in `backfill_quarters()`.
- `test_historical_backfill_executor_leaves_job_for_caller_to_finalize` would
  catch the executor writing terminal `job.status`.

They do not cover the CLI Step 2 quarter mismatch found above.

### D. R-P2 Deferral

9. PASS. `docs/BACKLOG.md` now has an entry for
   `_check_period_alignment()` still using filing-quarter semantics, and the
   task log records R-P2 as deferred with a reason.

### E. No New Regressions

10. FAIL. `execute_historical_backfill` callers look safe, but the CLI
    `backfill` caller is broken by the `backfill_quarters()` quarter-source
    change because its second phase still independently uses `_recent_quarters()`.

## Verification

I did not run the Docker test suite for this re-review. The task log reports
`docker compose exec -T api pytest -q` as 909 passed on a fresh DB.

Given the CLI mismatch above, I would not approve this round yet.
