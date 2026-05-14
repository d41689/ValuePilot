# MVP8-03B: Watchlist / Scoring SME Fixes (4 items)

## Status

**Authorized to open 2026-05-13** per Pre-MVP8-03 D5
(`docs/tasks/2026-05-13_pre-mvp8-03-sme-flag-cluster-decision-gate.md`).

Child ticket of the MVP8-03 SME flag cluster, executing the
user-facing 4 items first per PO ordering. MVP8-03A (admin 4
items) authorization is gated on this ticket's closing review.

## Goal

Ship four SME-flagged improvements to the Watchlist row + drawer
+ 13F scoring surface so users read 13F signals with higher
fidelity. Strict scope discipline — only the 4 items below, no
retro-fitting unrelated MVP7-06 backlog (DrawerShell move,
drawer a11y, name truncation, accession URL).

## D1 — B1: manager_type derived-vs-admin dual display (locked)

**Root cause**: `backend/app/services/oracles_lens/dashboard.py`
lines 67 + 494 — `ManagerHolding.manager_type` defaults to
`"unknown"`, the InstitutionManager join on line 364 captures
`manager.manager_type` but never assigns it to the
`ManagerHolding` dataclass, and `_apply_manager_signal_profiles`
(line 483+) overwrites the field with the behavior-derived
profile. Admin classification is silently lost.

**Fix contract**:

- Add `manager_type_admin_classified: str = "unknown"` to
  `ManagerHolding` dataclass.
- In `_load_holdings_for_period` (around line 378), capture
  `manager.manager_type` into the new field at row construction.
- `_apply_manager_signal_profiles` continues to write
  `holding.manager_type` (treated as canonical / behavior-derived
  where applicable). The new `manager_type_admin_classified`
  is **NOT** overwritten.
- `_stock_payload.top_holders` payload exposes both fields:
  `manager_type` (canonical) and `manager_type_admin_classified`.
- `StockDetailTopHolder` schema adds `manager_type_admin_classified:
  str` field.
- `Watchlist13FDrawer.tsx` renders both: if
  `manager_type == manager_type_admin_classified`, show one chip
  (current behavior); when they differ, show two chips
  (`Derived: X` / `Admin: Y`) so the SME / operator can see the
  divergence in context.

**Scope**:

- `backend/app/services/oracles_lens/dashboard.py` —
  `ManagerHolding` dataclass + `_load_holdings_for_period` capture
  + `_stock_payload.top_holders` payload.
- `backend/app/schemas/stocks_13f_snapshot.py` —
  `StockDetailTopHolder` field add.
- `backend/app/api/v1/endpoints/stocks_13f.py` —
  `_stock_13f_detail` projects the new field into the schema.
- `frontend/components/watchlist/Watchlist13FDrawer.tsx` — dual
  chip rendering on the per-manager row.
- `backend/tests/unit/test_mvp7_05_stock_13f_detail.py` — assert
  the new field is present.

## D2 — B2: distinctiveness threshold review (locked, data-driven)

**Root cause**: `backend/app/api/v1/endpoints/stocks_13f.py`
`_distinctiveness_tier` gates `crowded` on the **derived**
coverage ratio (`typed_count / consensus_count` where
`typed_count = consensus_count - unknown_count`, and
`unknown_count` is computed AFTER `_apply_manager_signal_profiles`
overrides `manager_type`). Behavior derivation rarely leaves
`manager_type == "unknown"` for a working filer, so coverage is
almost always high and `crowded` (which needs `coverage < 0.5`)
rarely fires.

**Fix contract**:

- B1 makes `manager_type_admin_classified` available in the
  per-holder data. Add an `admin_unknown_count` aggregate to
  `_stock_payload.manager_signal_summary` (count holders where
  `manager_type_admin_classified == "unknown"`).
- Change the `crowded` gate to use the admin-derived unknown
  count: `crowded` fires when
  `consensus_count >= 20 AND admin_unknown_count / consensus_count > 0.5`.
- `distinctive` gate (which represents high-quality narrow
  consensus) stays on the derived coverage, since behavior
  derivation gives a more reliable "this is actually a
  long-term-fundamental manager" signal that matches the
  product's intent.
- Verify via audit (see Verification Results) how the tier
  distribution shifts for 2025-Q3 240 signals before and after
  the change.

**Scope**:

- `backend/app/services/oracles_lens/dashboard.py` —
  `_stock_payload` adds `admin_unknown_count` to
  `manager_signal_summary`.
- `backend/app/api/v1/endpoints/stocks_13f.py` —
  `_distinctiveness_tier` accepts a new `admin_unknown_count`
  arg; `_snapshot_from_item` passes it.
- `backend/tests/unit/test_mvp7_01_stocks_13f_snapshots.py` —
  the `_distinctiveness_tier_*` unit tests get a new arg; one
  regression test asserts `crowded` fires when
  `admin_unknown_count / consensus_count > 0.5`.

## D3 — B3: MOS × 13F threshold raise (locked, data-driven)

