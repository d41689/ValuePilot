# Review — 13F web-validation fixes

Reviewed branch: `claude/13f-web-validation`

Baseline: `git diff main...HEAD`

Prompt: `docs/tasks/2026-05-21_13f-web-validation-review-prompts.md`

## Overall Verdict

FAIL. The core report-quarter direction is mostly right, but I found two
blocking regressions/risk points:

1. `backfill_quarters()` still starts from the current calendar quarter. After
   `ingest_quarter_index()` began translating report quarter -> next filing
   quarter, this can request an EDGAR full-index quarter that has not started
   yet.
2. `execute_historical_backfill()` writes the `JobRun` status itself before the
   worker calls `complete_leased_job()`. The worker's lease completion then no
   longer matches because the row is no longer `running`, so `finished_at` and
   `lease_expires_at` are not finalized by the worker.

I also found a non-blocking but relevant residual filing-quarter assumption in
`edgar_quality._check_period_alignment()`.

## Findings

### [P1] `backfill_quarters()` can fetch a not-yet-started filing quarter

Evidence:

- `ingest_quarter_index()` now explicitly treats `quarter` as a report quarter
  and fetches `next_quarter_label(quarter)`:
  `backend/app/services/edgar_ingestion.py:447-460`.
- `backfill_quarters()` still calls `_recent_quarters(today.year, today.month,
  num_quarters)`, and `_recent_quarters()` starts at the current calendar
  quarter:
  `backend/app/services/edgar_ingestion.py:912-923`,
  `backend/app/services/edgar_ingestion.py:1105-1115`.

On May 22, 2026, `_recent_quarters()` starts with `2026-Q2`. Under the new
report-quarter model, `ingest_quarter_index("2026-Q2")` fetches `2026-Q3`.
That quarter has not started, so this violates the prompt's future-quarter pass
bar. This also means one caller in A2 is not yet safely passing a usable report
quarter.

### [P1] `historical_backfill` status double-write breaks worker finalization

Evidence:

- `_execute_job()` dispatches `historical_backfill` to
  `execute_historical_backfill(... job_run_id=payload["_job_id"] ...)`:
  `backend/app/services/thirteenf_admin_dashboard.py:3022-3031`.
- The queued worker injects `_job_id`, calls `execute_job_payload()`, then calls
  `complete_leased_job()`:
  `backend/app/services/thirteenf_job_worker.py:305-314`.
- `complete_leased_job()` only completes rows that still match
  `_lease_owner_matches()`, and `_lease_owner_matches()` requires
  `job.status == "running"`:
  `backend/app/services/thirteenf_job_worker.py:191-202`,
  `backend/app/services/thirteenf_job_worker.py:347-355`.
- `execute_historical_backfill()` changes `job.status` to the terminal status
  and commits before returning:
  `backend/app/services/thirteenf_historical_backfill.py:280-284`.

These do not agree. Once `execute_historical_backfill()` commits `succeeded`,
`failed`, or `partial_success`, `complete_leased_job()` returns `None` and does
not set `finished_at`, clear `lease_expires_at`, or apply the worker's summary.
The executor should either leave final `JobRun` completion to the worker, or
the dispatcher should not run it through the normal leased-job completion path.

### [P2] `quality_check` still contains a filing-quarter-only subcheck

Evidence:

- The quarterly pipeline passes the report quarter into the `quality_check`
  stage:
  `backend/app/services/thirteenf_admin_dashboard.py:2849-2855`.
- `run_quality_checks()` calls `_check_period_alignment()` with that same
  quarter:
  `backend/app/services/edgar_quality.py:61-70`.
- `_check_period_alignment()` documents and implements `quarter` as the filing
  quarter: it expects `period_of_report` in the previous quarter and filters
  by `filed_at BETWEEN :f_start AND :f_end`:
  `backend/app/services/edgar_quality.py:306-345`.

Most quality checks use `_quarter_filter()` and scope by `period_of_report`, so
the quality job is partly report-quarter. This one subcheck is still
filing-quarter. It can miss period-alignment anomalies for the requested report
quarter, because those filings are typically filed in the next calendar
quarter.

## Prompt Checklist

### A. F1 + F2 — report-quarter model

1. PASS. `next_quarter_label()` handles Q1->Q2, Q2->Q3, Q3->Q4, and Q4->next
   year Q1. The new parametrized test covers all four cases:
   `backend/tests/unit/test_13f_quarter_model_and_backfill_wiring.py:19-29`.

