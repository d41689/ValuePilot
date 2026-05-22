# PR #92 Review — 13F bulk ingest: process the primary document

**Branch:** `claude/13f-bulk-ingest-primary-doc`
**Reviewer:** Claude Code (external re-review)
**Date:** 2026-05-22

---

## Overall verdict: REQUEST CHANGES

The two-pass Phase 2.5, the RESTATEMENT reconciliation helper, and the P3 card
fix are correctly constructed. However, Phase 2.5 pass 2 calls
`apply_amendment_policy` unconditionally for every amendment on every bulk
re-run, and that function resets `is_active_for_manager_period = False` and
`amendment_status` regardless of any previously applied admin decision. A
`NEW_HOLDINGS` amendment that was manually resolved via `resolve_amendment` is
overwritten and its original is potentially re-activated, breaking the
"exactly one correct active filing" contract. This is a blocking data-contract
regression.

---

## Findings

### [BLOCKING] Phase 2.5 bulk re-runs overwrite human-resolved amendment decisions

`apply_amendment_policy` (filing_detail.py:359–367) unconditionally sets:

```python
filing.is_active_for_manager_period = False
filing.amendment_status = "amendments_pending"   # non-RESTATEMENT
# or "pending_parse"                              # RESTATEMENT
```

for any `filing.is_amendment == True` filing, every time it is called.

`resolve_amendment` (thirteenf_admin_dashboard.py:459–474) sets
`amendment_status = "applied"` and `is_active_for_manager_period = True` when
an admin resolves a `NEW_HOLDINGS` amendment via `activate_as_original` or
`apply`. On the next `ingest_holdings` bulk run:

1. Phase 2.5 pass 1 parses the primary doc and re-sets primary-doc fields.
   It succeeds and appends the filing to `metadata_filings`.
2. Phase 2.5 pass 2 calls `apply_amendment_policy(session, filing)` on the
   resolved amendment, which resets it to `is_active_for_manager_period=False`,
   `amendment_status="amendments_pending"`.
3. Phase 5 calls `reconcile_restatement_activation` — a no-op for
   `NEW_HOLDINGS`. Nobody restores the amendment.
4. Phase 4c may re-activate the original (if it's now the sole filing with
   `is_active_for_manager_period=False` and `form_type="13F-HR"`).

Net result: the product sees the old original's (pre-amendment) holdings as
active. The screener and Oracle's Lens revert to stale data after any quarterly
re-run.

The same issue exists for `rejected` / `informational` amendments — pass 2
resets their `amendment_status`, though `is_active_for_manager_period` was
already `False` for those, so the data-contract impact is limited to status
field corruption rather than wrong active-filing selection.

**Required fix:** Guard `apply_amendment_policy` (or the Phase 2.5 pass-2 call
site) to skip filings whose `amendment_status` is already terminal
(`"applied"`, `"rejected"`, `"informational"`). Idempotency requires that a
resolved amendment is not reopened by a bulk re-run.

---

## Prompt checklist

### A. Phase 2.5 — primary-doc metadata

**A1 — Two-pass split: PASS**

Evidence: thirteenf_admin_dashboard.py:3356–3376.

Pass 1 (lines 3358–3373) calls `apply_primary_doc_metadata` per filing inside a
SAVEPOINT, collecting successes in `metadata_filings`. Pass 2 (lines 3374–3375)
calls `apply_amendment_policy` only for those same filings. The split is
necessary: `apply_amendment_policy` queries siblings via
`Filing13F.is_amendment.is_(False)` (filing_detail.py:381), so a not-yet-flagged
sibling would be counted as an original in a single interleaved pass. Pass 2
covers exactly the filings pass 1 succeeded on.

**A2 — SAVEPOINT isolation: PASS (with advisory)**

Evidence: thirteenf_admin_dashboard.py:3362–3373.

Each filing's pass-1 work is wrapped in `with session.begin_nested()`. A bad
primary-doc exception rolls back only that filing's savepoint. `_is_programming_error`
(line 3372) re-raises `ImportError`/`NameError`/`AttributeError` so a real bug
fails the stage loudly. Data failures are appended to `failures` and excluded
from `metadata_filings`.

Advisory: A filing where `raw_primary_doc_id` is non-NULL but the
`RawSourceDocument` row is absent hits `continue` inside the `with` block
(line 3365). The savepoint commits as a no-op and the filing is neither added to
`metadata_filings` nor to `failures`. The silent skip is low-risk given FK
integrity, but worth a `logger.warning`.

**A3 — Ordering vs holdings: PASS**

Evidence: thirteenf_admin_dashboard.py:3376 (`session.commit()`) before
Phase 3 at line 3381. The `is_amendment`/`amendment_type` fields are durable
before any call to `ingest_if_needed` / `_do_ingest_holdings`, so
`reconcile_restatement_activation` at holdings-ingest time sees the correct
flags.

### B. Restatement activation

**B4 — `reconcile_restatement_activation` correctness: PASS**

Evidence: thirteenf_holdings_ingest.py:93–127.

Guards (lines 102–104): returns `False` immediately for non-RESTATEMENT
amendments, `parse_status != "succeeded"`, or `quarter_end_date is None`. The
function demotes other `is_active=True` filings for the same
`(manager_id, quarter_end_date)` (lines 107–117), activates this filing (lines
119–123), and sets `amendment_status = "applied"` (lines 122–123). On a second
call, `changed` stays `False` (amendment already active and applied, no other
active filing exists) and the function returns `False`. Only RESTATEMENT
amendments are touched.