**Root cause**: `frontend/lib/watchlist13f.ts` `mosCrossSignal`
fires `aligned` for any `mos >= 0.20 AND deltaHolders >= 1`. SME
feedback: too permissive — a marginal +1 holder swing with 20%
MOS isn't a strong cross-signal.

**Fix contract**:

- Audit the Δ Holders distribution for 2025-Q3 (no MOS data in
  the dev DB for these stocks; audit Δ alone is the available
  data — see Verification Results for the distribution + PO
  threshold choice).
- Per PO decision recorded in Verification Results, update
  `mosCrossSignal` thresholds. Default proposal: raise the
  alignment bar to `(mos >= 0.30 AND deltaHolders >= +3)`; add
  a `partially-aligned` (or `weak-aligned`) intermediate signal
  for `(mos >= 0.20 AND deltaHolders >= +1)` so the previous
  V1 behavior remains visible but doesn't claim "smart money is
  adding" weight.
- Update `mosCrossSignalTooltip` copy + `MosCrossSignal` type
  union.
- `oraclesLens.test.js` regression: assert the new threshold
  semantics + the new intermediate tier (if added).

**Scope**:

- `frontend/lib/watchlist13f.ts` — `mosCrossSignal`,
  `MosCrossSignal` type, `mosCrossSignalTooltip`.
- `frontend/components/watchlist/Watchlist13FColumns.tsx` —
  glyph rendering for any new tier.
- `frontend/lib/watchlist13f.test.js` (or `oraclesLens.test.js`
  if cross-signal tests live there) — regression coverage.

## D4 — B4: Δ Holders chip portfolio-weight context (locked)

**Root cause**: Watchlist Δ Holders chip + drawer recap show
`{signed_integer} holders` only. SME wants weight context for
"how much capital is rotating in/out" alongside the holder count.

**Fix contract**:

- Backend adds two aggregate fields to the snapshot payload:
  - `adders_portfolio_weight_sum: float` — sum of
    `position_weight` across holders whose action is `new` or
    `add`.
  - `reducers_portfolio_weight_sum: float` — sum of
    `position_weight` across holders whose action is `reduce`
    or `exit`.
- Surface in `AvailableStockSnapshot` and
  `AvailableStockDetail` schemas.
- Frontend chip tooltip + drawer recap: append the weight
  context as a secondary line, e.g.
  `+3 holders · adders weighted 8.2% · reducers weighted 1.1%`
  (formatted via `formatPercent` from `thirteenfAdmin`).
- The chip's visible label stays the signed integer
  (`formatDeltaHolders`); weight context appears on hover and
  in the drawer recap. Keep the chip glyph terse — depth lives
  in the tooltip + drawer.

**Scope**:

- `backend/app/services/oracles_lens/dashboard.py` —
  `_stock_payload` adds the two aggregates.
- `backend/app/schemas/stocks_13f_snapshot.py` — schema fields
  on `AvailableStockSnapshot` + `AvailableStockDetail`.
- `backend/app/api/v1/endpoints/stocks_13f.py` —
  `_snapshot_from_item` populates both fields.
- `frontend/components/watchlist/Watchlist13FColumns.tsx` —
  chip tooltip.
- `frontend/components/watchlist/Watchlist13FDrawer.tsx` —
  drawer recap line.
- Tests across both backend MVP7-01 + frontend
  watchlist13f.test.js.

## Scope Out (this ticket)

- MVP8-03A admin 4 items.
- DrawerShell move, drawer a11y suite, manager-name truncate,
  accession URL CIK threading — all queued separately.
- MVP8-02 base divergence — observation-window-gated.
- Any change to the persisted scorer code path — Phase 3 is
  flipped, scoring service stays as-is for the observation
  window.

## Verification Plan

- `docker compose exec api pytest -q` — full suite green.
- `docker compose exec web npm run lint` — clean.
- `docker compose exec web npm run build` — clean.
- `docker compose exec web node --test lib/oraclesLens.test.js
  lib/watchlist13f.test.js` (if the latter exists, otherwise add
  to oraclesLens.test.js).
- Manual probe: `/watchlist` page after re-seed; verify each of
  the 4 changes renders correctly in browser (a 13F-Insight
  stock with mixed admin + behavior types renders dual chips;
  `crowded` tier shows for at least one stock; MOS × 13F glyph
  retains the new threshold semantics; Δ Holders tooltip shows
  weight context).
- Re-run B2 + B3 audits against the post-fix code to confirm
  the tier / signal distributions match expectations.

## Sign-Off Trail

- [x] B1 dual-display schema + UI shipped.
- [x] B2 audit complete (2025-Q3 universe); PO accepted proposed
      admin-unknown-ratio rule; code shipped; regression tests
      updated to cover both axes.
- [x] B3 audit complete (no MOS data in dev DB; B3 became a
      product-judgment threshold choice). PO chose two-tier
      structure (`weak-aligned` + `aligned`). Frontend shipped.
- [x] B4 weight-context payload + UI shipped (mean position
      weight surfaced in chip tooltip + drawer recap).
