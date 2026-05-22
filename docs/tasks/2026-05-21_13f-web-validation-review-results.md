# Review results — 13F web-validation fixes (PR #90)

Branch: `claude/13f-web-validation`  
Reviewer: external agent (claude-sonnet-4-6)  
Date: 2026-05-22

---

## Overall recommendation: APPROVE

All mandatory questions (A1–A5, B6–B9) pass or carry only low-severity
advisories. The report-quarter translation is correct, applied consistently, and
has no residual filing-quarter assumption or future-quarter 404 risk. The
`historical_backfill` dispatcher is wired correctly. Frontend, tests, and
backlog scope are clean.

---

## A. F1 + F2 — report-quarter model

### A1 — `next_quarter_label` correctness: PASS

`backend/app/edgar/parsers/form_idx.py` lines 117–122:

```python
def next_quarter_label(quarter: str) -> str:
    """'2025-Q4' → '2026-Q1'. The calendar quarter immediately after `quarter`."""
    year, qtr = quarter_to_year_qtr(quarter)
    if qtr >= 4:
        return f"{year + 1}-Q1"
    return f"{year}-Q{qtr + 1}"
```

Logic: `qtr >= 4` (not `== 4`) handles malformed input defensively; the year
rollover branch is correct. `test_next_quarter_label` in
`test_13f_quarter_model_and_backfill_wiring.py` covers all four cases:
`2025-Q1→Q2`, `2025-Q2→Q3`, `2025-Q3→Q4`, `2025-Q4→2026-Q1` (year rollover).

### A2 — `ingest_quarter_index` semantic shift: PASS

`edgar_ingestion.py` lines 447–460: the docstring now explicitly states
"`quarter` is a **report quarter**" and explains the 45-day offset. The
translation `filing_quarter = next_quarter_label(quarter)` is the first
statement in the function body, so no caller can accidentally get the old
behavior.

Callers traced:

1. **`fetch_quarter_index` branch in `_execute_job`** (`thirteenf_admin_dashboard.py`
   line 2914–2918): receives `quarter` from `_required(payload, "quarter")`.
   The payload originates from the web UI's "target quarter" field, which is a
   report-quarter label. No shift on the way in.

2. **`quarterly_pipeline` index stage** (`thirteenf_admin_dashboard.py` line
   2807–2816): passes `payload["quarter"]` straight through from the parent
   job's `quarter` field, which is also set by the user as a report quarter.
   No double-shift.

3. **`backfill_quarters`** (`edgar_ingestion.py` lines 912–927): calls
   `_recent_quarters(today.year, today.month, num_quarters)`. `_recent_quarters`
   returns current calendar quarter labels derived from `today` — these are
   report-quarter labels (a report quarter is defined by the period its holdings
   cover, which aligns with the calendar quarter). No double-shift.

No caller passes a pre-translated filing quarter.

### A3 — `_form_idx_fetched` alignment: PASS

`_form_idx_fetched` (`thirteenf_admin_dashboard.py` lines 1732–1746) now
computes `filing_year, filing_qtr = quarter_to_year_qtr(next_quarter_label(window.label))`
and filters `RawSourceDocument.source_url.contains(f"/{filing_year}/QTR{filing_qtr}/")`.

`_quarter_summary` (line 1462) filters `Filing13F.period_of_report.between(window.start, window.end)`
where `window = quarter_window(quarter)` — a report-quarter window. Since
`period_of_report` is the report-quarter end date stored on each filing, this
filter correctly selects Q's holdings.

Both now use the same quarter concept: `_form_idx_fetched` asks "was the EDGAR
full-index for the *following* filing quarter fetched?", while `_quarter_summary`
counts filings whose `period_of_report` falls in the *report* quarter Q. These
are consistent — the following-quarter index is exactly where Q's 13Fs appear.
The false `QUARTER_INDEX_FETCHED_NO_FILINGS` task can no longer misfire.

### A4 — No residual filing-quarter assumption: PASS

All EDGAR-URL-constructing call sites examined:

- `form_idx_url` is called in `edgar_ingestion.ingest_quarter_index` only, after
  the `next_quarter_label` translation (line 460). Correct.
- `_form_idx_fetched` uses `next_quarter_label` to derive the URL path. Correct.
- `daily_form_idx_url` (`form_idx.py` line 129) is used by `thirteenf_daily_sync`;
  it takes an absolute `sync_date`, not a quarter label, so it is unaffected.
- CLI (`app/cli/edgar.py`) and scheduler endpoint (`app/api/v1/endpoints/scheduler.py`)
  use `quarter_to_year_qtr` only to compute date bounds for `period_of_report`
  filtering, never to build an EDGAR URL. These are report-quarter operations
  that remain correct.
- `app/services/scheduler.py` line 67 similarly uses `quarter_to_year_qtr` to
  compute date ranges for `Filing13F.period_of_report`, not for URL construction.

No residual filing-quarter assumption found in fetch, dashboard, readiness, or
tasks paths.

### A5 — Future-quarter edge case: PASS

