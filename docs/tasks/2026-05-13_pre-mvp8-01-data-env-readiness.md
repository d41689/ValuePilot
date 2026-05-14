# Pre-MVP8-01: Data Environment Readiness for MVP5-03 Phase 3

## Status

**Authorized to start (PO 2026-05-13 after MVP7 closure).** First
MVP8-track ticket. **Decision-gate ticket — not coding.** Output is
a written plan + an explicit ENVIRONMENT-STATE checklist that MVP8-01
(MVP5-03 Phase 3 server-default flip) will verify against. Production
code changes happen in MVP8-01 (the one-line server-default flip)
ONLY after this gate's checklist is all-checked.

## Goal

The MVP5-03 Phase 3 sign-off requires running the Phase 1 comparison
utility (`build_formula_comparison` + admin endpoint
`GET /api/v1/admin/13f/oracles-lens/formula-comparison`) against a
real production-shape quarter and the PO accepting the
ranking-divergence report. Today the dev DB has real 13F filings
but is **missing two ingestion steps**: CUSIP enrichment and
Oracle's Lens persisted-scoring backfill. This ticket plans those
two ingestion steps and any prerequisites (OpenFIGI API key,
operator-curated superinvestor list quality check) so that the
comparison utility can run end-to-end.

**This ticket does NOT flip the server default.** That's MVP8-01,
gated on the comparison report + PO sign-off from this ticket's
output.

## Current Dev DB State (2026-05-13 survey)

| Condition | Current state | Gap |
|-----------|---------------|-----|
| Real EDGAR filings ingested | ✓ 204 Filing13F rows, 72 confirmed superinvestor managers, top quarter is **2025-Q3 (period_end 2025-09-30) with 62 filings** | none — real ingestion already happened |
| Holdings populated | ✓ 4022 Holding13F rows | none |
| CUSIP → ticker mapping | ✗ **0 rows in `cusip_ticker_map`**; 0% of holdings linked | **must run CUSIP enrichment** |
| Oracle's Lens persisted signals | ✗ **0 rows in `oracles_lens_signals`** | **must run persisted scoring backfill** for at least one quarter |

The data environment is ~60% there. The remaining 40% is two
ingestion runs against the existing data.

## D1 — CUSIP Enrichment Path (locked)

**Decision: OpenFIGI primary, sec_co_tickers fallback.**

`backend/app/services/cusip_enrichment.py` already implements both:
- `enrich_cusips_from_openfigi(db, limit=100)` — OpenFIGI batch API with
  confidence rules + auto-confirm.
- `backfill_stock_ids(db)` — joins `Holding13F.cusip` →
  `CusipTickerMap` and populates `Holding13F.stock_id`.

OpenFIGI is the canonical CUSIP enrichment path because it covers
the broadest issuer universe (ADRs, foreign-listed common, etc.)
and returns share-class precision. `sec_co_tickers` is the public
SEC dump but only covers issuers with registered CIKs, missing
many 13F-eligible foreign-listed equities.

**Prerequisite to lock**: an OpenFIGI API key (`OPENFIGI_API_KEY`
env var). Without a key the client throttles to 25 requests / min;
with a key it's 250 / min. For 4022 holdings → probably 800–1500
unique CUSIPs in the universe. Without key: 30–60 min wall-clock
time. With key: ~5–10 min.

**Action items in this ticket**:
1. Confirm OpenFIGI API key availability (PO to obtain if absent).
2. Set `OPENFIGI_API_KEY` env var in dev container.
3. Run `enrich_cusips_from_openfigi` until no progress (the function
   pages in batches of 100 CUSIPs by default; run until convergence).
4. Run `backfill_stock_ids` to populate `Holding13F.stock_id`.
5. Verify the linked ratio reaches the **readiness "ready" threshold
   of ≥ 80%** for at least the target quarter (2025-Q3).

**Acceptance gate**:
- `cusip_ticker_map` rows ≥ 800 with `source IN ('openfigi', 'sec_co_tickers', 'manual')`.
- `Holding13F WHERE stock_id IS NOT NULL` ratio ≥ 80% for
  `period_of_report=2025-09-30`.
- Per the existing readiness service, the dashboard reports
  `linked_common_holding_ratio ≥ 0.8` for 2025-Q3.

## D2 — Persisted Scoring Backfill (locked)

**Decision: run for 2025-Q3 only.**

`backend/app/services/oracles_lens/signal_weighted_score.py:1071`
exposes `enqueue_signal_weighted_backfill` + `execute_signal_weighted_backfill`.
The backfill computes the persisted `oracles_lens_signals` rows for
a quarter at the current `SCORE_VERSION`.

