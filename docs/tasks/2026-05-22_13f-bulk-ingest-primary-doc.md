# 13F bulk ingest — process the primary document

## Goal

The standard quarterly pipeline (`fetch_quarter_index → ingest_holdings`) parses
only the holdings *infotable*; it never parses the filing's *primary document*.
So every bulk-ingested filing is missing `is_amendment`, `amendment_type`,
`report_type`, `coverage_completeness`, `coverage_type`,
`has_confidential_treatment`. Only the single-filing `ingest_accession` path
runs `ingest_accession_filing_detail`, which reads the primary doc.

## Problems (found on /admin/13f/filings)

- **P1** — a parsed RESTATEMENT 13F-HR/A stays `amendment_status=pending_parse`
  and `is_active_for_manager_period=false`; the superseded original stays
  active. The screener / Oracle's Lens read the pre-restatement holdings.
  RESTATEMENT activation lives inside `_do_ingest_holdings`, which a re-run
  skips, and depends on `is_amendment`/`amendment_type` being set first.
- **P2** — 13F-HR/A filings bulk-ingested have `is_amendment=false`; they are
  never recognised as amendments and end up with no active filing for their
  period (Cantillon Q1–Q3 2025 — holdings invisible to the product).
- **P3** — the Amendment Accessions card contradicts itself: the "X pending"
  warning reads `amendment_status`; the list's STATUS is computed from
  `is_latest_for_period` and ignores `amendment_status`.

## Fix

1. Extract `apply_primary_doc_metadata(session, filing, summary)` in
   `thirteenf_filing_detail.py` — sets the primary-doc-derived fields and runs
   `_apply_amendment_policy`. `is_amendment` is also true when `form_type`
   ends in `/A` (authoritative). `ingest_accession_filing_detail` reuses it.
2. New phase in the bulk `ingest_holdings` job: parse each filing's primary doc
   (already on disk after Phase 1) and call `apply_primary_doc_metadata` —
   **before** the holdings phase, so `_do_ingest_holdings` sees the amendment
   flags.
3. Extract `reconcile_restatement_activation(session, filing)` —
   idempotent: a parsed RESTATEMENT amendment becomes the active filing and the
   superseded original is demoted. Called from `_do_ingest_holdings` (replacing
   the inline branch) and from a reconciliation phase in the bulk job (so a
   re-run heals already-ingested restatements).
4. `_amendment_payload.status` reflects `amendment_status` (P3).

## Acceptance criteria

- Bulk-ingested 13F-HR/A filings get `is_amendment=true` + `amendment_type`.
- A parsed RESTATEMENT amendment is `is_active_for_manager_period=true`,
  `amendment_status=applied`; the original is demoted.
- `report_type` / `coverage_*` populated for bulk-ingested filings.
- The Amendment Accessions card warning and list agree.
- Canonical CI green; verified on the dev stack via the web UI.

## Test plan

- `pytest -q` on a fresh DB (in-container).
- Unit: `reconcile_restatement_activation` (activate + demote + idempotent);
  `apply_primary_doc_metadata` sets `is_amendment` from a `/A` form type.
- Live: re-run "Ingest holdings" for the affected quarters on the dev stack;
  confirm Himalaya's RESTATEMENT is active and the Cantillon /A are detected.

## Log

- 2026-05-22: branch created; root cause confirmed (bulk pipeline never parses
  the primary doc; Phase 4c's comment already documents the gap).
- 2026-05-22: implemented. `apply_primary_doc_metadata` + public
  `apply_amendment_policy` extracted; bulk `ingest_holdings` Phase 2.5
  (primary-doc metadata, two passes) + Phase 5 (restatement reconciliation)
  added; `reconcile_restatement_activation` extracted and idempotent;
  `_amendment_payload.status` keyed off `amendment_status` (P3). 4 unit tests
  added. `pytest -q` — 917 passed on a fresh DB.

## Verification (dev stack, web UI)

Re-ran "Ingest holdings" for 2025-Q1…Q4 through `/admin/13f`:

- Himalaya 2025-Q4 RESTATEMENT 13F-HR/A → `amendment_status=applied`,
  `is_active_for_manager_period=true`; the original demoted (P1).
- Cantillon 2025-Q1/Q2/Q3 13F-HR/A → detected as amendments
  (`is_amendment=true`, `amendment_type=RESTATEMENT`), `applied` + active —
  their 74/75/76 holdings are now visible to the screener (P2).
- Vulcan 2025-Q4 NEW_HOLDINGS 13F-HR/A → correctly stays `amendments_pending`
  (not auto-mergeable — genuine admin-review item); the original stays active.
- `report_type` populated for all 64 filings (was 4) — the "unknown" labels
  are gone.
- Amendment Accessions card: the "NEW_HOLDINGS: 1 pending" warning now agrees
  with the list (Vulcan's row reads `pending`, not `applied`) (P3).

## Review round 1 — addressed

Both PR #92 reviews (FAIL / REQUEST CHANGES) flagged one blocker: Phase 2.5's
pass 2 called `apply_amendment_policy` unconditionally, which reset
`is_active_for_manager_period=False` and `amendment_status` for *every*
amendment on *every* re-run — reverting an admin-resolved amendment (e.g. a
NEW_HOLDINGS `activate_as_original`) and flipping the active filing back to the
superseded original.

Fixed in `apply_amendment_policy`: a resolved amendment (`amendment_status` in
`applied` / `rejected` / `informational`) is terminal — the policy returns
without touching it; and the original-filing branch leaves every original
inactive when an `applied` amendment exists for the period, so a re-run cannot
resurrect a superseded original. Regression test added
(`test_apply_amendment_policy_preserves_admin_resolved_amendment`). `pytest -q`
918 passed; verified live — a 2025-Q4 re-ingest left Himalaya's applied
RESTATEMENT active.
