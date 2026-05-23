# PR #92 Review — 13F bulk ingest: process the primary document

**Branch:** `claude/13f-bulk-ingest-primary-doc`
**Reviewer:** Claude Code (external re-review, then human re-review)
**Date:** 2026-05-22

---

## Overall verdict: APPROVE

All mandatory checks (A–C) pass. The first-pass review raised a blocking concern
about Phase 2.5 overwriting admin-resolved amendments on re-run, but direct
inspection of the diff shows that concern was a **false positive** — the PR
already contains the guard and the regression test. Details below.

---

## Correction of first-pass review

The first review (verdict: REQUEST CHANGES) claimed:

> `apply_amendment_policy` unconditionally resets `is_active_for_manager_period`
> and `amendment_status` for every amendment, overwriting admin-resolved
> decisions on bulk re-run.

This is incorrect. The PR already addresses both sides of the re-run scenario:

1. **Amendment filing path** — `_TERMINAL_AMENDMENT_STATUSES = frozenset({"applied", "rejected", "informational"})` is defined, and `apply_amendment_policy` returns early (`if filing.amendment_status in _TERMINAL_AMENDMENT_STATUSES: return`) before touching any flag. A resolved amendment survives any re-run.

2. **Original filing path** — The original-filing branch now queries for an existing `applied` amendment on the same `(manager_id, quarter_end_date)` before activating the original. If one exists, the original is left inactive; a superseded original cannot be resurrected.

3. **Regression test** — The diff adds a fifth test, `test_apply_amendment_policy_preserves_admin_resolved_amendment`, which directly covers the scenario the first review said was untested: resolve a NEW_HOLDINGS amendment, call `apply_amendment_policy` on both filings again, assert the amendment stays `applied` / active and the original stays inactive.

The first review appeared to analyse the pre-fix version of `apply_amendment_policy` rather than the new code, missing `_TERMINAL_AMENDMENT_STATUSES`, the `applied_amendment` guard, and the fifth test.

---

## Prompt checklist

### A. Phase 2.5 — primary-doc metadata

**A1 — Two-pass split: PASS**

Evidence: `thirteenf_admin_dashboard.py` Phase 2.5 block.

Pass 1 calls `apply_primary_doc_metadata` per filing inside a SAVEPOINT,
collecting successes in `metadata_filings`. Pass 2 calls `apply_amendment_policy`
only for those same filings — after all `is_amendment` flags are committed. The
split is necessary: `apply_amendment_policy`'s original-selection branch queries
`Filing13F.is_amendment.is_(False)`; a single interleaved pass would miscount a
not-yet-flagged sibling as an original and could activate the wrong filing.
Pass 2 covers exactly the filings pass 1 succeeded on (`metadata_filings`).

**A2 — SAVEPOINT isolation: PASS (advisory)**

Evidence: `with session.begin_nested()` wrapping each filing in pass 1;
`_is_programming_error` re-raise guard inside the except block.

A bad primary-doc parse (bad XML, network artifact) rolls back only that
filing's savepoint; the filing is appended to `failures` and excluded from
`metadata_filings`. A `NameError` / `AttributeError` / `ImportError` — a
programming bug — re-raises and fails the stage loudly.

Advisory: A filing where `raw_primary_doc_id` is non-NULL but the
`RawSourceDocument` row is absent hits `continue` inside the `with` block. The
savepoint commits as a no-op and the filing is neither in `metadata_filings` nor
`failures`. Low-risk given FK integrity, but worth a `logger.warning`.

**A3 — Ordering vs holdings: PASS**

Evidence: `session.commit()` barrier after Phase 2.5 pass 2, before Phase 3.

`is_amendment` / `amendment_type` are durable on disk before any
`ingest_if_needed` / `_do_ingest_holdings` call, so both the holdings path and
`reconcile_restatement_activation` see the correct flags on first ingest.

### B. Restatement activation

**B4 — `reconcile_restatement_activation` correctness: PASS**

Evidence: `thirteenf_holdings_ingest.py`, `reconcile_restatement_activation`.

Guards: returns `False` immediately unless `is_amendment=True`,
`amendment_type="RESTATEMENT"`, `parse_status="succeeded"`, and
`quarter_end_date is not None`. Demotes every other `is_active=True` sibling for
the same `(manager_id, quarter_end_date)`. Sets `is_active_for_manager_period=True`
and `amendment_status="applied"` on this filing. On a second call, `changed`
remains `False` (already active/applied, no other active sibling) and returns
`False`. Only RESTATEMENT amendments are touched — `NEW_HOLDINGS` returns `False`
at the first guard.

**B5 — Call-site `parse_status` ordering: PASS**

Evidence: `thirteenf_holdings_ingest.py`, `_do_ingest_holdings`.

`filing.parse_status = "succeeded"` is set before `reconcile_restatement_activation`
is called. The `parse_status == "succeeded"` guard therefore passes on a first
ingest of a RESTATEMENT amendment that has a valid `quarter_end_date`.

