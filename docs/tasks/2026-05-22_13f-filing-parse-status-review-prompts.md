# Review prompt — Filing13F.parse_status advance-on-ingest fix

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the diff on branch.

---

## Reviewer brief

You are reviewing **PR #91**, branch `claude/13f-filing-parse-status`. It is a
small, contained bug fix: the `/admin/13f/filings` STATUS column showed every
filing as `pending` even after its holdings parsed cleanly. The fix and the
diagnosis are agent-authored — scrutinise accordingly.

No production write, no schema change, no migration.

### What changed and why

`Filing13F.parse_status` defaults to `"pending"` on insert and **no code path
ever advanced it** — the holdings-ingest service set the `ParseRun13F`'s status
to `"succeeded"` but never mirrored it onto the filing. So every
successfully-parsed filing stayed `pending` forever.

`backend/app/services/thirteenf_holdings_ingest.py` now mirrors the parse-run
outcome onto the filing:

- `_do_ingest_holdings` success block → `filing.parse_status = "succeeded"`.
- `_do_ingest_holdings` failure block → `filing.parse_status = "failed"`
  (written inside the failed-run SAVEPOINT).
- `ingest_if_needed` skip branch → if a current succeeded `ParseRun13F` exists
  but the filing is not `"succeeded"`, reconcile it (+ `session.flush()`). This
  self-heals filings ingested before the fix on a plain re-run.
- `reparse_accession` except handler → when a failed reparse restores the prior
  good run, flip `parse_status` back to `"succeeded"`.

### Files in scope

- `backend/app/services/thirteenf_holdings_ingest.py` — the four edits above.
- `backend/tests/unit/test_13f_parse_run_audit.py` — 4 regression tests.

### Baseline

`git diff main...HEAD`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + evidence

### A. Success path — MANDATORY

1. Confirm `_do_ingest_holdings` sets `filing.parse_status = "succeeded"` in the
   Phase-2 success block and `session.add(filing)`s it, and that `"succeeded"`
   is a member of `FILING_PARSE_STATUSES` (the `@validates` whitelist).
2. Confirm the diagnosis: grep the backend — nothing else writes
   `Filing13F.parse_status` to `"succeeded"`/`"partial_success"`, so there is
   no competing writer and no double-write.

### B. Failure path — MANDATORY

3. The failure block writes `filing.parse_status = "failed"` inside
   `with session.begin_nested()` alongside the failed `ParseRun13F`. Confirm:
   (a) the `filing` object is still usable after the earlier `sp.rollback()`;
   (b) the nested savepoint commits the `"failed"` status so it survives the
   subsequent `raise`; (c) `ingest_holdings_for_filing` does not roll it back.
4. Reparse edge: a failed reparse calls `_do_ingest_holdings` (→ status
   `"failed"`), then `reparse_accession`'s except restores the old current run.
   Confirm the except handler also flips `parse_status` back to `"succeeded"`
   (guarded by `restored.status == "succeeded"`), so a failed reparse leaves
   the filing `succeeded` — it still holds the prior good holdings. Covered by
   `test_failed_reparse_keeps_filing_parse_status_succeeded`.

### C. Self-heal — MANDATORY

5. `ingest_if_needed`'s skip branch reconciles a stale `parse_status` and calls
   `session.flush()`. Confirm the flush is needed (so a re-run persists the
   heal even before the caller's commit barrier) and harmless inside the bulk
   ingest loop.
6. Confirm the self-heal can only mark a filing `"succeeded"` when a current
   `ParseRun13F` with `status == "succeeded"` exists — `ingest_if_needed`'s
   `current_run` query filters on exactly that, so it cannot wrongly promote a
   filing with no good run.

### D. Tests

7. Review the 4 new tests in `test_13f_parse_run_audit.py`. Confirm each would
   **fail against the pre-fix code**: success → `succeeded`, failed ingest →
   `failed`, skip-path heal of a stale `pending`, failed reparse staying
   `succeeded`.

### E. No regression

8. `pytest -q` — 913 passed on a fresh DB (was 909; +4 new tests). Confirm the
   new `"succeeded"` / `"failed"` writes are consistent with the existing
   consumers of `Filing13F.parse_status` — `thirteenf_health.py` (counts
   `parse_status == "failed"` / `"needs_review"`) and `thirteenf_filing_detail.py`
   (sets `"needs_review"` / `"failed"`).

## Verification

```
docker compose exec -T api pytest -q          # 913 passed on a FRESH DB
```

Existing data: no migration/backfill script — the `ingest_if_needed` self-heal
means re-running "Ingest holdings" reconciles pre-fix rows. Verified on the dev
stack: re-ingesting healed all 64 existing filings from `pending` to
`succeeded`.

## Pass bar

Approve only if **A–C** confirm the parse-run outcome is mirrored onto the
filing on success, failure, skip-heal, and the failed-reparse edge, with no
competing writer and no way to mark a filing `succeeded` without a good run,
and **D/E** are satisfied. The bar is: "a parsed filing reports `succeeded`, a
failed ingest reports `failed`, and a plain re-run heals everything ingested
before the fix."
