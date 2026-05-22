# Re-review 2 — 13F web-validation review fixes

Reviewed branch: `claude/13f-web-validation`

Baseline: `git diff main...HEAD`

Prior review: `docs/tasks/2026-05-22_13f-web-validation-fixes-rereview.md`

## Overall Verdict

APPROVE. The round-2 blocker is fixed: CLI `edgar backfill` now uses the exact
quarter set returned by `backfill_quarters()` for both the index phase and the
holdings-ingestion phase.

I found no remaining blocking issue in the reviewed scope. I did not rerun the
Docker test suite during this review.

## Findings

No blocking findings.

## Round-2 Blocker

### CLI `backfill` quarter-set mismatch — PASS

The previous re-review failed because Step 1 indexed latest usable report
quarters while Step 2 independently rebuilt a current-calendar-quarter list.
That drift is gone.

Evidence:

- `backfill_quarters()` enumerates latest usable report quarters from
  `latest_usable_quarter_label()` and returns the result dict keyed by those
  quarters:
  `backend/app/services/edgar_ingestion.py:912-940`.
- CLI Step 2 now iterates `for quarter in results`, so it scans holdings for
  the same report quarters Step 1 indexed:
  `backend/app/cli/edgar.py:214-240`.
- `_recent_quarters()` was removed from `edgar_ingestion.py`; `rg` finds no
  remaining code references, only historical review/prompt docs.

This addresses the May 22, 2026 example from the prior review: Step 1 and Step
2 now both use `2026-Q1`, `2025-Q4`, `2025-Q3`, `2025-Q2` for `quarters=4`
rather than drifting into `2026-Q2`.

## Original P1 Fixes

### `backfill_quarters()` future filing-quarter risk — PASS

`backfill_quarters()` still starts from `latest_usable_quarter_label()` and
walks backward with `previous_quarter_label()`. Because latest usable report
quarter is gated by the 45-day filing deadline, the filing quarter fetched by
`ingest_quarter_index()` has already started.

### `historical_backfill` worker finalization — PASS

`execute_historical_backfill()` still leaves the `JobRun` terminal status to
the caller/worker and returns `status` in the result dict. This preserves the
worker path where `complete_leased_job()` sees the row as `running`, sets the
terminal status, writes `finished_at`, clears `lease_expires_at`, and stores
the summary.

## Deferred P2

PASS. `_check_period_alignment()` remains deferred in `docs/BACKLOG.md` with
context and severity. That is acceptable under the prior pass bar.

## Tests

Not run in this re-review. The task log reports:

- Backend `pytest -q` — 909 passed on a fresh `valuepilot_test` DB.
- Frontend unit tests, lint, and production build — green.

One coverage note: there is still no dedicated CLI harness test for `edgar
backfill`, but the implementation now shares the Step 1 `results` object by
construction, so the specific quarter-list drift no longer has a second list to
diverge.