`latest_usable_quarter_label` (`thirteenf_admin_dashboard.py` lines 97–105)
only returns a quarter `Q` when `today >= window.deadline`, where
`window.deadline = quarter_end + timedelta(days=45)` (line 82). Therefore
`next_quarter_label(Q)` refers to a calendar quarter that starts at the
beginning of the month following Q's end — which is at least 45 days before
today, meaning that quarter has already started and its EDGAR full-index has been
open for at least 45 days. EDGAR updates `form.idx` continuously during a
quarter, so it will always exist. No risk of requesting a non-existent future
index.

---

## B. F4 — historical_backfill wiring

### B6 — `job_run_id` source: PASS (with minor advisory)

`thirteenf_job_worker.py` lines 306–307 always inject `payload["_job_id"] = job.id`
before calling `execute_job_payload`. The historical_backfill branch uses
`payload["_job_id"]` (bracket access, line 3027) rather than `.get("_job_id")`
as used by `quality_check` (line 2888) and `oracles_lens_score_backfill`
(line 3009).

**Advisory (low):** The bracket access is safe when the job is dispatched
through the worker because the worker always injects `_job_id`. However the
mismatch with sibling branches (which use `.get`) is a minor inconsistency.
The test at line 43 of `test_13f_quarter_model_and_backfill_wiring.py` passes
`{"_job_id": job.id}` explicitly, confirming this path. No production risk since
the worker path guarantees injection.

### B7 — Three production dependencies: PASS

**`_historical_backfill_filing_discovery`** (`thirteenf_admin_dashboard.py` lines
3035–3068): Opens a single `EdgarClient` context per `(manager, quarter)` call
and fetches that manager's SEC submissions. Filter:
`window.start <= report_date <= window.end` where `report_date = filing.report_date or filing.filed_at`.
The fallback to `filed_at` is the cautious choice (using a filing date as a
proxy when `report_date` is absent); it could include a filing whose actual
`period_of_report` is slightly outside the window, but that is the existing
convention across the codebase. The `with EdgarClient() as client:` pattern
opens and closes one connection per call — one HTTP request per manager per
quarter. For a typical backfill of ~70 managers over several quarters this is a
large number of connections but is functionally correct and matches the pattern
used elsewhere (rate-limiting is handled by Rate Guard).

**`_historical_backfill_ingest`** (lines 3070–3092): calls
`_execute_pipeline_stage_job(session, parent_payload={}, job_type="ingest_accession", ...)`.
`parent_payload={}` is tolerated: `_execute_pipeline_stage_job` only reads
`parent_payload.get("_job_id")` (line 3117), which returns `None` on `{}`,
so the stage job's `parent_job_id` is `None`. This means the sub-job will not
be linked to the parent historical_backfill job in the UI, but it is functionally
correct. Status mapping: `stage["status"] in {"succeeded", "partial_success"}` →
`"succeeded"`, else `"failed"` — consistent with the worker's own
`succeeded`/`partial_success` acceptance in `complete_leased_job`.

**`_historical_backfill_validation_gate`** (lines 3095–3101): returns
`(not errors, errors)` where `errors: list[str]`. The `ValidationGate` type
alias is `Callable[[Session, str, list[dict[str, Any]]], tuple[bool, list[str]]]`.
This matches exactly. `report.errors` is `list[QualityIssue]`; the list
comprehension `[getattr(issue, "detail", None) or str(issue) for issue in report.errors]`
safely extracts the string detail. Correct.

### B8 — Robustness — discovery failure isolation: advisory

`_execute_quarter` (`thirteenf_historical_backfill.py` line 328) iterates
`for meta in filing_discovery_fn(manager, quarter):` with no try/except. If
`_historical_backfill_filing_discovery` raises a network error (e.g., EDGAR
rate-limit or transient timeout) for any manager, the exception propagates
uncaught through `_execute_quarter`, through the `for quarter in quarters:` loop
in `execute_historical_backfill`, and to the worker's outer try/except, which
marks the whole job `failed`.

**Advisory (low):** Per-manager isolation would allow the job to continue and
record failures per manager rather than aborting the whole run. The job is
retryable (the existing filing-present check skips already-ingested managers),
so whole-job-fail-and-retry is a viable strategy. A one-quarter backfill through
the web UI (the validated use case) is low-risk here. For a multi-quarter
production backfill over 70 managers, a transient EDGAR error in early managers
would waste all work done so far. Consider wrapping the
`filing_discovery_fn(manager, quarter)` call in a try/except that catches
network/HTTP errors and records them as `failed` entries rather than aborting.
This is a follow-up improvement, not a blocker.

### B9 — Status double-write: PASS (with minor advisory)

`execute_historical_backfill` sets `job.status = overall` and commits at line 284.
The worker then calls `complete_leased_job(..., status=summary.pop("status", "succeeded"), ...)`
which sets `job.status = status` a second time. Both write the same value (`overall`),
so the final DB state is correct.

