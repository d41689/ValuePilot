# Re-review results — Filing13F.parse_status failure-path durability

Reviewed branch: `claude/13f-filing-parse-status`

Baseline: `git diff main...HEAD`

Prior review: `docs/tasks/2026-05-22_13f-filing-parse-status-review-results.md`

## Overall Verdict

APPROVE. The prior blocker is fixed. `_do_ingest_holdings()` now commits the
failed `ParseRun13F` plus `filing.parse_status = "failed"` before re-raising,
so the admin bulk ingest caller's later `session.rollback()` no longer discards
the failure audit/status.

I found no remaining blocking issue in the reviewed scope. I did not rerun the
Docker test suite during this re-review.

## Prior Blocker

### Failed bulk ingest rollback durability — PASS

Evidence:

- On parse failure, `_do_ingest_holdings()` rolls back the in-progress ingest
  savepoint, writes a failed `ParseRun13F`, sets `filing.parse_status =
  "failed"`, and now calls `session.commit()` before re-raising:
  `backend/app/services/thirteenf_holdings_ingest.py:244-275`.
- The product caller still does `session.rollback()` on per-filing exceptions:
  `backend/app/services/thirteenf_admin_dashboard.py:3346-3350`, but that
  rollback now happens after the failure audit/status commit.
- `test_failed_ingest_marks_filing_parse_status_failed` now mimics that caller
  rollback and reloads the filing from the database before asserting
  `"failed"`:
  `backend/tests/unit/test_13f_parse_run_audit.py:360-382`.

This test would fail against the pre-fix code because the SAVEPOINT-released
failure row/status would be rolled back by the caller-style rollback.

## Prompt Checklist

### A. Success path

1. PASS. Success still sets `filing.parse_status = "succeeded"` and adds the
   filing in the Phase-2 success block; `"succeeded"` is allowed by
   `FILING_PARSE_STATUSES`.

2. PASS. No competing production writer was found that also mirrors holdings
   ingest success to `Filing13F.parse_status`.

### B. Failure path

3. PASS. The failure block now makes the failed audit/status durable via
   `session.commit()` before re-raise, so the subsequent bulk-caller rollback
   does not undo it.

4. PASS. Failed reparse still restores the prior current succeeded run and
   flips the filing back to `"succeeded"` before committing:
   `backend/app/services/thirteenf_holdings_ingest.py:358-372`.

### C. Self-heal

5. PASS. The skip branch still reconciles stale status and flushes:
   `backend/app/services/thirteenf_holdings_ingest.py:409-417`.

6. PASS. Self-heal still only runs after finding a current succeeded
   `ParseRun13F`, so it cannot promote a filing without a good current run.

### D. Tests

7. PASS. The four regression tests cover success, durable failed ingest,
   skip-path heal, and failed-reparse restoration. The failed ingest test now
   covers the previously missed rollback behavior.

### E. No regression

8. PASS. The new writes are consistent with existing consumers:
   readiness benefits from `"succeeded"`, health counts `"failed"` /
   `"needs_review"`, and filing-detail routing already uses `"needs_review"` /
   `"failed"`.

## Notes

- `failed_run_saved` remains assigned but unused in
  `thirteenf_holdings_ingest.py`; this is pre-existing/local cleanup, not a
  blocker.
- The failure-path commit mirrors the existing success-path per-filing commit.
  It does commit any pending work in the session, but the admin bulk ingest
  phases already use explicit commit barriers before Phase 3, and the success
  path already has the same per-filing commit behavior.

## Verification

Not run in this re-review. The developer reports:

- `pytest -q` — 913 passed on a fresh DB.