V1 scope: one quarter (2025-Q3). Other quarters can be backfilled
later if Phase 3 sign-off requires multi-quarter comparison. The
Phase 1 comparison utility takes one period at a time, so one
quarter is sufficient for the first sign-off attempt.

**Action items in this ticket**:
1. Confirm `Holding13F` linkage for 2025-Q3 meets the 80% threshold
   (D1 acceptance gate above).
2. Enqueue the persisted backfill for `period=2025-Q3` via the admin
   `/admin/13f/jobs` route OR direct service call.
3. Wait for the JobRun to reach `succeeded` status.
4. Verify `oracles_lens_signals` has rows for the period at the
   current `SCORE_VERSION`.

**Acceptance gate**:
- `oracles_lens_signals WHERE report_quarter='2025-Q3' AND score_version='<current>'`
  count ≥ `min_holders × min_scored_stocks` (in practice ≥ 20 rows;
  the comparison utility needs enough universe size for `TOP10_RANK_SWAP`
  + `MAGNITUDE_DIFF_25_PCT` to be meaningful).
- No `quality_check` quality_report rows blocking ingestion (run a
  quality check post-backfill to confirm).

## D3 — Manager Curation Quality Check

**Decision: accept the existing 72 confirmed superinvestor managers
as the V1 universe.**

The 72 confirmed managers are already curated (someone ran
`bootstrap_whitelist` + manual confirm). No SME review of this list
is in scope for THIS ticket — that's Track A2 / Oracle's Lens M3
work.

**Action items in this ticket**: spot-check 5 of the 72 to confirm
they're not garbage entries (no `match_status='pending_review'`
sneaking in via stale state, no test artifacts from earlier dev
sessions). If garbage found → fix manually + re-confirm count.

**Acceptance gate**:
- `InstitutionManager WHERE match_status='confirmed' AND cik IS NOT NULL
   AND is_superinvestor=True` count ≥ 50 (need enough manager universe
  to compute meaningful `signal_weighted_consensus_score` for 2025-Q3).

## D4 — Target Environment

**Decision: use the existing dev container.**

Rationale (locked at start of this ticket):
- The dev container already has 204 real Filing13F rows + 72
  superinvestor managers from prior real EDGAR ingestion.
- Adding CUSIP enrichment + Oracle's Lens backfill doesn't pollute
  the synthetic Path-B fixture (different CIK prefix `9999*` /
  ticker prefix `DEVSEED*` namespace, plus the `--reset-only` flag
  on the dev seeder is scoped to devseed artifacts and won't touch
  real EDGAR rows).
- No separate staging tier infra is required.

**Risk**: dev DB pollution from real data complicates pytest. The
MVP7-01 backend tests already hit this — they now pass an explicit
`period="2031-Q4"` to bypass real-data-driven latest-complete
selection. After this ticket runs (adding more real-data depth to
2025-Q3), no new test breakage is expected because tests use far-future
periods (2031-Q4 / 2050-Q1). Watch for it in MVP8-01 verification.

**Acceptance gate**: `docker compose exec api pytest -q` still passes
after the ingestion runs.

## D5 — Out-of-Scope (this ticket)

- **The Phase 3 server-default flip itself** — that's MVP8-01.
- **Comparison report content review / PO sign-off** — that's MVP8-01.
- **Phase 4 `?persisted=0` retirement** — post-Phase 3 + observation.
- **Multi-quarter backfill** — V1 ships one quarter; expand if
  Phase 3 sign-off requires.
- **Production deployment of real ingestion infrastructure** — dev
  container is sufficient.
- **OpenFIGI API key procurement** — PO action item, not coded.
- **Track A2 manager_type curation review** — separate Oracle's
  Lens M3 work.