**Advisory (low):** The two commits also write to `job.summary_json` with
slightly different shapes. `execute_historical_backfill` commits
`{"scope": {...}, "impact_summary": {...}, "per_quarter": [...]}` (line 282).
The worker's `complete_leased_job` then overwrites `summary_json` with the
function's return dict minus `status`:
`{"job_run_id": ..., "impact_summary": ..., "per_quarter": ..., "scope": {...}}`.
These carry the same data in slightly different top-level key arrangements.
The overwrite is benign; the dashboard reads from this `summary_json` and the
final shape is consistent. The double-commit pattern is pre-existing
(identical to `enqueue_historical_backfill`'s comment at line 278). No conflict.

---

## C. Frontend

### C10 — Two new buttons: PASS

Both new controls in `frontend/app/(dashboard)/admin/13f/page.tsx` use the
shared `Button` component (imported from `@/components/ui/button`, line 37).

**"Enrich all CUSIPs"** (lines 929–936):
- `job_type: 'enrich_cusip'` — matches the pre-existing `enrich_cusip` job
  registered in `_JOB_LOCK_BUILDERS` and `_execute_job`.
- `disabled={isJobActive({ job_type: 'enrich_cusip' })}` — consistent with the
  sibling "Bootstrap stocks" button which also does not require a `targetQuarter`.
  `enrich_cusip` is a global job (no quarter scope), so omitting `quarter` is
  correct.

**"Oracle's Lens score"** (lines 985–999):
- `job_type: 'oracles_lens_score_backfill'` with `quarter: targetQuarter` —
  correct.
- `disabled={!targetQuarter || isJobActive({ job_type: 'oracles_lens_score_backfill', quarter: targetQuarter })}` —
  consistent with "Fetch quarter index", "Ingest holdings", etc., all of which
  guard on `!targetQuarter`.
- Both use `variant="outline"`, `type="button"`, and `onClick` with `runJob()` —
  identical pattern to all sibling buttons.

The task doc reports frontend unit tests, lint, and production build all green.
The `uiStandard.test.js` scanner forbids raw HTML form/control primitives;
the two new buttons use the shared `Button` component and would not trigger that
scanner.

---

## D. Tests

### D11 — Test coverage gap: advisory

`test_13f_quarter_model_and_backfill_wiring.py` covers:
1. All four `next_quarter_label` cases (pure unit test, no DB).
2. That `execute_job_payload` routes `historical_backfill` without raising
   `Unsupported job_type` (the regression that F4 fixed).

**Gap noted in review brief:** No test asserts that `ingest_quarter_index`
actually requests the translated (filing-quarter) URL. The F2 URL-translation
rests on:
- The `next_quarter_label` unit test (covers the translation function itself).
- The docstring change and code inspection (the function body is two lines and
  straightforward).
- Existing tests (`test_oracles_lens_score_job.py`, `test_smart_retries.py`,
  `test_13f_admin_dashboard.py`) exercise the broader ingestion path.

**Advisory (low):** An explicit test of `ingest_quarter_index` that mocks
`fetch_and_store` and asserts the URL passed is the filing-quarter URL would
make F2's regression bar crisp and self-documenting. Given the simplicity of
the translation (two lines), the existing `next_quarter_label` unit test is a
reasonable proxy, but the direct URL-translation test would be more robust as a
regression guard.

---

## E. Scope / deferred

### E12 — `docs/BACKLOG.md`: PASS

Confirmed:

- No F1/F2 or F4 entries exist in `docs/BACKLOG.md`. These were resolved in
  this PR; the backlog contains no stale entries for them.
- The F5 entry ("13F test suite is not isolated from dev-database data") is
  present as the first entry in the Open section (lines 12–27), with correct
  context, severity (low), and link to the task doc.

---

## Summary of verdicts

| Question | Area | Verdict |
|---|---|---|
| A1 | `next_quarter_label` correctness | PASS |
| A2 | `ingest_quarter_index` callers | PASS |
| A3 | `_form_idx_fetched` alignment | PASS |
| A4 | No residual filing-quarter assumption | PASS |
| A5 | Future-quarter edge case | PASS |
| B6 | `_job_id` source | PASS (minor advisory: bracket vs `.get`) |
| B7 | Three production dependencies | PASS |
| B8 | Discovery failure isolation | advisory (low: no per-manager try/except) |
| B9 | Status double-write | PASS (minor advisory: two `summary_json` commits) |
| C10 | Frontend buttons | PASS |
| D11 | Test coverage gap | advisory (low: no URL-translation test for `ingest_quarter_index`) |
| E12 | BACKLOG entries | PASS |

**Overall: APPROVE**

The three low-severity advisories (B6 bracket access, B8 no per-manager
discovery isolation, D11 missing URL-translation test) are worth a follow-up
but none blocks merge. The highest-risk change — the F1/F2 report-quarter
model — is correct, consistently applied, and confirmed by four unit tests plus
inspection of every caller. The feature bar is met: a report quarter Q entered
in the UI now ingests, summarises, scores, and reports on Q's actual holdings;
the Historical Backfill job executes instead of failing `Unsupported job_type`.
