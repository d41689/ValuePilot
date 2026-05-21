# 2026-05-21 — Diagnosis: 13F CUSIP link rate stuck at ~12%

Backlog item: `docs/BACKLOG.md` → "13F holdings CUSIP link rate stuck at ~12%".
Requested approach: diagnose on dev first, then recommend.

## TL;DR

The ~12% link rate is **a bug, not (only) a data-completeness gap.**
`enrich_unmapped_holdings` — the OpenFIGI enrichment that creates
`cusip_ticker_map` rows — queries holdings in status `pending_mapping` **only**.
Prod has **0** holdings in `pending_mapping`; the 13,981 unresolved holdings are
all in status `unresolved`. So the OpenFIGI enrichment finds nothing and is a
**permanent no-op** — `cusip_ticker_map` can never grow, and the link rate is
frozen. Running enrichment "at scale" (as the backlog item assumed) would do
nothing until this filter is fixed.

## Method

- **dev DB** (`valuepilot-dev-db-1`) — found **empty** of 13F data (0 holdings,
  0 `cusip_ticker_map`, 0 stocks). A dev before/after run is impossible; the
  rate is a prod-only condition. Diagnosis continued via a live OpenFIGI test
  (environment-independent) + **read-only** SELECTs against prod.
- **prod** — read-only queries via the prod api's DB session; live
  `OpenFigiClient` calls via Rate Guard.

## Findings

### 1. Prod data state (read-only)

| Metric | Value |
|---|---|
| `holdings_13f` total | 15,995 |
| linked (`stock_id` set) | 1,996 — **12.5%** |
| `cusip_mapping_status` | `unresolved` 13,981 · `linked` 1,996 · `needs_review` 18 · **`pending_mapping` 0** |
| distinct CUSIPs | 2,169 total, **2,084 unlinked** |
| `cusip_ticker_map` rows | **98** (85 `high`, 11 `low`, 2 `review_needed:low`) |
| `stocks` | 177 |
| `quarter_end_date IS NULL` | **0** |

Per-quarter common-stock link rate: 2026-Q1 504/4278 (11.8%), 2025-Q4
465/3705 (12.6%), 2025-Q3 491/3849 (12.8%) — uniformly ~12%.

### 2. OpenFIGI works — not the blocker

Live `OpenFigiClient().map_cusips()` (via Rate Guard) on five "unresolved"
mega-caps → all resolve, and `evaluate_openfigi_matches` collapses OpenFIGI's
200+ per-CUSIP listing variants to one US-Common-Stock ticker at `high`
confidence:

`02079K107 → GOOG` · `92826C839 → V` · `023135106 → AMZN` ·
`060505104 → BAC` · `037833100 → AAPL` — all `confidence='high'`.

So OpenFIGI + `evaluate_openfigi_matches` + `bootstrap_stocks_from_cusip_map`
(which only excludes `review_needed:%`) form a sound chain.

### 3. `quarter_end_date` NULL — hypothesis disproven

`_apply_mappings_to_holdings` skips holdings with `quarter_end_date IS NULL`.
Prod has **0** such holdings — this is not a factor.

### 4. Root cause — a status-filter bug

`cusip_mapping_status` lifecycle:
- New holdings are ingested as **`pending_mapping`**
  (`thirteenf_holdings_ingest.py:191`).
- `_apply_mappings_to_holdings` (run via `backfill_stock_ids` / the
  `bootstrap_stocks` job) looks up *existing* `cusip_ticker_map` rows and, when
  it finds none, sets the holding to **`unresolved`** (`cusip_enrichment.py:355,
  365`). It never calls OpenFIGI — `unresolved` here just means "no row in the
  map yet", **not** "OpenFIGI tried and failed".
- Nothing ever moves `unresolved` back to `pending_mapping`.

So once `_apply_mappings_to_holdings` has run (it has — that is why prod has
0 `pending_mapping`), every unresolved holding sits in `unresolved` forever.

The two functions disagree on what "unresolved" means:

| Function | status filter |
|---|---|
| `enrich_unmapped_holdings` (creates OpenFIGI mappings) | `== "pending_mapping"` |
| `_apply_mappings_to_holdings` (applies existing mappings) | `IN ("pending_mapping", "unresolved", "needs_review")` |

