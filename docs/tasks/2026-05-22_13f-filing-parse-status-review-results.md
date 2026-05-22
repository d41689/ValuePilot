# Review results — Filing13F.parse_status advance-on-ingest fix

Reviewed branch: `claude/13f-filing-parse-status`

Baseline: `git diff main...HEAD`

Prompt: `docs/tasks/2026-05-22_13f-filing-parse-status-review-prompts.md`

## Overall Verdict

FAIL. The success path, skip-path self-heal, and failed-reparse restoration are
implemented in the right places. However, the first-ingest failure path does
not survive the real `/admin/13f` bulk ingest caller: `_do_ingest_holdings()`
writes `filing.parse_status = "failed"` inside a nested SAVEPOINT, then raises;
the bulk caller catches the exception and calls `session.rollback()`, which
rolls back the failed parse-run audit row and the filing status update.

That means the pass bar is not met: a failed ingest in the admin pipeline still
does not reliably report `failed`.

## Findings

### [P1] Failed bulk ingest rolls back the new `failed` parse_status

Evidence:

- `_do_ingest_holdings()` rolls back the in-progress parse SAVEPOINT after an
  exception, then opens a new nested transaction to add a failed `ParseRun13F`
  and set `filing.parse_status = "failed"`:
  `backend/app/services/thirteenf_holdings_ingest.py:244-268`.
- That nested transaction is only a SAVEPOINT release. Unlike the success path,
  there is no outer `session.commit()` before the function re-raises:
  success commits at `backend/app/services/thirteenf_holdings_ingest.py:231-232`,
  failure re-raises after the nested block without committing.
- The real quarterly ingest loop catches per-filing exceptions and immediately
  calls `session.rollback()`:
  `backend/app/services/thirteenf_admin_dashboard.py:3335-3350`.

So in the product path, a failed first ingest does not keep the failed
`ParseRun13F` or `Filing13F.parse_status = "failed"` write. The new unit test
`test_failed_ingest_marks_filing_parse_status_failed` calls
`ingest_holdings_for_filing()` directly and never rolls back, so it does not
cover the real caller behavior.

The fix should make the failure audit/status write durable before the exception
reaches a caller that rolls back, or change the caller contract so it does not
rollback those intentionally persisted per-filing failure records.

## Prompt Checklist

### A. Success path

1. PASS. `_do_ingest_holdings()` sets `filing.parse_status = "succeeded"` and
   `session.add(filing)` in the Phase-2 success block:
   `backend/app/services/thirteenf_holdings_ingest.py:199-211`. The success
   path commits at lines 231-232. `"succeeded"` is in
   `FILING_PARSE_STATUSES`, and the model validator enforces that whitelist:
   `backend/app/models/institutions.py:45`,
   `backend/app/models/institutions.py:414-416`.

2. PASS with scope note. The changed holdings-ingest service is the only
   production writer I found that mirrors `Filing13F.parse_status` to
   `"succeeded"`. Other production writers set `"pending"`, `"needs_review"`,
   or `"failed"` for filing-detail/routing cases; tests and fixtures also
   create rows with `"succeeded"`. No competing production success writer is
   apparent.

### B. Failure path

3. FAIL. The `filing` object is usable after `sp.rollback()` in the direct
   helper path, and `ingest_holdings_for_filing()` itself does not call
   rollback. But the failed status is only written inside a nested transaction
   and not committed before re-raise. The real admin bulk ingest caller catches
   the exception and calls `session.rollback()`, so the `"failed"` status does
   not survive in the product path:
   `backend/app/services/thirteenf_admin_dashboard.py:3346-3350`.

4. PASS. Failed reparse is handled: `_do_ingest_holdings()` first sets
   `"failed"`, then `reparse_accession()` restores the prior current run and,
   when `restored.status == "succeeded"`, sets the filing back to
   `"succeeded"` before committing:
   `backend/app/services/thirteenf_holdings_ingest.py:351-365`. The new
   `test_failed_reparse_keeps_filing_parse_status_succeeded` covers this:
   `backend/tests/unit/test_13f_parse_run_audit.py:402-420`.

### C. Self-heal

5. PASS. The skip branch reconciles stale filing status and calls
   `session.flush()`:
   `backend/app/services/thirteenf_holdings_ingest.py:402-410`. The flush is
   useful because the skip branch returns without an internal commit, so the
   caller sees the change as pending immediately and can commit at its existing
   barrier. It is harmless in the bulk loop because it updates one already
   loaded filing row and does not run a reparse.

6. PASS. The self-heal only runs after `current_run` has been found with both
   `is_current == True` and `status == "succeeded"`:
   `backend/app/services/thirteenf_holdings_ingest.py:390-395`. A filing with
   no good current run falls through to a real ingest attempt instead.

### D. Tests

7. FAIL/advisory. The four new tests each assert the intended behavior and
   would fail against the pre-fix code in the direct paths:

- success -> `succeeded`:
  `backend/tests/unit/test_13f_parse_run_audit.py:345-357`
- direct failed ingest -> `failed`:
  `backend/tests/unit/test_13f_parse_run_audit.py:360-372`
- skip-path heal:
  `backend/tests/unit/test_13f_parse_run_audit.py:375-399`
- failed reparse stays `succeeded`:
  `backend/tests/unit/test_13f_parse_run_audit.py:402-420`

But the failure test is not sufficient for the product path because it does not
simulate the admin bulk loop's `session.rollback()` after the helper raises.

### E. No regression

8. FAIL due to the failure-path transaction issue above. The new `"succeeded"`
   and skip-heal writes are consistent with existing consumers:
   `thirteenf_readiness.py` counts `parse_status == "succeeded"`,
   `thirteenf_health.py` counts `"failed"` / `"needs_review"`, and
   `thirteenf_filing_detail.py` already uses `"needs_review"` / `"failed"` for
   filing-detail routing. But failed admin ingest still will not reliably
   persist `"failed"`.

## Verification

I did not run Docker tests for this review. The prompt reports:

- `docker compose exec -T api pytest -q` — 913 passed on a fresh DB.

Given the P1 transaction finding, I would not approve this PR until the failed
ingest path is made durable under the actual admin bulk caller and covered by a
test that exercises the caller rollback behavior.
