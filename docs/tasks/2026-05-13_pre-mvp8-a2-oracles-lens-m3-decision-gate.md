# Pre-MVP8-A2: Oracle's Lens M3 — Decision Gate

**Status: CLOSED — Option B selected 2026-05-13**
**Date: 2026-05-13**
**Blocks: MVP8-A2 (Oracle's Lens M3 valuation + quality overlay)**

---

## 1. Current State Audit

### What M3 is

Per the Oracle's Lens product plan (`docs/plans/13f_oracles_lens_dashboard_product_plan.md`),
M3 is the "Business Quality Overlay + Valuation Reference" layer:

- **Quality overlay**: Piotroski F-Score (`score.piotroski.total`) + earnings
  predictability (`quality.earnings_predictability`) + financial strength
  (`quality.financial_strength`), sourced from `metric_facts` (Value Line parse).
- **Valuation reference**: 18-month high/low VL price targets
  (`target.price_18m.mid` / `proj.long_term.high_price` /
  `proj.long_term.low_price`) + owner earnings per share, sourced from
  `metric_facts`.
- **Owner earnings**: `owners_earnings_per_share` from `metric_facts`.

### Where M3 is already implemented

| Surface | Status |
|---|---|
| `/13f/oracles-lens` page | **Already implemented** (legacy `oraclesLens.js` + `build_oracles_lens_dashboard()`) |
| MVP7 Watchlist 13F drawer | **Not implemented** |
| Persisted scoring path (`_apply_persisted_scores`) | **Not implemented** |
| 13F detail endpoint (`/stocks/{id}/13f-detail`) | **Not implemented** |

The existing implementation lives in:
- `backend/app/services/thirteenf_admin_dashboard.py` — `_quality_overlay_by_stock()` (line 786) and `_valuation_reference_by_stock()` (line 937), called from `build_oracles_lens_dashboard()` (lines 191–218).
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` — M3 rendering (1176-line legacy page).
- `frontend/lib/oraclesLens.js` — client-side lens computation including quality overlay integration.

The legacy page at `/13f/oracles-lens` is the **only surface** that shows M3 data today.

---

## 2. Data Environment Reality (Dev DB, 2026-05-13)

| Metric | Dev Count |
|---|---|
| Unique stocks in 13F holdings (`holdings_13f`) | 1,183 |
| Stocks with any Value Line data (`metric_facts`, `stock_id` linked) | 7 |
| Stocks with `score.piotroski.total` (in `value_json`) | 6 |
| Stocks with `target.price_18m.mid` | 7 |
| Piotroski stocks also in 13F holdings | **5** (ADBE, FICO, FNV, GOOG, MTDR) |
| VL target stocks also in 13F holdings | **5** (ADBE, FICO, FNV, GOOG, MTDR) |

**Important**: Dev DB has only 7 stocks with Value Line data loaded (dev fixture
limitation). In production, the proportion depends on how many stocks have
been processed by the Value Line parser. The 5-stock overlap is a dev artifact,
not a structural ceiling.

**Note on `score.piotroski.total` storage**: The Piotroski score is stored in
`metric_facts.value_json`, not `value_numeric`. The `_quality_overlay_by_stock`
function reads from `value_json` directly. Only one row (FNV, most recent
period) has `value_numeric` populated (value = 4.0); all others have
`value_numeric = null`. This is not a data defect — it is how the Value Line
parser stores composite scores.

---

## 3. Scope Options

### Option A — M3 stays on Oracle's Lens page only (status quo)

No new work. The `/13f/oracles-lens` page already surfaces M3. The Watchlist
13F drawer (MVP7) surfaces per-stock 13F consensus data but not quality or
valuation overlay.

**Tradeoff**: Users who discover a stock via the Watchlist drawer must
navigate to `/13f/oracles-lens` to see quality/valuation context. Two separate
research workflows.

**Engineering cost**: Zero.

### Option B — Extend M3 into the Watchlist 13F drawer

Add quality overlay + valuation reference to the `GET /stocks/{id}/13f-detail`
endpoint response (already used by `Watchlist13FDrawer`). The drawer gets a
new "Quality & Valuation" section using the same data as M3.

Backend: extract `_quality_overlay_by_stock` and `_valuation_reference_by_stock`
into shared helpers callable from both `build_oracles_lens_dashboard()` and the
`/stocks/{id}/13f-detail` endpoint. No new tables, no schema changes.

Frontend: add a collapsible section to `Watchlist13FDrawer.tsx` (shipped in
MVP7-05).

**Tradeoff**: M3 context is in the Watchlist workflow without leaving the page.
But data coverage is sparse until more Value Line files are ingested — the
drawer would show "Quality data not available" for most stocks. The UI must
treat missing data as a first-class state (per product plan §2).

**Engineering cost**: ~1 day. Backend: 2–3 functions refactored. Frontend:
~60 lines added to the drawer.

### Option C — Full M3 integration on both surfaces + persisted scoring path

Option B plus: thread quality overlay and valuation reference into the persisted
scoring path so that `_apply_persisted_scores` includes M3 signals. This enables
offline ranking and alerting on quality or valuation changes.

**Tradeoff**: More complete but significantly more scope. The persisted path
adds complexity and requires a decision about how to store M3 signals (new
`metric_facts` aggregation vs. derived at query time).

**Engineering cost**: 3–5 days. Requires a separate persisted-M3 design
decision before implementation.

---

## 4. PO Decision Points

| # | Question | Options |
|---|---|---|
| D1 | Which surfaces should show M3? | A (Oracle's Lens only), B (+ Watchlist drawer), or C (both + persisted path) |
| D2 | What is the minimum viable quality signal for the drawer? | Full Piotroski + VL targets, or just a "quality available" badge that links to Oracle's Lens |
| D3 | How should missing data be surfaced? | Silent omission (don't render the section), or explicit "Quality data not yet available for this stock" message per product plan §2 |
| D4 | Is M3 drawer work blocked on Value Line coverage? | Accept thin coverage now and ship with appropriate "limited data" framing, or wait until coverage threshold is reached (define threshold) |

---

## 5. Recommended Scope (Engineering View)

**Option B** with explicit missing-data treatment (D3 = explicit message,
D4 = ship with thin coverage and good framing) is the recommended path. It:

- Puts M3 context at the point of Watchlist research without changing the
  Oracle's Lens page.
- Uses only existing data — no new ingestion, no schema changes.
- Keeps scope tight: refactor two service helpers + ~60 lines in the drawer.
- Aligns with the product plan's mandate: "Show coverage explicitly rather
  than hiding it."

Option C is premature until there is a clear use case for persisted M3 scoring
(alerting, weekly digest, etc.).

---

## 6. Files That Would Change (Option B)

- `backend/app/services/thirteenf_admin_dashboard.py` — extract quality/valuation helpers
- `backend/app/api/v1/endpoints/thirteenf.py` — enrich `GET /stocks/{id}/13f-detail` response
- `frontend/components/admin13f/Watchlist13FDrawer.tsx` — Quality & Valuation section
- `docs/tasks/2026-05-13_pre-mvp8-a2-oracles-lens-m3-decision-gate.md` — this file

---

## 7. Sign-Off

- [x] PO selects **Option B** 2026-05-13. D1: Oracle's Lens + Watchlist drawer, no persisted path. D2: compact overlay reusing existing service helpers. D3: explicit "not yet available" when no VL data. D4: ship with thin coverage + honest framing.
- [x] Engineering confirms Option B in scope for MVP8-A2.
- [x] MVP8-A2 ticket opened: `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md`.
