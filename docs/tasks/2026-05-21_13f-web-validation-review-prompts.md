# Review prompt — 13F web-validation fixes (report-quarter model, historical_backfill wiring)

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-21_13f-web-validation.md` and the diff on branch.

---

## Reviewer brief

You are reviewing **PR #90**, branch `claude/13f-web-validation`. The changes
came out of an AI-agent validation run that drove the **entire 13F pipeline
from an empty dev DB through the `/admin/13f` web UI**. The run surfaced four
issues; this PR fixes three (F1+F2, F3, F4) and backlogs the fourth (F5). The
bugs *and* the fixes are agent-authored — scrutinise accordingly. The
**F1+F2 quarter-model change is the highest-risk part**; weight your review
there.

No production write happened. No schema change / no migration. All changes are
code + docs.

### What changed and why

- **F1 + F2 — filing-quarter vs report-quarter model.** `ingest_quarter_index(Q)`
  fetched the EDGAR full-index for calendar quarter `Q` (`/{year}/QTR{q}/`). But
  a 13F is filed within 45 days *after* the quarter it reports on, so it is
  indexed under the *following* calendar quarter. Result: requesting report
  quarter `Q` ingested `Q-1`'s holdings, while `_quarter_summary` /
  `latest_usable_quarter_label` / readiness / tasks all key on
  `period_of_report` (the report quarter). The Readiness checklist showed
  "blocked" after a fully successful ingest, and a false
  `QUARTER_INDEX_FETCHED_NO_FILINGS` task fired. Fix: new `next_quarter_label()`;
  `ingest_quarter_index` and `_form_idx_fetched` translate the report quarter to
  the following filing quarter.
- **F3 — no loop CUSIP-enrichment control.** The Quarter Pipeline's only enrich
  button (`enrich_metadata`) does one 100-record batch. Added an "Enrich all
  CUSIPs" button for the pre-existing loop-to-completion `enrich_cusip` job.
- **F4 — Historical Backfill never executed.** `enqueue_historical_backfill`
  creates a `historical_backfill` JobRun, but `_execute_job` had no branch for
  it — every run failed `Unsupported job_type`. Wired
  `execute_historical_backfill` into the dispatcher with three production
  dependencies.
- Added an "Oracle's Lens score" button — `oracles_lens_score_backfill` had no
  web control at all.

### Files in scope

- `backend/app/edgar/parsers/form_idx.py` — new `next_quarter_label()`.
- `backend/app/services/edgar_ingestion.py` — `ingest_quarter_index` translation.
- `backend/app/services/thirteenf_admin_dashboard.py` — `_form_idx_fetched`
  translation; `historical_backfill` dispatch branch + three dependency
  functions (`_historical_backfill_filing_discovery` / `_ingest` /
  `_validation_gate`).
- `frontend/app/(dashboard)/admin/13f/page.tsx` — "Enrich all CUSIPs" and
  "Oracle's Lens score" buttons.
- `backend/tests/unit/test_13f_quarter_model_and_backfill_wiring.py` — new.
- `docs/tasks/2026-05-21_13f-web-validation.md`, `docs/BACKLOG.md`.

### Baseline

`git diff main...HEAD`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + evidence

### A. F1 + F2 — report-quarter model — MANDATORY

1. **`next_quarter_label` correctness.** Q1→Q2, Q2→Q3, Q3→Q4, and the
   Q4→Q1 **year rollover**. Confirm the unit test covers all four.
2. **`ingest_quarter_index` semantic shift.** It now fetches
   `next_quarter_label(quarter)`'s `/{year}/QTR{q}/` index. Confirm `quarter` is
   now unambiguously a *report* quarter and the docstring says so. **Trace every
   caller** of `ingest_quarter_index` (the `_execute_job` `fetch_quarter_index`
   branch, `backfill_quarters` in `edgar_ingestion.py`, the `quarterly_pipeline`
   index stage) and confirm each passes a report quarter — i.e. no caller
   double-shifts, and none still assumes the old filing-quarter behaviour.
3. **`_form_idx_fetched` alignment.** It now checks the
   `next_quarter_label(window.label)` QTR path. Confirm this is consistent with
   the same `_quarter_summary`'s `filings` filter (`period_of_report` within the
   report-quarter window) — the two must refer to the same quarter concept, or
   the `QUARTER_INDEX_FETCHED_NO_FILINGS` task mis-fires again.
4. **No residual filing-quarter assumption.** Grep the 13F surfaces for other
   places that build an EDGAR `QTR{n}` URL or a quarter from `period_of_report`
   vs a label. Confirm fetch, dashboard, readiness and tasks are now uniformly
   report-quarter.
5. **Future-quarter edge case.** For the latest usable report quarter,
   `next_quarter` is the current (partially-elapsed) calendar quarter — EDGAR's
   `/{year}/QTR{q}/form.idx` exists and updates during a quarter. Confirm
   `latest_usable_quarter_label`'s deadline gate means you never request an
   index for a calendar quarter that has not started.

### B. F4 — historical_backfill wiring — MANDATORY

6. **`job_run_id` source.** The branch passes `job_run_id=payload["_job_id"]`.
   Confirm the worker always injects `_job_id` into the payload for a queued job
   (compare the `quality_check` / `oracles_lens_score_backfill` branches, which
   read `payload.get("_job_id")`). A missing key would `KeyError`.
7. **The three production dependencies.**
   - `_historical_backfill_filing_discovery` — opens a new `EdgarClient` per
     `(manager, quarter)` call and filters submissions by
     `window.start <= report_date <= window.end`. Confirm the filter is correct
     and the per-call client open is acceptable (one submissions fetch per
     tracked manager per quarter).
   - `_historical_backfill_ingest` — calls `_execute_pipeline_stage_job` with
     `parent_payload={}`. Confirm `{}` is tolerated and the status mapping
     (`succeeded` / `partial_success` → `succeeded`, else `failed`) is right.
   - `_historical_backfill_validation_gate` — wraps `run_quality_checks`.
     Confirm `(passed, errors)` matches the `ValidationGate` contract.
8. **Robustness — discovery failure isolation.** If `filing_discovery_fn`
   raises for one manager (transient EDGAR error), `_execute_quarter`'s
   `for meta in filing_discovery_fn(...)` propagates and fails the whole
   `historical_backfill` job. Decide whether per-manager isolation is needed
   or whether whole-job-fail-and-retry is acceptable (the job is retryable).
9. **Status double-write.** `execute_historical_backfill` commits the session
   and sets `job.status` itself, then the worker also sets status from the
   return dict. Confirm these agree and there is no conflict.

### C. Frontend — F3 + scoring button

10. The two new controls in `page.tsx` use the shared `Button`, the correct
    `job_type` (`enrich_cusip`, `oracles_lens_score_backfill`), and
    `isJobActive` / `disabled` wiring consistent with the sibling buttons.
    Confirm `lib/uiStandard.test.js`, lint and the production build are green.

### D. Tests

11. Review `test_13f_quarter_model_and_backfill_wiring.py`. Note the gap: no
    test asserts `ingest_quarter_index` actually requests the *translated* URL —
    F2's URL translation rests on the `next_quarter_label` unit test plus the
    (unchanged, still-green) existing callers in `test_oracles_lens_score_job.py`
    / `test_smart_retries.py` / `test_13f_admin_dashboard.py`. Decide whether an
    explicit `ingest_quarter_index` URL-translation test is warranted.

### E. Scope / deferred

12. Confirm `docs/BACKLOG.md`: the F1/F2 and F4 entries added mid-task are
    **removed** (resolved by this PR), and the F5 entry (test suite not isolated
    from dev-DB data) is present.

## Verification

```
docker compose exec -T api pytest -q          # 907 passed on a FRESH DB
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Caveat (F5): `pytest -q` assumes a fresh DB. After any web use of the dev
stack, `test_13f_admin_dashboard.py` fails on a `job_runs` FK during fixture
cleanup — data, not code. Verify on a fresh DB (a clean `valuepilot_test` with
`alembic upgrade head`), as real CI does.

## Pass bar

Approve only if: **A1–A5** confirm the report-quarter translation is correct,
applied at every relevant point, and has no residual filing-quarter assumption
or future-quarter 404 risk; **B6–B9** confirm `historical_backfill` is wired
correctly and its failure modes are understood; **C/D/E** findings recorded.
The bar is: "a report quarter `Q` typed into the UI now ingests, summarises,
scores and reports on `Q`'s actual holdings — consistently — and the Historical
Backfill job executes instead of failing `Unsupported job_type`."
