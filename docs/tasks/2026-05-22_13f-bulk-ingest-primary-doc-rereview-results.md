# Re-review results — bulk ingest primary-doc amendment policy

Reviewed branch: `claude/13f-bulk-ingest-primary-doc`

Baseline: `git diff main...HEAD`

Prior review: `docs/tasks/2026-05-22_13f-bulk-ingest-primary-doc-review-results.md`

## Overall Verdict

APPROVE. The prior blocker is fixed. `apply_amendment_policy()` now preserves
terminal amendment resolutions (`applied`, `rejected`, `informational`) and the
original-filing branch keeps originals inactive when an applied amendment owns
the period. A bulk re-run no longer reverts an admin-resolved amendment or
resurrects the superseded original.

I found no remaining blocking issue in the reviewed scope. I did not rerun the
Docker test suite during this re-review.

## Prior Blocker

### Bulk re-run overwrote resolved amendments — PASS

Evidence:

- Terminal amendment statuses are defined as `applied`, `rejected`, and
  `informational`:
  `backend/app/services/thirteenf_filing_detail.py:359`.
- For amendments, `apply_amendment_policy()` normalizes `amendment_type`, then
  returns early when the existing status is terminal, leaving
  `is_active_for_manager_period` and `amendment_status` untouched:
  `backend/app/services/thirteenf_filing_detail.py:362-370`.
- For original filings, the policy now checks whether an applied amendment
  exists for the same `(manager_id, quarter_end_date)` and leaves the original
  inactive if so:
  `backend/app/services/thirteenf_filing_detail.py:386-399`.
- The regression test simulates the bulk Phase 2.5 policy pass across both the
  demoted original and an applied NEW_HOLDINGS amendment, and asserts the
  amendment remains active/applied while the original remains inactive:
  `backend/tests/unit/test_13f_amendment_policy.py:411-448`.

This directly addresses the active-filing data-contract failure from the prior
review.

## Prompt Checklist

### A. Phase 2.5 — primary-doc metadata

1. PASS. The two-pass design remains intact: pass 1 applies primary-doc fields
   for successfully parsed filings, pass 2 runs the policy after sibling
   `is_amendment` flags have been populated.

2. PASS. Pass 1 still isolates per-filing primary-doc parse failures with a
   SAVEPOINT and re-raises programming errors.

3. PASS. Phase 2.5 still commits before holdings Phase 3, so holdings ingest
   sees amendment metadata.

### B. Restatement activation

4. PASS. `reconcile_restatement_activation()` still acts only on parsed
   RESTATEMENT amendments with `parse_status == "succeeded"` and non-null
   `quarter_end_date`, demotes sibling active filings, marks the restatement
   active/applied, and is idempotent.

5. PASS. `_do_ingest_holdings()` still sets `parse_status = "succeeded"` before
   calling the restatement reconciliation helper.

6. PASS. Phase 5 still runs on every bulk ingest and idempotently heals
   already-ingested RESTATEMENT amendments; non-RESTATEMENT amendments are not
   auto-activated.

### C. Active-filing data contract

7. PASS. Fresh ingest and re-run paths now preserve the intended contract:
   originals are active when no applied amendment owns the period; parsed
   RESTATEMENT amendments supersede originals; pending NEW_HOLDINGS amendments
   leave the original active; already-applied NEW_HOLDINGS amendments remain
   active across bulk re-runs.

### D. P3 — Amendment Accessions card

8. PASS. The card status and `recommended_job` behavior remain consistent with
   the prior review: pending review is not treated as a parse problem.

### E. Tests

9. PASS. The original four tests still cover the new helper/card behavior, and
   the added regression test covers the prior blocker: preserving an
   admin-resolved amendment across a policy re-run.

## Verification

Not run in this re-review. The commit message/task log report:

- `pytest -q` — 918 passed on a fresh DB.
- Live check: a 2025-Q4 re-ingest kept Himalaya's applied RESTATEMENT active.
