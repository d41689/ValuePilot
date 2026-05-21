# Review prompt — CUSIP enrichment status-filter fix + run-to-completion (PR #84)

Paste this into a fresh reviewer session (human or agent). It is self-contained.
Pair it with `docs/tasks/2026-05-21_cusip-link-rate-diagnosis.md` (diagnosis +
implementation notes).

## Reviewer brief

You are reviewing **PR #84**, branch `claude/cusip-link-rate-enrichment-fix`.
It fixes the bug behind the 13F CUSIP link rate being stuck at ~12%:
`enrich_unmapped_holdings` queried `cusip_mapping_status == "pending_mapping"`
only, but every unresolved prod holding (~13,981) is in status `unresolved`, so
the OpenFIGI enrichment was a permanent no-op. The PR broadens the filter and
adds a run-to-completion batch loop.

This is **prod-auto-deploying backend code** that changes a **data-pipeline**
query and adds a **loop over an external (OpenFIGI-via-Rate-Guard) call**.
Review it with particular attention to (1) the status-filter correctness and
(2) the loop's termination guarantee.

One review lens — backend / Python (data-pipeline correctness + tests).

### Files in scope
- `backend/app/services/cusip_enrichment.py` — the filter fix,
  `_count_enrichable_holdings`, `enrich_all_unmapped_holdings`
- `backend/app/services/thirteenf_admin_dashboard.py` — the `enrich_cusip` job
- `backend/tests/unit/test_13f_cusip_enrichment.py` — new + rewritten tests
- `docs/tasks/2026-05-21_cusip-link-rate-diagnosis.md`, `docs/BACKLOG.md`

### Baseline
`git diff main...HEAD`.

## Answer each question with a verdict (PASS / FAIL / advisory) + file:line evidence

### A. Status-filter correctness — MANDATORY
1. `enrich_unmapped_holdings` now selects `cusip_mapping_status IN
   ('pending_mapping', 'unresolved')`. Confirm `unresolved` genuinely means
   "needs a mapping, OpenFIGI never consulted" — `_apply_mappings_to_holdings`
   sets `unresolved` purely from a *missing `cusip_ticker_map` row*, never from
   an OpenFIGI call — so re-querying it is correct, not a re-try of a known
   failure. Confirm excluding `needs_review` (the ambiguous-result human queue)
   is right.
2. The query also requires `cusip IS NOT NULL` and `cusip NOT IN (SELECT cusip
   FROM cusip_ticker_map WHERE cusip IS NOT NULL)`. Confirm the `NOT IN`
   subquery is safe (the NULL-in-`NOT IN` pitfall is handled by the
   `IS NOT NULL` on the subquery), and that `_count_enrichable_holdings` uses
   the **identical** predicate as the batch query (a mismatch would desync the
   loop).

### B. Loop termination — MANDATORY (the crux)
3. `enrich_all_unmapped_holdings` loops `enrich_unmapped_holdings`. Prove it
   terminates: each batch sends every batch CUSIP to `upsert_cusip_mapping`,
   which **always** creates a `cusip_ticker_map` row (confirm — even for a
   no-match / `low` result), so those CUSIPs leave the `~cusip.in_` pool and the
   next batch cannot re-pick them. The unmapped-CUSIP pool strictly shrinks →
   the `before == 0` check ends the loop.
4. The backstops: `max_batches` hard cap, and the no-progress guard
   (`_count_enrichable_holdings(db) >= before → break`). Confirm a genuinely
   unresolvable CUSIP (OpenFIGI returns nothing → `low`, `ticker=None`) does
   **not** spin the loop — it gets a map row once, then is excluded — and that
   an all-invalid-CUSIP batch (holdings → `invalid_cusip`, leaving the
   `[pending,unresolved]` set) still counts as progress, not a false stall.

### C. No regression for the other callers
5. The `~cusip.in_(cusip_ticker_map)` exclusion was added to
   `enrich_unmapped_holdings`, which is also reached by
   `enrich_cusips_from_openfigi` (the `enrich_metadata` job, the CLI). Confirm
   those single-batch callers still behave correctly — they now skip
   already-mapped CUSIPs (an improvement), and `_apply_mappings_to_holdings`
   still links holdings against existing mappings.
6. The `enrich_cusip` job result dict changed shape (now `mappings_created`,
   `batches_run`, `new_stocks`, `holdings_linked`, `holdings_still_unmapped`,
   `status`). Confirm nothing consumes the old `{mappings_created, status}`
   shape rigidly.

### D. Transactions & client lifecycle
7. `enrich_all_unmapped_holdings` runs a long loop; each `enrich_unmapped_holdings`
   batch commits (via `_apply_mappings_to_holdings`). Confirm partial progress
   is durable and the loop's count probes see committed state.
8. `enrich_all_unmapped_holdings` is `owns_client`-aware and closes a
   self-constructed `OpenFigiClient` in a `finally` (the PR-3 C6 lesson) — the
   same client instance is reused across all batches. Confirm.

### E. Tests
9. `test_enrich_picks_up_unresolved_holdings` — confirm it is a genuine
   regression test: it would **fail** against the old `== "pending_mapping"`
   filter (a holding seeded in `unresolved`).
10. `test_enrich_skips_cusips_already_mapped` and
    `test_enrich_all_runs_to_completion` — assess coverage; note gaps. Confirm
    the two rewritten PR-#81 client-lifecycle tests now run against the real
    `db_session` (their old MagicMock-db helper hard-coded the query shape).

### F. Scope
11. Confirm the PR does **not** claim to raise the link rate — it unblocks the
    enrichment; the operational `enrich_cusip` run against prod is a separate,
    explicitly-authorised step, and `docs/BACKLOG.md` reflects that (the entry
    stays open until that run is done).

## Verification
- `docker compose run --rm --no-deps api pytest -q` — backend green (~895).
- `git diff main...HEAD` — scope; no DB migration (`cusip_mapping_status` is an
  existing column; only query filters changed); frontend untouched.

## Pass bar
Approve only if: A (the broadened filter is correct and `unresolved` is the
right set to re-enrich); B (the loop provably terminates — the unmapped-CUSIP
pool strictly shrinks, backed by the cap + no-progress guard). C / D / E / F
findings are recorded. The bar is "the OpenFIGI enrichment now actually sees the
unresolved backlog and a single `enrich_cusip` job drains it to completion —
safe to auto-deploy to prod."