2. FAIL. `ingest_quarter_index()` now has the right docstring and URL
   translation (`backend/app/services/edgar_ingestion.py:447-460`).
   `_execute_job(fetch_quarter_index)` and `quarterly_pipeline` pass a report
   quarter (`backend/app/services/thirteenf_admin_dashboard.py:2806-2817`,
   `backend/app/services/thirteenf_admin_dashboard.py:2914-2918`).
   However, `backfill_quarters()` still generates current calendar quarters and
   now feeds them into a report-quarter API
   (`backend/app/services/edgar_ingestion.py:912-923`,
   `backend/app/services/edgar_ingestion.py:1105-1115`).

3. PASS. `_form_idx_fetched()` translates the report-quarter window label to
   the next filing quarter before checking the stored `form.idx` URL:
   `backend/app/services/thirteenf_admin_dashboard.py:1732-1744`. That aligns
   with `_quarter_summary()` filtering filings by `period_of_report` within
   the same report-quarter window:
   `backend/app/services/thirteenf_admin_dashboard.py:335-340`.

4. FAIL. Fetch/dashboard/readiness are mostly report-quarter, but I found two
   residual filing-quarter assumptions: `backfill_quarters()` as described
   above, and `edgar_quality._check_period_alignment()` as a subcheck of
   `quality_check`.

5. FAIL. `latest_usable_quarter_label()` itself is safe: it only returns a
   report quarter after that quarter's 45-day filing deadline
   (`backend/app/services/thirteenf_admin_dashboard.py:97-105`), so the
   translated filing quarter has already started. But `backfill_quarters()`
   does not use that gate and can request a future full-index quarter.

### B. F4 — historical_backfill wiring

6. PASS. The real queued worker injects `_job_id` before dispatch:
   `backend/app/services/thirteenf_job_worker.py:305-308`. Direct test callers
   still need to pass it manually, which the new regression test does.

7. PASS with notes. The three dependencies are wired:
   `backend/app/services/thirteenf_admin_dashboard.py:3025-3030`.
   Discovery filters `filing.report_date or filing.filed_at` to the report
   quarter window (`backend/app/services/thirteenf_admin_dashboard.py:3046-3056`);
   per-manager client creation is acceptable for this job's explicit
   per-manager/per-quarter discovery shape. Ingest uses
   `_execute_pipeline_stage_job(... parent_payload={} ...)`, and that function
   tolerates `{}` via `parent_payload.get("_job_id")`
   (`backend/app/services/thirteenf_admin_dashboard.py:3074-3088`,
   `backend/app/services/thirteenf_admin_dashboard.py:3117-3119`).
   Validation returns `(not errors, errors)` as the `ValidationGate` contract
   expects.

8. Advisory. Discovery failure isolation is not present:
   `_execute_quarter()` directly iterates `for meta in filing_discovery_fn(...)`
   (`backend/app/services/thirteenf_historical_backfill.py:315-328`). Whole-job
   fail-and-retry is acceptable only if the product wants a conservative batch
   retry model. For long all-manager historical runs, per-manager isolation
   would give better progress and clearer failure accounting.

9. FAIL. Status double-write is a real conflict; see P1 finding above.

### C. Frontend

10. PASS for code shape; verification not independently rerun. The new controls
    use shared `Button`, the expected job types, and sibling-style disabled
    wiring:
    `frontend/app/(dashboard)/admin/13f/page.tsx:929-936`,
    `frontend/app/(dashboard)/admin/13f/page.tsx:985-1000`.
    I did not rerun `node --test`, lint, or production build during this
    review. The task log reports them green.

### D. Tests

11. FAIL/advisory. An explicit URL-translation test is warranted. The new tests
    prove `next_quarter_label()` and direct dispatch of `historical_backfill`,
    but they do not assert that `ingest_quarter_index("2025-Q4")` fetches
    `/2026/QTR1/form.idx`. The current `backfill_quarters()` miss is exactly
    the kind of caller-level semantic drift such a test would not catch.

### E. Scope / deferred

12. PASS. `docs/BACKLOG.md` contains the F5 test-isolation entry and does not
    show open F1/F2 or F4 entries:
    `docs/BACKLOG.md:12-27`.

## Verification

I did not run the Docker canonical gate as part of this review. The task log
records:

- `pytest -q` — 907 passed on a fresh `valuepilot_test` DB.
- `node --test lib/*.test.js` — 159 passed.
- `npm run lint` — clean.
- `NODE_ENV=production npm run build` — succeeded.

Given the P1 findings above, I would not approve this PR until the
`backfill_quarters()` quarter source and `historical_backfill` job finalization
are corrected and covered by tests.