`enrich_unmapped_holdings`'s `pending_mapping`-only filter means it queries a
status that essentially no longer occurs in prod → returns 0 holdings → creates
0 mappings → `cusip_ticker_map` stays at 98 → link rate frozen at 12.5%. The
`enrich_cusip` admin job and the `enrich_cusips_from_openfigi` entrypoint all
funnel through this filter, so all of them are no-ops on the real backlog.

## Recommendation — next steps

1. **Fix the bug (small, the real unblock).** Broaden
   `enrich_unmapped_holdings`'s query to
   `cusip_mapping_status.in_(["pending_mapping", "unresolved"])` — the holdings
   that genuinely have no mapping. Exclude `needs_review` (those are an
   ambiguous-result human queue; re-running OpenFIGI just re-flags them). Add a
   regression test: a holding in `unresolved` must be picked up by
   `enrich_unmapped_holdings`.
2. **Then build run-to-completion batching** (the original "Option A"). After
   the filter fix there are ~13,981 holdings to enrich at 100/run; the
   `enrich_cusip` job should loop in batches (with a safety cap) until none
   remain, then run `bootstrap_stocks_from_cusip_map` + `backfill_stock_ids`.
   OpenFIGI rate limiting is handled by Rate Guard, so the loop is safe.
3. **Operational run against prod** — a separate, explicitly-authorized step
   after 1+2 ship.

Expected impact: the 2,084 unlinked CUSIPs are dominated by ordinary US common
stock (mega-caps among them, all OpenFIGI-resolvable at `high` confidence), so
the link rate should rise substantially — from ~12% toward the share of
holdings that are US common equity.

## Implementation (PR — steps 1 + 2)

Branch: `claude/cusip-link-rate-enrichment-fix`.

- **Step 1 — the filter bug.** `enrich_unmapped_holdings` now selects holdings
  in `cusip_mapping_status IN ('pending_mapping', 'unresolved')` (was
  `== 'pending_mapping'`), with a non-NULL `cusip` and the CUSIP not already in
  `cusip_ticker_map`. `needs_review` stays excluded (the ambiguous-result human
  queue).
- **Step 2 — run-to-completion.** New `enrich_all_unmapped_holdings(db, *,
  client=None, batch_size=100, max_batches=300)` loops `enrich_unmapped_holdings`
  until no holding with an unmapped CUSIP remains — each batch maps every CUSIP
  it touches, so the unmapped-CUSIP pool strictly shrinks and the loop
  terminates (a `max_batches` hard cap and a no-progress guard back it up). It
  then runs `bootstrap_stocks_from_cusip_map` + `backfill_stock_ids` and returns
  a summary (`mappings_created`, `batches_run`, `new_stocks`, `holdings_linked`,
  `holdings_still_unmapped`). The `enrich_cusip` admin job now calls it.
- **Tests** — `test_13f_cusip_enrichment.py` gains: a regression test that an
  `unresolved` holding is enriched (red against the old filter), the
  skip-already-mapped behaviour, and a run-to-completion test.

Out of scope: the operational run against prod (a separate, explicitly
authorised step); surfacing the `enrich_cusip` job as an admin-UI button.

Verification: `docker compose run --rm --no-deps api pytest -q` — green.

## Review remediation (2026-05-21)

Two independent reviews — both **APPROVE / PASS**, no blockers. Advisories
addressed:

- **`unresolved` comment accuracy** (both reviews) — the comment claimed
  `unresolved` always means "OpenFIGI never consulted"; a no-match CUSIP also
  stays `unresolved` after OpenFIGI. The comment now states both cases and that
  the `cusip NOT IN cusip_ticker_map` clause is what prevents a re-query.
- **`bootstrap` / `backfill` placement** (review 2) — a comment now documents
  that they run after a completed loop and that a mid-loop failure is recovered
  by the retriable, resumable `enrich_cusip` job; DB-mutating work is
  deliberately kept off the exception path.
- **Test gap** — added `test_enrich_all_terminates_on_unresolvable_cusip`: a
  CUSIP OpenFIGI cannot resolve terminates the loop in one batch (does not spin
  to `max_batches`).

Re-verified: backend `pytest -q` green.