**B6 — Phase 5 re-run heal: PASS**

Evidence: Phase 5 loop in `_execute_ingest_job`.

Phase 5 iterates every filing in the quarter and calls the idempotent
`reconcile_restatement_activation`. For an already-ingested RESTATEMENT, Phase 3
skips re-parse (`ingest_if_needed`), so activation comes from Phase 5 — and it
does. A `NEW_HOLDINGS` or other non-RESTATEMENT amendment returns `False`
immediately and is left `amendments_pending` / inactive, with the original
staying active. Phase 5 is unconditional and idempotent, so re-runs are safe.

### C. Active-filing data contract

**C7 — PASS**

Fresh-ingest path:
- **Plain 13F-HR original:** `apply_amendment_policy` (pass 2) activates the
  latest original; no applied amendment exists, so the `applied_amendment` guard
  does not fire. Phase 4c is a no-op (already active). One active filing.
- **RESTATEMENT /A:** Phase 2.5 sets `is_amendment=True` / `amendment_type=RESTATEMENT`.
  Phase 3 / `_do_ingest_holdings` calls `reconcile_restatement_activation`, which
  activates the amendment and demotes the original. Phase 5 is idempotent. One
  active filing.
- **NEW_HOLDINGS /A:** Phase 2.5 sets `is_amendment=True`; `apply_amendment_policy`
  sets `amendments_pending` / inactive. No auto-activation. Original stays active
  via the original-filing branch. One active filing.

Re-run path after admin resolution of a NEW_HOLDINGS amendment:
- `apply_amendment_policy` checks `amendment_status in _TERMINAL_AMENDMENT_STATUSES`
  first; `"applied"` is terminal, so it returns early — the amendment stays
  `is_active=True` / `amendment_status="applied"`.
- The original-filing branch finds the `applied` amendment via the
  `applied_amendment` query and returns early — the original stays `is_active=False`.
- Phase 4c's `WHERE is_active_for_manager_period.is_(False)` guard makes it a
  no-op since the amendment is already active.

The "exactly one correct active filing" guarantee holds across re-runs for all
three cases.

### D. P3 — Amendment Accessions card

**D8 — PASS**

Evidence: `_amendment_payload` in `thirteenf_admin_dashboard.py`.

`needs_parse = has_failed_raw or raw_infotable_doc_id is None or holdings_count == 0`
captures genuine parse problems. `recommended_job` is gated on `needs_parse`,
not on `status`. The status waterfall checks `amendment_status in ("amendments_pending",
"pending_parse")` before `is_latest_for_period`, so a filing that parsed fine
but awaits admin resolution correctly shows `"pending"` (not the pre-fix
`"applied"`). `recommended_job` is `None` for such a filing — correct; the
operator must decide, not the system.

### E. Tests

**E9 — PASS**

The PR adds **five** tests (the review prompt anticipated four; the fifth is the
key regression):

1. `test_reconcile_restatement_activation_heals_already_ingested` — activates a
   RESTATEMENT stuck at `pending_parse` and confirms idempotency. Fails
   pre-fix (function did not exist as a public export).
2. `test_reconcile_restatement_activation_skips_non_restatement` — confirms a
   `NEW_HOLDINGS` amendment is untouched. Same `ImportError` pre-fix.
3. `test_apply_primary_doc_metadata_flags_amendment_from_form_type` — a `/A`
   form type forces `is_amendment=True` even when the parser returns
   `is_amendment=False`. Fails pre-fix (`apply_primary_doc_metadata` was not
   public).
4. `test_amendment_payload_status_reflects_amendment_status` — a
   `is_latest_for_period=True` + `amendment_status="amendments_pending"` filing
   must return `status="pending"`. Pre-fix: `is_latest_for_period` branch fired
   first, returning `"applied"`.
5. `test_apply_amendment_policy_preserves_admin_resolved_amendment` — simulates
   Phase 2.5 pass 2 calling `apply_amendment_policy` on a previously-resolved
   `NEW_HOLDINGS` amendment; asserts the amendment stays `applied` / active and
   the original stays inactive. Fails pre-fix (no terminal guard).

All five would fail against pre-fix code. The test suite directly covers the
re-run idempotency scenario that was the first review's stated concern.

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
| C7 — Active-filing data contract (all cases incl. re-run after admin resolve) | PASS |
| D8 — Amendment Accessions card | PASS |
| E9 — Tests (5 tests, all would fail pre-fix) | PASS |

**Advisory (non-blocking):** When `raw_primary_doc_id` is set but the
`RawSourceDocument` row is missing, Phase 2.5 pass 1 silently skips the filing
without a log entry or `failures` entry. Add a `logger.warning` to aid
diagnosis.

**Approved.** The bulk pipeline now reliably sets amendment flags, selects
exactly one correct active filing per period across all amendment cases, and
re-runs are idempotent even after admin resolution of NEW_HOLDINGS amendments.
