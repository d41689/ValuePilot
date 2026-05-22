# Review prompt — bulk ingest processes the primary document

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with `docs/tasks/2026-05-22_13f-bulk-ingest-primary-doc.md`
and the diff on branch.

---

## Reviewer brief

You are reviewing **PR #92**, branch `claude/13f-bulk-ingest-primary-doc`. The
standard quarterly pipeline (`fetch_quarter_index → ingest_holdings`) parsed
only the holdings infotable and never the filing's *primary document*, so
`is_amendment` / `amendment_type` / `report_type` / `coverage_*` were unset for
every bulk-ingested filing. The PR adds primary-doc processing to the bulk
pipeline and fixes amendment activation. The fix and the diagnosis are
agent-authored — scrutinise accordingly.

**This change moves `is_active_for_manager_period`** — the data contract the
screener and Oracle's Lens read — so weight your review on correctness of the
active-filing selection. No schema change / no migration.

### What changed

- `thirteenf_filing_detail.py` — `apply_primary_doc_metadata` extracted
  (primary-doc fields only; `is_amendment` is also true for a `/A` form type);
  `_apply_amendment_policy` renamed to public `apply_amendment_policy`.
  `ingest_accession_filing_detail` calls metadata, then the policy.
- Bulk `ingest_holdings` (`_execute_ingest_job`) — **Phase 2.5** (after routing,
  before holdings): pass 1 parses every filing's primary doc and applies the
  metadata fields; pass 2 runs `apply_amendment_policy` for every filing.
  **Phase 5** (after holdings/healing): `reconcile_restatement_activation` per
  filing.
- `thirteenf_holdings_ingest.py` — `reconcile_restatement_activation` extracted
  (idempotent), replacing the inline RESTATEMENT branch in `_do_ingest_holdings`.
- `_amendment_payload.status` reflects `amendment_status` (P3); `recommended_job`
  gated on a genuine parse problem.

### Files in scope

- `backend/app/services/thirteenf_filing_detail.py`
- `backend/app/services/thirteenf_holdings_ingest.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_amendment_policy.py`
- `docs/tasks/2026-05-22_13f-bulk-ingest-primary-doc.md`

### Baseline

`git diff main...HEAD`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + evidence

### A. Phase 2.5 — primary-doc metadata — MANDATORY

1. **Two passes.** Pass 1 sets fields (incl. `is_amendment`) for all filings;
   pass 2 runs `apply_amendment_policy`. Confirm the split is necessary —
   `apply_amendment_policy`'s original-activation branch queries sibling rows by
   `is_amendment.is_(False)`, so a single interleaved pass would miscount a
   not-yet-flagged sibling amendment as an original. Confirm pass 2 covers every
   filing pass 1 succeeded on.
2. **Isolation.** Pass 1 wraps each filing in a SAVEPOINT; a bad primary doc is
   recorded in `failures` and does not fail the stage. Confirm a programming
   error still re-raises (`_is_programming_error`).
3. **Ordering vs holdings.** Phase 2.5 runs before Phase 3 so `_do_ingest_holdings`
   sees `is_amendment`/`amendment_type`. Confirm the commit barrier between them.

### B. Restatement activation — MANDATORY

4. **`reconcile_restatement_activation` correctness.** It activates a parsed
   RESTATEMENT amendment, demotes every *other* active filing for the same
   `(manager_id, quarter_end_date)`, sets `amendment_status="applied"`. Confirm:
   the `parse_status == "succeeded"` + `quarter_end_date is not None` guards;
   that it is idempotent (a second call returns False, changes nothing); and
   that it only ever touches RESTATEMENT amendments.
5. **`_do_ingest_holdings`.** The inline RESTATEMENT branch is replaced by a
   call to `reconcile_restatement_activation`. Confirm `filing.parse_status` is
   already `"succeeded"` at that call site (set a few lines above) so the guard
   passes on a first ingest.
6. **Phase 5 — re-run heal.** For an already-ingested restatement, Phase 3
   skips re-parse (`ingest_if_needed`), so the activation must come from Phase 5.
   Confirm Phase 5 runs every time and is idempotent, and that a NEW_HOLDINGS /
   non-RESTATEMENT amendment is left `amendments_pending` (not auto-activated).

### C. Active-filing data contract — MANDATORY

7. Trace the net effect on `is_active_for_manager_period`: a plain 13F-HR
   original is activated by `apply_amendment_policy`; a RESTATEMENT /A supersedes
   it; a NEW_HOLDINGS /A leaves the original active. Confirm there is exactly one
   active filing per `(manager, period)` in the normal case, and that the
   pre-existing Phase 4c "solo 13F-HR" heuristic is now a harmless guarded
   fallback (its `WHERE is_active=False` makes it a no-op once Phase 2.5 ran).

### D. P3 — Amendment Accessions card

8. `_amendment_payload.status` returns `pending` when `amendment_status` is
   `amendments_pending` / `pending_parse`, so the list agrees with the
   `build_pending_amendments_read_model` warning. Confirm `recommended_job` no
   longer recommends `reprocess_amendment` for an amendment that parsed fine and
   is merely awaiting an apply/reject decision.

### E. Tests

9. Review the 4 tests in `test_13f_amendment_policy.py` — restatement
   reconciliation (heal + idempotent), non-restatement skip,
   `apply_primary_doc_metadata` flagging `is_amendment` from a `/A` form type,
   and `_amendment_payload` status reflecting `amendment_status`. Confirm each
   would fail against pre-fix code.

## Verification

```
docker compose exec -T api pytest -q          # 917 passed on a FRESH DB
```

The author re-ran "Ingest holdings" for 2025-Q1…Q4 on the dev stack:
Himalaya's RESTATEMENT became applied/active, the three Cantillon `/A` were
detected as RESTATEMENT amendments and activated, Vulcan's NEW_HOLDINGS stayed
`amendments_pending`, `report_type` populated for all 64 filings.

## Pass bar

Approve only if **A–C** confirm the bulk pipeline now reliably sets the
amendment flags and selects exactly one correct active filing per period
(including the restatement-supersedes-original and lone-NEW_HOLDINGS cases),
with the reconciliation idempotent across re-runs, and **D/E** are satisfied.
The bar is: "a bulk-ingested 13F-HR/A is a recognised amendment, a parsed
RESTATEMENT is the active filing, and the Amendment Accessions card is
self-consistent."
