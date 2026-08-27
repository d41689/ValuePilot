# Task: 13F investor workflow 01 — investor-facing manager list + quarterly report page

**Created:** 2026-07-03 · **Origin:** PO review `2026-07-03_13f-po-review-value-investor.md` (§3 gap #1 — the single biggest investor-facing gap)
**Status:** COMPLETE (2026-07-18)

## Goal / Acceptance Criteria

The #1 mental entry point for 13F is the *manager* ("what did Buffett do this quarter?"). All consumer APIs exist; only the investor-facing UI is missing (managers are currently admin-only).

- **`/13f/managers` (new page):** list of active managers — display name, style_primary badge, manager_type, turnover, capital structure, latest reported quarter + filing status. The default scope is genuine value-oriented managers (`value_deep`, `value_concentrated`, `quality_compounder`); activists and the full tracked universe remain explicit alternatives. Quant, index-like, growth/long-short and macro noise must never leak into the default list. Data: additive fields on existing `GET /13f/managers`.
- **`/13f/managers/[id]` (new page):** the classic quarterly report —
  - Header: manager name, style badge, curated classification rationale, turnover/capital-structure context, CIK, latest quarter selector (data: `GET /13f/managers/{id}/quarters`).
  - **Quarter-over-quarter moves table**: new / increased / reduced / exited, sorted by |portfolio-weight change|, with value & share deltas, confidence level, and caveat badges (data: `GET /13f/managers/{id}/holdings/changes`).
  - **Current holdings table**: rank, ticker (linked to `/stocks/[ticker]/summary` when stock-linked), value, **weight in the manager's reported 13F common-stock portfolio**, holding streak, put/call flag (data: `GET /13f/managers/{id}/holdings`; common vs options sections kept separate as the API returns them). Multiple raw rows/CUSIPs for one linked economic position are aggregated for display while the raw holdings remain untouched as the audit trail.
  - All existing caveats (NT quarter, combination, confidential, amendment-pending, filing-window-open) rendered as badges — **never silently dropped**.
- **Cross-linking (closes the navigation triangle):**
  - Sidebar nav gains "Managers" under the 13F group.
  - Oracle's Lens drilldown "Top direct holders" cards → link to the manager page.
  - Watchlist 13F drawer top-holder cards → link to the manager page.
  - `/stocks/[ticker]/summary` gains a "13F holders" card (top holders + link; data: existing `GET /13f/stocks/{stock_id}/holders`).
- Loading / empty / error states per existing patterns; responsive per watchlist conventions.

## Scope

**In:** frontend pages/components + nav; additive consumer-API fields and read-time position aggregation where the existing endpoint lacks investor-facing semantics; no schema changes.
**Out:** follow-manager affordance (BACKLOG); export; QoQ charts; any admin-surface change.

## Files to change (indicative)

- `frontend/app/(dashboard)/13f/managers/page.tsx` [NEW]
- `frontend/app/(dashboard)/13f/managers/[id]/page.tsx` [NEW]
- `frontend/components/13f/` manager cards/tables [NEW, shadcn/ui per uiStandard]
- `frontend/components/layout/AppShell.tsx` (nav entry)
- Oracle's Lens drilldown + `Watchlist13FDrawer.tsx` + stock summary page (links)
- `backend/app/services/thirteenf_user_api.py` (taxonomy/profile metadata, latest filing summary, position-level holdings/weights)
- `backend/tests/unit/test_13f_user_api.py` (consumer contract)

## Test plan (Docker)

```bash
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'node --test lib/*.test.js'   # uiStandard scanner covers new components
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
# closing gate: full canonical CI per AGENTS.md
```

PO acceptance (needs seeded dev data): open Managers → pick a Value DNA manager → read the quarter's moves sorted by weight change → click through to a stock and back.

## 2026-07-18 implementation decisions / gotchas

- The live empty-database rehearsal seeded 82 classified managers but **zero `is_featured=true` rows**. `is_featured` therefore cannot define the primary investor experience. The default product scope is the V2 value-DNA styles; the UI still exposes activists and all tracked managers deliberately.
- `holdings_13f.portfolio_weight_pct` is intentionally NULL in the original MVP-1 parser contract. The investor API must calculate the position weight from normalized `value_usd` over the complete filing's common-stock denominator; it must return unavailable for partial/notice coverage, never silently show 0%.
- A filing can contain multiple raw rows that map to the same stock. The user-facing table is a position view (summed value/shares, constituent-row count and CUSIPs retained); raw rows and parse provenance remain unchanged.
- The curated one-line `classification_rationale` currently lives in `confirmed_managers.json`, not a database column. Consumer responses may read that canonical seed metadata by CIK and return `null` for managers outside the curated seed. No synthetic rationale should be invented.
- Every 13F page must keep the fixed limitation copy: quarter-end snapshot, up to 45-day delay, long-only reportable US securities, no transaction price/cost basis, and options are not directional proof.
- Synthetic visual-acceptance managers now carry V2 style, structure, turnover, concentration and ideology metadata while preserving all eight legacy score-weight branches. The default seeded page renders 8 value managers out of 32 rather than an empty list.
- Read-time display deltas treat a new position as `+current` and an exit as `-previous` for value and shares. The immutable/materialized ownership-change row is not rewritten.

## 2026-07-18 verification trail

- Targeted backend consumer/taxonomy suite: green.
- Frontend helper tests, uiStandard scanner, lint and production build: green.
- Isolated, seeded browser acceptance: Managers showed `8 / 32` default Value DNA managers; manager detail rendered computed 13F common weights, new positions and holding streaks; cross-links opened stock research and Oracle's Lens.
- Canonical closing gate: backend `1291 passed`; frontend `193 passed`; lint and production build green.