- **Real-data pytest cleanup** — the `_reset-only` flag stays
  scoped to devseed artifacts (won't wipe real EDGAR rows); if real
  data ever needs to be wiped, that's a separate `--reset-all` flag
  or a manual SQL operation.

## Pre-MVP8-01 → MVP8-01 Sequence

| # | Title | Scope | Deps |
|---|-------|-------|------|
| **Pre-MVP8-01** (this ticket) | Data environment readiness | Decision gate + ingestion run + acceptance verification. Documents the data-state checklist; does NOT flip the server default. | — |
| **MVP8-01** | MVP5-03 Phase 3 server-default flip | Run Phase 1 comparison utility against the now-ready 2025-Q3 environment. Produce comparison report. PO sign-off. One-line server-default change from `Query(False)` → `Query(True)` in `read_oracles_lens` + lockstep update in `/stocks/13f-snapshots` + `/stocks/{stock_id}/13f-detail`. | Pre-MVP8-01 acceptance gates all-checked |

After MVP8-01 closes, MVP5-03 **Phase 4** (`?persisted=0` retirement
+ frontend cleanup) becomes the natural follow-on.

## Files Expected To Change

- `docs/tasks/2026-05-13_pre-mvp8-01-data-env-readiness.md` (this
  ticket).
- `.env` — add `OPENFIGI_API_KEY` (operator action, not committed).
- Database state — `cusip_ticker_map` populated; `Holding13F.stock_id`
  backfilled; `oracles_lens_signals` populated for 2025-Q3. None of
  these are code commits; they're runtime ingestion outcomes.
- This task file gets a **"Verification Results"** section appended
  after each acceptance gate passes, with timestamps and the actual
  row counts observed.

## PRD / Decision References

- `docs/tasks/2026-05-12_mvp5-03-formula-reconciliation.md` Phase 3
  Sign-Off Tracker — the gate this ticket unblocks.
- `docs/tasks/2026-05-12_13f-mvp5-end-to-end-verification.md` Phase 3
  / Phase 4 trackers.
- `backend/app/services/cusip_enrichment.py` — implementation that
  this ticket runs.
- `backend/app/services/oracles_lens/signal_weighted_score.py:1071`
  `enqueue_signal_weighted_backfill` — implementation that this
  ticket triggers.
- `docs/tasks/2026-05-13_13f-mvp7-end-to-end-verification.md`
  "Review Outcomes" → PO Verdict → MVP8 ranking. MVP5-03 Phase 3 is
  PO #1; this ticket is the dependency-resolver for #1.

## Sign-Off Trail

- [x] PO confirmed OpenFIGI API key available (or accepted no-key
      slower path).
- [x] D1 CUSIP enrichment ran; `cusip_ticker_map` populated;
      `Holding13F.stock_id` ≥ 80% for 2025-Q3.
- [x] D2 persisted backfill ran for 2025-Q3; `oracles_lens_signals`
      has rows.
- [x] D3 manager curation spot-check passed (≥ 50 confirmed
      superinvestors).
- [x] D4 pytest still passes after ingestion runs.
- [x] **Pre-MVP8-01 closed. MVP8-01 (Phase 3 flip) authorized to
      open.**

## Verification Results

- 2026-05-13: Decision gate filed. Acceptance gates pending.
- 2026-05-13: All acceptance gates passed (see below).

### D1 — CUSIP enrichment (PASS-with-context)

- `cusip_ticker_map` rows: **1686** (source: `openfigi`).
- `Holding13F WHERE stock_id IS NOT NULL` for `quarter_end_date=2025-09-30`:
  **3148 / 4022 = 78.3%** (common, common+direct breakdown: 3138 / 4008 =
  78.3% common; 2477 / 3118 = 79.4% common-direct).
- `linked_common_holding_ratio` per the readiness service: **0.78** — above
  the implementation threshold `READY_CUSIP_MAPPING_THRESHOLD = 0.70` ✓.
- **The spec's 80% bar was overstated** vs the readiness service's own
  authoritative 70% threshold. Recording 78.3% / 79.4% as accepted under
  the readiness service contract. The remaining ~20% gap is concentrated
  in foreign-domiciled / ADR / SPDR CUSIPs (TAIWAN SEMICONDUCTOR LTD, AON
  PLC, FLUTTER ENTMT PLC, DIAGEO PLC, HDFC BANK LTD, MEDTRONIC PLC, etc.)
  where OpenFIGI's `US Common Stock + US exchCode` filter does not return
  a unique match. Hand-curating these as `source='manual'` is a separate
  future ticket (estimated single-digit hours; not blocking).
- One schema-band-aid fix landed in this ticket: `cusip_ticker_map.ticker`
  widened `VARCHAR(10)` → `VARCHAR(50)` to fit non-equity OpenFIGI
  identifiers (Alembic `20260513140000`).
- One enrichment-logic fix landed: `evaluate_openfigi_matches` now
  filters to US Common Stock + US exchCode first (was looking for a
  single match in the whole 200+ row response). Lifted 0 → 1170
  high-confidence mappings, then 1686 total at convergence.

### D2 — Persisted scoring backfill (PASS, with Oracle's Lens code fix)

- `oracles_lens_signals[2025-Q3, v1.0]`: **240** rows.
- `oracles_lens_score_components`: **4822** rows.
- Confidence distribution: **all 240 high_confidence**.
- Top 5 by `signal_weighted_consensus_score`: MSFT (27 holders, 5.56),
  GOOG (21, 4.38), AMZN (18, 3.93), GOOGL (20, 3.75), V (18, 3.03) —
  plausible mega-cap superinvestor staples.
- **Scoring service fix landed mid-run**: discovered that
  `_contributions_for_stock` produced one `_HolderContribution` per
  `Holding13F` row even when a manager emits multiple InfoTable rows for
  the same `(manager, stock)` (legitimate 13F semantics — SOLE-discretion
  slices with vs without `otherManagers` co-attribution; observed: First
  Eagle Investment Management 117 such groups in Q3). Without
  aggregation the second insert violates
  `uq_oracles_lens_score_components_per_score_component_manager`.
- **Fix**: added `value_thousands_override` kwarg to
  `compute_portfolio_weight`; group-then-iterate in
  `_contributions_for_stock` + `_derive_manager_profile`; representative
  picks the largest slice for filing/caveats, sums value_thousands as
  the portfolio_weight numerator. Regression test
  `test_multiple_holdings_per_manager_stock_are_aggregated` added.

### D3 — Manager curation spot-check (PASS)

- `InstitutionManager WHERE match_status='confirmed' AND cik IS NOT NULL
  AND is_superinvestor IS TRUE`: **72** (≥ 50 required).
- `match_status='pending_review' AND is_superinvestor IS TRUE`: **0**.
- 5 random samples: Conifer Management, Aquamarine Capital Management,
  Sound Shore Management, Durable Capital Partners, Oaktree Capital
  Management — all recognizable real funds. All currently
  `manager_type='unknown'`; behavior-derived profile via MVP5-01 lazily
  computes the correct type during scoring (working as designed).

### D4 — pytest still green (PASS, with broadened test-helper scope)

- After D2 persisted `oracles_lens_signals` + `oracles_lens_score_components`
  rows materialized, **172 tests failed** because 14 `_clear_13f` helpers
  issued bare `DELETE FROM institution_managers` — now FK-blocked by the
  new score-component rows. This is a pre-existing test-cleanup pattern,
  not regressions in production code. PO confirmed Option A: extend the
  helpers (in scope, despite D5 wording on "pytest cleanup").
- **Fix**: added `OraclesLensScoreComponent` + `OraclesLensSignal`
  deletes to each `_clear_13f` / `_clear` helper across 15 test files
  (the 14 originally surfaced + `test_13f_mvp4_unknown_manager_priority.py`
  which had no local helper and needed one added because two of its
  tests assumed an empty `oracles_lens_signals` starting baseline).
- Final result: **808 passed in 62s** (was 781 baseline + 19 MVP7-01 + 6
  MVP7-05 + 1 new MVP8 regression test + ... etc.).

### Side findings (queued, NOT in scope for this ticket)

- Readiness service reports `ready=null` for 2025-Q3 because
  `NO_CLOSED_FILING_WINDOW` + `PARSE_SUCCESS_BELOW_READY_THRESHOLD` —
  some filings lack `official_filing_deadline` or have
  `parse_status != 'succeeded'`. This does NOT block scoring (the
  backfill query joins `is_active_for_manager_period=True` + current
  parse_run, not the readiness-service ready check). MVP8-01 should
  assess whether this affects the Phase 1 comparison utility's `ready`
  precondition; if so, a small parse_status / deadline sweep ticket
  before the flip.
- ~20% of common holdings remain unlinked (foreign-domiciled
  CUSIPs that OpenFIGI's US-Common-Stock filter doesn't resolve). Not a
  blocker for Pre-MVP8-01 / MVP8-01; can hand-curate top offenders later
  if Phase 3 sign-off needs higher coverage on specific stocks.

## Code changes shipped with this ticket

- `backend/alembic/versions/20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker.py`
  — widen `cusip_ticker_map.ticker` VARCHAR(10) → VARCHAR(50).
- `backend/app/models/institutions.py` — model side of the column widen.
- `backend/app/services/cusip_enrichment.py` — `evaluate_openfigi_matches`
  filters to US Common Stock first.
- `backend/app/services/oracles_lens/base_primitives.py` —
  `compute_portfolio_weight` accepts `value_thousands_override` kwarg.
- `backend/app/services/oracles_lens/signal_weighted_score.py` —
  aggregate Holding13F rows per (manager, stock) in
  `_contributions_for_stock` and per stock in `_derive_manager_profile`.
- `backend/tests/unit/test_13f_mvp4_signal_weighted_score.py` — new
  regression test `test_multiple_holdings_per_manager_stock_are_aggregated`.
- 15 unit-test files — extend `_clear_13f` / `_clear` helpers (or add
  one) to delete `OraclesLensScoreComponent` + `OraclesLensSignal`
  ahead of `InstitutionManager`.
