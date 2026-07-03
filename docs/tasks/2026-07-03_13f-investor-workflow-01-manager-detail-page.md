# Task: 13F investor workflow 01 — investor-facing manager list + quarterly report page

**Created:** 2026-07-03 · **Origin:** PO review `2026-07-03_13f-po-review-value-investor.md` (§3 gap #1 — the single biggest investor-facing gap)
**Status:** DRAFT (next-iteration package; blocked on `pre-mvp6-01-13f-dev-data-bootstrap` for PO acceptance only, not for development)

## Goal / Acceptance Criteria

The #1 mental entry point for 13F is the *manager* ("what did Buffett do this quarter?"). All consumer APIs exist; only the investor-facing UI is missing (managers are currently admin-only).

- **`/13f/managers` (new page):** list of active managers — display name, style_primary badge, manager_type, is_featured flag, latest reported quarter + filing status. Featured first; filter by style_primary. Data: existing `GET /13f/managers`.
- **`/13f/managers/[id]` (new page):** the classic quarterly report —
  - Header: manager name, style badge, classification rationale, CIK, latest quarter selector (data: `GET /13f/managers/{id}/quarters`).
  - **Quarter-over-quarter moves table**: new / increased / reduced / exited, sorted by |portfolio-weight change|, with value & share deltas, confidence level, and caveat badges (data: `GET /13f/managers/{id}/holdings/changes`).
  - **Current holdings table**: rank, ticker (linked to `/stocks/[ticker]/summary` when stock-linked), value, portfolio weight, holding streak, put/call flag (data: `GET /13f/managers/{id}/holdings`; common vs options sections kept separate as the API returns them).
  - All existing caveats (NT quarter, combination, confidential, amendment-pending, filing-window-open) rendered as badges — **never silently dropped**.
- **Cross-linking (closes the navigation triangle):**
  - Sidebar nav gains "Managers" under the 13F group.
  - Oracle's Lens drilldown "Top direct holders" cards → link to the manager page.
  - Watchlist 13F drawer top-holder cards → link to the manager page.
  - `/stocks/[ticker]/summary` gains a "13F holders" card (top holders + link; data: existing `GET /13f/stocks/{stock_id}/holders`).
- Loading / empty / error states per existing patterns; responsive per watchlist conventions.

## Scope

**In:** frontend pages/components + nav; no schema changes; no new backend endpoints expected (if a field is missing from an existing consumer endpoint, extend that endpoint additively).
**Out:** follow-manager affordance (BACKLOG); export; QoQ charts; any admin-surface change.

## Files to change (indicative)

- `frontend/app/(dashboard)/13f/managers/page.tsx` [NEW]
- `frontend/app/(dashboard)/13f/managers/[id]/page.tsx` [NEW]
- `frontend/components/13f/` manager cards/tables [NEW, shadcn/ui per uiStandard]
- `frontend/components/layout/AppShell.tsx` (nav entry)
- Oracle's Lens drilldown + `Watchlist13FDrawer.tsx` + stock summary page (links)

## Test plan (Docker)

```bash
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'node --test lib/*.test.js'   # uiStandard scanner covers new components
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
# closing gate: full canonical CI per AGENTS.md
```

PO acceptance (needs seeded dev data): open Managers → pick a featured manager → read the quarter's moves sorted by weight change → click through to a stock and back.