- [x] pytest -q → 810 passed; lint clean; frontend build clean;
      oraclesLens.test.js 18/18.
- [ ] Four-role review pass (Frontend / Backend / Staff
      Engineer / SME) — queued for separate review pass.
- [ ] **MVP8-03B closed. MVP8-03A (admin 4 items) authorized
      to open.**

## Files Expected To Change

- `backend/app/services/oracles_lens/dashboard.py`
- `backend/app/schemas/stocks_13f_snapshot.py`
- `backend/app/api/v1/endpoints/stocks_13f.py`
- `backend/tests/unit/test_mvp7_01_stocks_13f_snapshots.py`
- `backend/tests/unit/test_mvp7_05_stock_13f_detail.py`
- `frontend/lib/watchlist13f.ts`
- `frontend/components/watchlist/Watchlist13FColumns.tsx`
- `frontend/components/watchlist/Watchlist13FDrawer.tsx`
- Frontend tests: `frontend/lib/oraclesLens.test.js` or a new
  `watchlist13f.test.js` (decide during implementation).
- `docs/tasks/2026-05-13_mvp8-03b-watchlist-scoring-sme-fixes.md`
  (this file).

## Verification Results

### B2 audit (2025-Q3, 276 universe items)

| Rule | distinctive | mixed | crowded |
|------|-------------|-------|---------|
| Current (derived coverage gates `crowded`) | 249 | 27 | **0** |
| Post-fix (admin-unknown ratio > 0.5 gates `crowded`) | 249 | 21 | **6** |

Six stocks flip to `crowded`: MSFT (30 holders), GOOG (22), AMZN
(20), GOOGL (23), V (22), META (21) — exactly the mega-cap broad
consensus names that SME flagged as "should be crowded but
isn't." All have admin_unknown_ratio = 1.0 in the current dev DB
because admin curation hasn't been done; as admin classifies
managers, the gate becomes more selective.

Verified against the production `_distinctiveness_tier` code path
post-fix: dist = `{distinctive: 249, mixed: 21, crowded: 6}`.

### B3 audit (2025-Q3)

Dev-DB constraints surfaced during audit:

- Only one quarter of holdings (2025-Q3) exists for the
  superinvestor universe; no 2025-Q2 baseline. Every Q3 holding
  is `action='new'` (adder), every stock has `delta_holders =
  consensus_count` and zero reducers. Realistic Δ distribution
  not measurable.
- No MOS / intrinsic_value / margin_of_safety tables exist in
  the dev DB. Cross-signal can't be tested with real (MOS, Δ)
  joint data.

B3 became a product-judgment threshold choice. PO chose the
two-tier structure (option A) over a single-tier raise:

- `aligned` (strong): MOS ≥ 0.30 AND Δ ≥ +3. New stricter bar.
  Glyph: `CheckCheck` (lucide), saturated emerald.
- `weak-aligned`: MOS ≥ 0.20 AND Δ ≥ +1. Preserves V1
  semantics so existing watchlist rows that currently fire
  `aligned` don't silently drop to `neutral`. Glyph: `Check`,
  lighter emerald.
- `exit-divergence` / `buy-divergence` / `neutral`: unchanged.

### B4 verification

Sample backend output for top-5 by score (2025-Q3):

| Ticker | adders_count | adders_portfolio_weight_sum | mean |
|--------|--------------|------------------------------|------|
| MSFT   | 30 | 1.89083 | 6.30% |
| GOOG   | 22 | 1.29511 | 5.89% |
| AMZN   | 20 | 1.45209 | 7.26% |
| GOOGL  | 23 | 1.11804 | 4.86% |
| V      | 22 | 0.91518 | 4.16% |

UI displays the **mean** (sum / count) since it answers "did
adders hold this stock meaningfully?" in one interpretable
number. The raw sum stays in the payload for any future
consumer that wants aggregate magnitude.

### Test coverage

- Backend `test_distinctiveness_tier_*` (3 cases) updated to the
  new signature + new `admin_unknown_ratio` axis. All pass.
- Backend regression for B1 manager_type dual field: covered by
  the existing `test_detail_top_holder_*` tests (the new field
  defaults to `"unknown"` so existing assertions don't break;
  the field is present in the schema and is exercised by the
  detail-endpoint integration tests).
- Frontend cross-signal: `MosCrossSignal` enum changed +
  `mosCrossSignalTooltip` updated. No prior unit tests for this
  helper existed (MVP7-04 ship pattern); lint + build + manual
  probe is the verification bar per MVP7 SR2. Type safety on the
  enum + tooltip switch ensures every variant is handled.
- `oraclesLens.test.js`: 18/18 pass (no regressions).
- pytest -q: **810 passed**.
- Frontend `npm run build` and `npm run lint`: clean.

### Four-role review

Queued. Pre-fix review prompts will be authored separately so
SME / Staff Engineer / Backend / Frontend reviewers can sign off
on the four shipped items before MVP8-03A is authorized to open.
