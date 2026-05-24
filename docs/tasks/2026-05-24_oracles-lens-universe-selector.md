# 2026-05-24 — Oracle's Lens universe selector (style/capital/market-cap filters)

## Goal

Let value investors filter Oracle's Lens to a manager universe that
matches their lens — "Deep Value Consensus", "Activists",
"Permanent Capital", "Small-cap Sleuths" — and have the Signal /
Conviction / Distinctive scores **all recompute over that subset**,
not just be display-filtered post hoc.

This is the natural next step after manager-taxonomy-v2 (PR #94): we
now have `style_primary` / `capital_structure` / `market_cap_focus`
on every manager; the only piece missing is letting consumers actually
**use** that classification to slice the consensus signal.

## PO-confirmed design decisions

| Decision | Choice |
|---|---|
| Math model | **Filter (strict subset)** — only the picked managers count; scores recompute |
| Default universe | **Value-only** (Deep Value preset) — value-only is the default; "All" is opt-in |
| UX shape | **Preset chips + Custom dialog** — 6 chips for the common cuts, dialog for power users |
| "Deep Value Consensus" composition | **value_deep + value_concentrated + quality_compounder** (~50/82 managers) |

## Acceptance criteria

### Backend

1. **`GET /v1/13f/oracles-lens` accepts three new optional query params**:
   - `style_primary` — comma-separated subset of the canonical
     `STYLE_PRIMARY` vocabulary (e.g. `value_deep,value_concentrated,quality_compounder`)
   - `capital_structure` — comma-separated subset of `CAPITAL_STRUCTURE`
   - `market_cap_focus` — comma-separated subset of `MARKET_CAP_FOCUS`
   - Empty/missing means "no constraint on that dimension"
   - Unknown values raise HTTP 400 (don't silently fall through)
2. **Signal / Conviction / Distinctive scores recompute over the
   filtered subset** when ANY of the three params is non-empty.
   `compute_conviction_components(contributions)` and
   `compute_distinctive_consensus(signal_weighted_score, contributions)`
   are pure functions of the contribution list, so threading the
   allowlist through `_contributions_for_stock()` is sufficient —
   conviction/distinctive get correct values "for free".
3. **`_eligible_stock_ids()` also respects the allowlist** — a stock
   that has 5 holders globally but only 1 in the filtered universe
   must not pass `min_holders=3` for that universe.
4. **`_top_n_stock_ids_per_manager()` does NOT take the allowlist** —
   "is stock X in manager M's top-10" is universe-agnostic.
5. **Empty filter = persisted mode (fast path preserved)**: when all
   three params are empty, fall through to the existing
   `_apply_persisted_scores()` reader. No regression for the "All"
   universe.
6. **Any non-empty filter = live-recompute path**: the persisted
   `oracles_lens_signals` row reflects the all-managers universe and
   is incorrect for the filtered case; we recompute on-the-fly,
   we do NOT write back to `oracles_lens_signals`. Backfill remains
   the all-managers source of truth.
7. **Response carries universe metadata** so the FE can render the
   "X of 82 managers" subtitle without an extra round-trip:
   ```json
   "universe": {
     "filtered_manager_count": 50,
     "total_manager_count": 82,
     "applied_filters": {
       "style_primary": ["value_deep", "value_concentrated", "quality_compounder"],
       "capital_structure": [],
       "market_cap_focus": []
     }
   }
   ```
8. **Manager-resolver lives in a dedicated helper**
   (`backend/app/services/oracles_lens/manager_universe.py`) so the
   resolution logic is unit-testable in isolation.

### Frontend

9. **Chip row above the existing Filters card** on
   `/13f/oracles-lens`:
   ```
   [Deep Value]  [Activists]  [Small-cap Sleuths]  [Permanent Capital]  [All]  [Custom…]
   ```
   Each chip maps to a URL-query-param set; selected chip is visually
   distinguished.
10. **Default behavior on first load**: if no `style_primary` /
    `capital_structure` / `market_cap_focus` params are present, the
    page **redirects** (via `router.replace`) to the Deep Value preset.
    This makes the value-only default both visible (chips show
    Deep Value selected) and bookmarkable (a bookmark of the bare URL
    always lands on value-only).
11. **"Custom…" dialog**: 8 checkboxes for `style_primary`; live
    "X of 82 managers selected" footer; "Apply" writes the URL params.
    `capital_structure` / `market_cap_focus` deferred from V1 dialog
    (presets cover those; advanced editing is YAGNI for now).
12. **Subtitle near chip row** shows
    "**N of M managers**" reading from `payload.universe`.

### Tests (test-first)

13. New `backend/tests/unit/test_13f_oracles_lens_universe_filter.py`:
    - resolver: `style_primary=value_deep` → expected manager_id set
    - resolver: rejects unknown style values with ValueError
    - `_contributions_for_stock(..., manager_id_allowlist={...})`
      filters as expected
    - `_eligible_stock_ids(..., manager_id_allowlist={...})` filters
      as expected
    - **Hero test**: with Deep Value preset, Tiger Global's holdings
      are NOT in the contributions list (was the V1 problem)
    - **Conviction/distinctive correctness**: filtered contributions
      → conviction/distinctive recompute to match (not the persisted
      all-managers value)
    - Endpoint: 400 on unknown style value
    - Endpoint: empty filters → persisted-mode path used
    - Endpoint: any non-empty filter → live-recompute path
14. New `frontend/components/oraclesLens/UniverseSelector.test.js`:
    - preset key → URL params map is correct
    - Custom dialog applies selected styles
    - URL query parse round-trip
15. CI canonical commands green.

### Out-of-scope (deferred to BACKLOG if applicable)

- Persisted preset scores (cache `oracles_lens_signals` with a
  `universe_key` column). V1 ships live-recompute; if latency becomes
  noticeable in production, that's the optimization.
- Watchlist 13F columns following the universe selector. Watchlist
  stays "All managers" for now — universe filtering is an Oracle's
  Lens browse-time concept, not a per-position thesis concept.
- `capital_structure` / `market_cap_focus` in the Custom dialog UI.
  Preset chips cover both today.
- MVP8-01 Phase 4 deletion of `use_persisted_scores` flag — the
  live-compute code path is now load-bearing for the filter case, so
  Phase 4 should delete only the flag (the deprecated
  `dashboard.py:_stock_payload()` in-memory path can still go), not
  the entire live-compute capability.

## Critical invariants — preserved

- `oracles_lens_signals` schema unchanged. No migration in this PR.
- `MANAGER_SIGNAL_WEIGHTS` unchanged. `SCORE_VERSION` unchanged.
- `_top_n_stock_ids_per_manager()` and downstream pure functions
  (`compute_conviction_components`, `compute_distinctive_consensus`,
  `compute_portfolio_weight`, `compute_holding_streak`,
  `compute_add_intensity`) are untouched.
- All existing backfill paths
  (`compute_signal_weighted_scores`, `execute_signal_weighted_backfill`)
  call the helpers with `manager_id_allowlist=None`, preserving today's
  behavior bit-for-bit.

## Files to change

| File | Change |
|---|---|
| `backend/app/services/oracles_lens/manager_universe.py` | NEW — resolver `resolve_manager_id_allowlist(session, *, style_primary, capital_structure, market_cap_focus) -> set[int] \| None` |
| `backend/app/services/oracles_lens/signal_weighted_score.py` | `_eligible_stock_ids` + `_contributions_for_stock` accept optional `manager_id_allowlist`. New `compute_oracles_lens_filtered(session, period, allowlist)` returning the live-recomputed items. |
| `backend/app/services/oracles_lens/dashboard.py` | Branch on allowlist: empty → existing persisted path; non-empty → new live-recompute path. Attach `universe` metadata to response. |
| `backend/app/api/v1/endpoints/oracles_lens.py` | Three new Query params; parse comma-separated; validate against `STYLE_PRIMARY` / `CAPITAL_STRUCTURE` / `MARKET_CAP_FOCUS`; pass to dashboard service. |
| `backend/tests/unit/test_13f_oracles_lens_universe_filter.py` | NEW test file (see AC #13) |
| `frontend/lib/oraclesLens.js` | Build new params into the query; parse `universe` from response. |
| `frontend/components/oraclesLens/UniverseSelector.tsx` | NEW — chip row + Custom dialog |
| `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` | Mount selector; redirect on bare URL; render "X of 82 managers" subtitle |
| `frontend/components/oraclesLens/UniverseSelector.test.js` | NEW — preset map + URL round-trip tests |

## Decisions / gotchas

- **Live-recompute is the default user experience.** Every visit to
  `/13f/oracles-lens` with the Value-only preset (the new default)
  triggers a live compute pass. Expected latency: ~300-500ms for
  ~50 stocks × ~50 filtered managers, all index-driven. If real-world
  data points higher, the optimization path is a `universe_key` column
  on `oracles_lens_signals` plus a multi-universe backfill, deferred to
  a separate PR.
- **`compute_conviction_components` / `compute_distinctive_consensus`
  are pure functions of `contributions`** — confirmed via code read.
  This makes the conviction/distinctive "filter follow-through"
  automatic; no separate threading required. Hero realization of this
  task — without it, the filter would have leaked Tiger-Global-style
  bias into Conviction Score even after we filtered the manager list.
- **`Decimal` arithmetic is preserved.** Weights, position scores,
  conviction, and distinctive all use `Decimal`. The new helpers must
  not introduce `float` round-trips.
- **MVP8-01 Phase 4 risk noted in Scope (Out)** — Phase 4 was planning
  to delete the `use_persisted_scores` flag entirely. We are now
  load-bearing on the live-compute path for filter mode. Phase 4
  needs to be re-scoped to "delete the flag and the deprecated
  in-memory dashboard formula, but keep `compute_oracles_lens_filtered`
  alive."

## Test plan

```
docker compose up -d --build
docker compose exec -T api alembic upgrade head     # no new migrations
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
docker compose restart web                          # per memory: prod build clobbers dev
```

Targeted iteration:
```
docker compose exec -T api pytest -q tests/unit/test_13f_oracles_lens_universe_filter.py
docker compose exec -T web sh -lc 'node --test lib/oraclesLens.test.js'
```

End-to-end smoke (browser):
- Visit `/13f/oracles-lens` → URL replaces to include Deep Value params
- Chip row shows Deep Value selected, subtitle "50 of 82 managers"
- Click "All" chip → URL params clear, score returns to V1 numbers
- Click "Custom…" → dialog opens, pick `activist`, Apply → URL
  updates to `?style_primary=activist`, candidates list re-ranks
