# Pre-MVP7-01: Watchlist × 13F Insight Decision Gate

## Status

**Authorized to start (PO 2026-05-13 after MVP6 closure).** First
MVP7-track ticket. **Planning / decision-gate ticket — not coding.**
Output is a written plan that becomes the MVP7-01..N task sequence
backbone.

## Goal

Fuse the user-facing `/watchlist` surface with the 13F automation
engine built across MVP1–MVP6. Watchlist is the daily driver for
value investors; 13F is the differentiating signal ValuePilot's
backend produces. Until now they have been parallel surfaces —
this gate defines the V1 product fusion as a set of four 13F-derived
columns rendered on each watchlist row, grouped under a `13F` header
that carries the quarter label.

The decisions captured here drive each subsequent MVP7-N ticket's
scope. Production code changes happen in those follow-up tickets,
not this one.

## Product Framing

A value investor on `/watchlist` asks: **"what does the latest 13F
say about THIS stock?"** — distinct from `/13f/oracles-lens` which
ranks the whole universe. The four highest-density signals (PO
locked 2026-05-13):

1. **Conviction** — is smart money positioned heavily here, by
   percentile across the ranked universe?
2. **Δ Holders** — what was the net activity last quarter?
3. **Distinctiveness** — is this a concentrated few-deep-value-funds
   conviction, or generic crowded-fund ownership?
4. **Caveats** — what data-quality flags should temper the read?

These cross-signal with the existing **MOS** column to produce
the value-investor read: high MOS + smart money adding → value
setup confirmed; high MOS + smart money exiting → re-examine FV.

## Locked Design Decisions (PO 2026-05-13)

### D1. The Four V1 Columns

Under the `13F (YYYY-Qn, as of YYYY-MM-DD)` group header on
`/watchlist`, four columns in this order:

| # | Column | Display | Sort | Source field |
|---|--------|---------|------|--------------|
| 1 | **Conviction** | percentile chip (`Top 15%` / `Mid 50%` / `Bot 25%`) | by raw `conviction_score` desc | `conviction_score` in `_stock_payload` + universe-rank percentile computed server-side |
| 2 | **Δ Holders** | signed integer chip (`+3` / `-1` / `0`) | by signed delta desc | `adders_count − reducers_count` |
| 3 | **Distinctiveness** | 3-tier chip (`Distinctive` / `Mixed` / `Crowded`) | by tier ordinal desc | derived from `distinctive_consensus_score` + `manager_signal_quality_coverage` |
| 4 | **Caveats** | chip / icon (`OK` / ⚠ / ⚠⚠) | by severity asc | `caution_flags` aggregate + `score_confidence` |

Things explicitly **NOT** column-level (deferred to drawer in
MVP7-05):

- Top 3 holders manager names + portfolio weights + manager_type
  badges + last-quarter action.
- Per-manager position size change magnitude.
- Caution flag detail breakdown.

### D2. Quarter Label in Group Header

Group header reads `13F (YYYY-Qn, as of YYYY-MM-DD)` where the
date is the latest filing-deadline date the snapshot covers (not
the API call time). Example: `13F (2025-Q4, as of 2026-02-14)`.

The quarter resolves to `latest_usable_quarter` per the existing
readiness service. The "as of" date is the SEC filing deadline
for that period (45 days after period end).

### D3. Empty State

For stocks where no 13F filer holds the security at or above
the §240.13f-1 threshold (small caps, recent IPOs, foreign
listings outside §13F scope), each of the four cells renders
`—` with a tooltip: *"No 13F-filer holds this stock above the
$200M AUM reporting threshold for {quarter}."* Caveats column
shows neutral `—` not ⚠.

For stocks where a 13F snapshot exists but with `< min_holders`
qualifying ranked managers, render `—` with tooltip: *"Below
min_holders threshold ({n}/{min_holders}). Insufficient consensus
for ranking."*

### D4. Responsive Strategy

Two-tier collapse:

- **≥ 1280px (lg+):** all four columns visible inline.
- **768–1279px (md):** entire 13F group collapses behind a
  group-header click toggle; default state collapsed for first
  visit, then per-user persisted in localStorage.
- **< 768px (sm):** entire 13F group hidden; group header
  renders as a row-level "+ Show 13F" link that expands to a
  per-row stacked view (mobile-only, not in V1 scope — defer).

### D5. MOS × 13F Cross-Signal as Visual Enhancement (not a column)

The existing **MOS** column gets a single-character status glyph
appended to its chip:

| Glyph | Condition | Meaning |
|-------|-----------|---------|
| ✓ (green) | MOS ≥ 20% and Δ Holders ≥ +1 | "Aligned: value setup confirmed" |
| ⚠ (amber) | MOS ≥ 20% and Δ Holders ≤ −1 | "Re-examine: smart money exiting your discount" |
| ⚠ (amber) | MOS ≤ 0% and Δ Holders ≥ +1 | "Re-examine FV: they may see a catalyst" |
| (no glyph) | otherwise | neutral or insufficient data |

Hover tooltip on each glyph explains the cross-signal in one
sentence. NOT a sortable column — the underlying MOS sort
behavior is unchanged.

## Backend API Contract

### New endpoint

```
POST /api/v1/stocks/13f-snapshots
Body: {
  "stock_ids": [int, ...],
  "period": "latest" | "YYYY-Qn"   // optional; defaults to "latest"
}
```

Response:

```json
{
  "period": "2025-Q4",
  "period_filing_deadline": "2026-02-14",
  "universe_size": 87,          // total ranked stocks in the period
  "snapshots": [
    {
      "stock_id": 123,
      "available": true,
      "conviction_score": 4.32,
      "conviction_percentile": 0.85,   // 0..1, higher = stronger
      "delta_holders": 2,              // adders_count − reducers_count
      "adders_count": 3,
      "reducers_count": 1,
      "distinctiveness_tier": "distinctive" | "mixed" | "crowded",
      "caveat_severity": "ok" | "caution" | "high-caution",
      "caveat_codes": ["PARTIAL_COVERAGE", ...],
      "score_confidence": "high_confidence"
    },
    {
      "stock_id": 456,
      "available": false,
      "unavailable_reason": "below_min_holders" | "no_holders"
    }
  ]
}
```

Implementation notes:

- Reuse `build_oracles_lens_dashboard(...)` to compute the full
  universe ranking for the period, then filter to requested
  `stock_ids`. The dashboard run is the expensive part; filtering
  is cheap.
- Cache the dashboard payload by (`period`, `score_version`,
  `score_inputs_hash`) for 60s to amortize repeated calls from
  the watchlist page-load + refresh cycle.
- `conviction_percentile` = `1.0 − (rank_position − 1) / universe_size`
  where `rank_position` is by `conviction_score` desc.
- `distinctiveness_tier` derivation (V1 heuristic, refinable):
  - `distinctive`: `manager_signal_quality_coverage ≥ 0.7` AND
    `consensus_count ≤ 8`.
  - `crowded`: `consensus_count ≥ 20` AND
    `manager_signal_quality_coverage < 0.5`.
  - `mixed`: everything else.
- `caveat_severity` aggregation: any `_HIGH_CAVEATS` member
  present → `high-caution`; any `_MEDIUM_CAVEATS` → `caution`;
  empty → `ok`.

### What does NOT change

- `GET /oracles-lens` (existing dashboard endpoint) — unchanged.
- `GET /stocks/{ticker}/institutions` — unchanged; superseded
  by the drawer (MVP7-05).
- `oracles_lens_signals` table — no migration. The dashboard
  computes everything on read; persistence is a future-Pre-MVP7
  optimization if read latency is unacceptable.

## Frontend Architecture

### Reuse from existing layers

- `frontend/lib/oraclesLens.js` — `cautionTone` (D3 caveat chip
  variant), `humanizeTier` (caveat-code labels), `formatPercent`
  (conviction percentile display).
- React Query for the watchlist 13F snapshot fetch — batch one
  `useQuery` keyed on the watchlist row stock_ids list.
- `@/components/ui/table` — existing Table primitive; extend with
  `<colgroup>` + 2-row header for the 13F group label.

### New frontend module

`frontend/lib/watchlist13f.ts` — pure helpers (no React):

- `formatConvictionTier(percentile: number): string` →
  `"Top 15%"` / `"Mid 50%"` / `"Bot 25%"`.
- `formatDeltaHolders(delta: number): string` → signed integer.
- `distinctivenessTone(tier): BadgeVariant`.
- `caveatSeverityTone(severity): BadgeVariant`.
- `mosCrossSignal({mos, deltaHolders}): "aligned" | "exit-divergence" | "buy-divergence" | "neutral"`.

### New frontend component

`frontend/components/watchlist/Watchlist13FColumns.tsx` — receives
the snapshot for one row + renders the four `<TableCell>`s. Easier
than scattering the rendering logic across the page.

## MVP7-01..N Task Sequence

Each row is one ticket. Each follows the standard pattern: task
spec → tests → Docker verification → commit with
`Co-Authored-By: Claude Opus 4.7` footer.

