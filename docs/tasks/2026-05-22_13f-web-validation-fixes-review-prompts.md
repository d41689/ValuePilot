# Review prompt — 13F web-validation review-round-1 fixes

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-21_13f-web-validation.md` and the diff on branch.

---

## Reviewer brief

You are re-reviewing **PR #90**, branch `claude/13f-web-validation`. An earlier
review (`docs/tasks/2026-05-22_13f-web-validation-review.md`) returned **FAIL**
with two P1s and one P2; a second review
(`docs/tasks/2026-05-21_13f-web-validation-review-results.md`) returned APPROVE.
This round of commits addresses the **FAIL**. Your job: confirm the two P1s are
genuinely fixed, the P2 deferral is recorded, and nothing new regressed. The
fixes are agent-authored — scrutinise accordingly.

No production write, no schema change, no migration.

### What changed in this round

- **R-P1a — `backfill_quarters()` could request a not-yet-started filing
  quarter.** It enumerated quarters from the *current calendar quarter* via
  `_recent_quarters(today.year, today.month, n)`. After the F1/F2 fix,
  `ingest_quarter_index` treats its arg as a *report* quarter and fetches the
  *following* calendar quarter's EDGAR full-index — so the current quarter
  mapped to a full-index quarter that has not started. Fix:
  `backfill_quarters` now walks back from `latest_usable_quarter_label()` using
  `previous_quarter_label()`.
- **R-P1b — `historical_backfill` status double-write.**
  `execute_historical_backfill()` committed a terminal `JobRun` status itself.
  The worker then calls `complete_leased_job()`, whose lease check requires
  `status == "running"` — so it no-op'd, leaving `finished_at` and
  `lease_expires_at` unset (observed live: the job detail showed FINISHED "—").
  Fix: the executor no longer writes the terminal status; it commits the
  per-quarter work and returns `status` for the caller (the worker) to finalize.
- **R-P2 — `_check_period_alignment()` still filing-quarter** — backlogged, not
  fixed (non-blocking; needs a rethink under the report-quarter model).
- Two regression tests added.

### Files in scope

- `backend/app/services/edgar_ingestion.py` — `backfill_quarters` quarter source.
- `backend/app/services/thirteenf_historical_backfill.py` —
  `execute_historical_backfill` no longer finalizes the `JobRun`.
- `backend/tests/unit/test_13f_quarter_model_and_backfill_wiring.py` — 2 new tests.
- `docs/tasks/2026-05-21_13f-web-validation.md`, `docs/BACKLOG.md`.

### Baseline

`git diff main...HEAD`. Compare against the round-1 review
`docs/tasks/2026-05-22_13f-web-validation-review.md`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + evidence

### A. R-P1a — `backfill_quarters` quarter source — MANDATORY

1. **No future filing quarter.** `backfill_quarters` walks back from
   `latest_usable_quarter_label()`. Confirm that for every report quarter it
   yields, `next_quarter_label(q)` (the filing quarter `ingest_quarter_index`
   actually fetches) is ≤ the current calendar quarter — i.e. that EDGAR
   full-index always exists. The deadline gate inside
   `latest_usable_quarter_label` is what guarantees this; confirm the reasoning.
2. **Circular import.** `backfill_quarters` (in `edgar_ingestion.py`)
   function-locally imports `latest_usable_quarter_label` /
   `previous_quarter_label` from `thirteenf_admin_dashboard.py`. Confirm this
   runtime import is safe (no import cycle at module load).
3. **CLI.** `app/cli/edgar.py` `backfill` — step 1 calls the fixed
   `backfill_quarters` (inherits the fix); step 2 still uses `_recent_quarters`
   but only to scan local rows by `period_of_report` (no EDGAR fetch). Confirm
   step 2 is harmless and `_recent_quarters` is not otherwise misused.

### B. R-P1b — `historical_backfill` finalization — MANDATORY

4. **Worker finalizes.** `execute_historical_backfill` no longer sets
   `job.status` / `job.summary_json`; it commits and returns
   `{"status": ..., ...}`. Confirm the worker path now works end to end:
   `_execute_job` returns that dict → `complete_leased_job` sees the row still
   `running` → sets terminal status, `finished_at`, clears `lease_expires_at`,
   writes `summary_json`.
5. **Direct callers unaffected.** `execute_historical_backfill` is also called
   directly by `test_13f_mvp3_historical_backfill.py` (20 tests). Confirm those
   assert the **return dict** (`result["impact_summary"]`, …) and DB findings —
   not `job.status` — so dropping the status write does not break them.
6. **`summary_json` content.** The executor no longer builds `summary_payload`;
   the worker stores `summary_json = <return dict minus status>`
   (`job_run_id`, `impact_summary`, `per_quarter`, `scope`). Confirm that is an
   adequate summary and nothing depended on the old shape.
7. **Per-quarter durability.** The executor still calls `session.commit()` so
   per-quarter `QualityReport13F` / `QualityFinding13F` rows are durable with
   the job row left `running`. Confirm no per-quarter work is lost.

### C. Regression tests

8. Review the two new tests in
   `test_13f_quarter_model_and_backfill_wiring.py`. Confirm each would **fail
   against the pre-fix code**: `test_backfill_quarters_does_not_request_a_future_filing_quarter`
   (pre-fix `_recent_quarters` yields the current quarter →
   `next_quarter_label` future), and
   `test_historical_backfill_executor_leaves_job_for_caller_to_finalize`
   (pre-fix the executor set a terminal `job.status`).

### D. R-P2 deferral

9. Confirm `docs/BACKLOG.md` has the `_check_period_alignment` entry and the
   task log records R-P2 as deferred with a reason — not silently dropped.

### E. No new regressions

10. Confirm no other caller of `backfill_quarters` or
    `execute_historical_backfill` is broken by these changes. `pytest -q` —
    909 passed on a fresh DB (was 907 pre-round; +2 new tests).

## Verification

```
docker compose exec -T api pytest -q          # 909 passed on a FRESH DB
```

Caveat unchanged from round 1 (F5): `pytest` assumes a fresh DB; run it against
a clean `valuepilot_test` (`alembic upgrade head`), as real CI does.

## Pass bar

Approve only if **A1–A3** confirm `backfill_quarters` can no longer request a
future EDGAR full-index, **B4–B7** confirm `historical_backfill` jobs are now
finalized by the worker (status + `finished_at` + lease) with no lost
per-quarter work and no broken direct callers, and **C/D/E** are satisfied. The
bar is: "the two round-1 P1 regressions are gone, covered by tests that would
catch them, and the P2 is on the backlog."