**B5 — Call-site `parse_status` ordering: PASS**

Evidence: thirteenf_holdings_ingest.py:247–253. `filing.parse_status =
"succeeded"` is set at line 247 before `reconcile_restatement_activation` is
called at line 253. The guard at line 104 therefore passes on a first ingest for
a `RESTATEMENT` amendment with a valid `quarter_end_date`.

**B6 — Phase 5 re-run heal: PASS**

Evidence: thirteenf_admin_dashboard.py:3474–3482. Phase 5 iterates every filing
in the quarter and calls the idempotent `reconcile_restatement_activation`. For
an already-ingested RESTATEMENT, `ingest_if_needed` skips re-parse (Phase 3),
so the activation must come from Phase 5 — and it does. A `NEW_HOLDINGS` or
other non-RESTATEMENT amendment returns `False` immediately from
`reconcile_restatement_activation` and is left untouched (`amendments_pending`,
original stays active).

### C. Active-filing data contract

**C7 — FAIL (same as blocking finding above)**

Fresh-ingest path is correct:
- Plain 13F-HR original: `apply_amendment_policy` pass 2 activates the latest
  accepted-at original. Phase 4c is a no-op (already active).
- RESTATEMENT /A: Phase 2.5 sets flags; Phase 3 / `_do_ingest_holdings` calls
  `reconcile_restatement_activation`, which activates the amendment and demotes
  the original. Exactly one active filing.
- NEW_HOLDINGS /A: Phase 2.5 sets `amendments_pending` / inactive. No
  auto-activation. Original stays active. Exactly one active filing.

Re-run path after admin resolution is broken: Phase 2.5 pass 2 calls
`apply_amendment_policy` on a previously-resolved `NEW_HOLDINGS` amendment and
resets it to inactive / `amendments_pending`. The original may be re-activated
by Phase 4c. Phase 5 does not fix this (it is RESTATEMENT-only). The net result
is that the "exactly one correct active filing" guarantee is violated after any
subsequent bulk re-run.

Phase 4c's `WHERE is_active_for_manager_period.is_(False)` guard is not a
protection here — it activates the original after the amendment has been
incorrectly deactivated, compounding the error.

### D. P3 — Amendment Accessions card

**D8 — PASS**

Evidence: thirteenf_admin_dashboard.py:2650–2700.

`needs_parse` (line 2656) captures genuine parse problems only. `recommended_job`
is gated on `needs_parse` (line 2675), not on `status`. The waterfall correctly
puts `amendment_status in ("amendments_pending", "pending_parse")` before the
`is_latest_for_period` branch, so a resolved `is_latest_for_period=True` filing
with those statuses will no longer be mislabelled `"applied"`. For a
NEW_HOLDINGS filing that parsed fine and is merely awaiting a decision,
`recommended_job` is now `None` (correct).

### E. Tests

**E9 — FAIL (missing regression for re-run after admin resolution)**

The four new tests (test_13f_amendment_policy.py:277–409) are well-constructed
and would fail against pre-fix code:

- `test_reconcile_restatement_activation_heals_already_ingested` (lines 277–310):
  `reconcile_restatement_activation` did not exist as a public function pre-fix
  → `ImportError`.
- `test_reconcile_restatement_activation_skips_non_restatement` (lines 313–334):
  same `ImportError`.
- `test_apply_primary_doc_metadata_flags_amendment_from_form_type` (lines 337–361):
  `apply_primary_doc_metadata` was not a public function pre-fix → `ImportError`.
- `test_amendment_payload_status_reflects_amendment_status` (lines 364–409):
  pre-fix `_amendment_payload` computed status from `is_latest_for_period` first,
  so a `is_latest_for_period=True` + `amendment_status="amendments_pending"` filing
  would return `"applied"`, failing the assertion.

The blocking gap — Phase 2.5 overwriting a resolved amendment on re-run — has
no regression test. The test suite would not catch this regression.

---

## Summary

| Item | Verdict |
|---|---|
| A1 — Two-pass split | PASS |
| A2 — SAVEPOINT isolation | PASS (advisory: silent skip for orphan primary-doc) |
| A3 — Phase ordering | PASS |
| B4 — `reconcile_restatement_activation` correctness | PASS |
| B5 — Call-site `parse_status` ordering | PASS |
| B6 — Phase 5 re-run heal | PASS |
| C7 — Active-filing data contract (re-run after admin resolution) | **FAIL — BLOCKING** |
| D8 — Amendment Accessions card | PASS |
| E9 — Tests | FAIL (missing re-run regression) |

**Required before merge:**

1. Guard Phase 2.5 pass 2 (or `apply_amendment_policy` itself) to skip
   filings whose `amendment_status` is already in `{"applied", "rejected",
   "informational"}`. A resolved amendment must survive a bulk re-run
   unchanged.
2. Add a regression test: resolve a NEW_HOLDINGS amendment via
   `activate_as_original`, run Phase 2.5 + Phase 5 logic again, assert the
   amendment stays `is_active_for_manager_period=True` / `amendment_status=
   "applied"` and the original stays inactive.