| # | Title | Scope summary | Deps |
|---|-------|---------------|------|
| **MVP7-01** | Backend `/stocks/13f-snapshots` batch endpoint | New router endpoint; reuses `build_oracles_lens_dashboard`; in-memory 60s cache; pytest coverage for `available=true/false` branches + percentile math + caveat severity aggregation. | — |
| **MVP7-02** | Watchlist row data plumbing | Extend `_watchlist_rows_for_memberships` (or sibling fetch) to call the new endpoint with the row stock_ids; thread snapshot fields onto `WatchlistRow`. Wire `useQuery` on the frontend. | MVP7-01 |
| **MVP7-03** | Four 13F columns + group header | Frontend Table extended with 2-row header (`<colgroup>`); 4 new `<TableCell>` columns powered by `Watchlist13FColumns` component. Sort behavior on each column. `frontend/lib/watchlist13f.ts` helper module. | MVP7-02 |
| **MVP7-04** | Responsive collapse + MOS cross-signal glyph | D4 responsive strategy (lg inline / md collapse / sm hidden). D5 MOS glyph wired into existing MOS cell render. localStorage persistence for collapse state. | MVP7-03 |
| **MVP7-05** | Per-row 13F drawer | Click row (or 13F group header on a specific row) opens a `DrawerShell`-style detail panel with top 3 holders cards, per-manager position change magnitudes, caveat code breakdown. Reuse `frontend/lib/oraclesLens.js` normalizers. | MVP7-03 |
| **MVP7-06** | E2E verification | Closing gate. Four-role review (Staff Engineer / SME / PO / Frontend-UX). Verification doc + review prompts following the MVP6-08 pattern. | MVP7-01..05 |

Parallelism: MVP7-04 and MVP7-05 are mutually independent after
MVP7-03 lands. MVP7-02 is the only sequential blocker.

## Scope Out

- **No watchlist V1 PRD revisions.** The existing
  `docs/prd/watchlist/watchlist-v1.md` Sidebar / Add Ticker /
  Fair Value semantics stay.
- **No alerts / notifications** (PRD §11 Future Roadmap).
  Watchlist V1.1 territory.
- **No backend schema migrations.** Dashboard computes on read;
  persistence optimization deferred until / unless read latency
  observed > 500ms on the watchlist page-load.
- **No `oracles_lens_signals` rank-position column.** Universe
  rank is computed per request inside the snapshot endpoint.
- **No MVP6-08 follow-up FLAGs landed here.** The four MVP6 SME
  FLAGs (manager_type editor evidence threshold, Kahn TP signal,
  Batch Reparse skip banner, Quality Reports drilldown) stay
  queued for separate MVP7-track tickets.
- **No mobile (< 768px) per-row stacked view.** D4 defers
  mobile-only V1. The 13F group is hidden on sm viewports.

## PRD / Decision References

- `docs/prd/watchlist/watchlist-v1.md` — existing user-facing
  watchlist PRD.
- `docs/prd/13f_automation_and_resilience_prd.md` §7 (Oracle's
  Lens scoring vocabulary), §11 (admin readiness surface that
  feeds caveat computation).
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7
  (V1 score surface — same scoring formulas the watchlist
  snapshot endpoint will reuse), §17 (V1.1 / V2 deferred
  additions).
- `docs/tasks/2026-05-12_13f-mvp6-end-to-end-verification.md`
  "Post-MVP6 Decision Inputs" — Track D Watchlist V1 selected
  as MVP7 first ticket.
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` Track D — original
  framing of the Watchlist + Value Line + F-Score formalization
  cluster.
- `backend/app/services/oracles_lens/dashboard.py` `_stock_payload`
  — existing per-stock field set the snapshot endpoint reuses.

## Verification Pattern

- Per-ticket Docker verification (`pytest -q` baseline + frontend
  `lint` + `build` + `node --test lib/oraclesLens.test.js`).
- Manual probe of the watchlist 13F columns with the dev seeder
  running (Pre-MVP6-01 produced 8 stocks; some will have
  qualifying 13F snapshots, some will hit `unavailable: true`
  paths — both branches must render correctly).
- For MVP7-04 / MVP7-05: at least one browser-interaction
  check on each viewport tier (lg / md / sm) confirming the
  responsive strategy works.
- MVP7-06 follows the MVP6-08 four-role review pattern.

## Sign-Off Trail

- [x] PO authorized MVP7 kickoff with Track D Watchlist V1
      (2026-05-13).
- [x] PO selected the per-stock 13F insight product framing
      (2026-05-13).
- [x] PO locked the four V1 columns (Conviction / Δ Holders /
      Distinctiveness / Caveats) (2026-05-13).
- [x] PO accepted the four design refinements (quarter label
      format / empty state / responsive strategy / MOS visual
      cross-signal) (2026-05-13).
- [x] Pre-MVP7-01 decision gate ready for MVP7-01..06
      execution.

## Verification Results

- 2026-05-13: D1–D5 filled in by engineer. **Pre-MVP7-01 ready
  for MVP7-01 task spec.** No code changes yet.
