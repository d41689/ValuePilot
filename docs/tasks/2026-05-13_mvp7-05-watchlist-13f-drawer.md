# MVP7-05: Per-Row 13F Drawer on /watchlist

## Status

**Authorized to start (PO 2026-05-13 after MVP7-04 ship).** Fifth
ticket on the MVP7 Watchlist × 13F Insight track.

## Goal / Acceptance Criteria

Add a per-row drawer on `/watchlist` that surfaces the detail-level
13F context for one stock: top 3 holders with per-manager position
change magnitudes, the full caveat flag breakdown, and a header
recap of the four column signals. Replaces the column-level
chips' tooltip with a structured panel for operators who want to
inspect *why* the column says what it says.

Acceptance criteria:

- **New backend endpoint** `GET /api/v1/stocks/{stock_id}/13f-detail`:
  - Query param `period: "latest" | "YYYY-Qn"` (optional; defaults
    to `"latest"`).
  - Returns one stock's `_stock_payload` projected to a
    detail-shaped response with `top_holders[]` (up to 3 by
    `position_weight` desc), full `caveat_flags[]`, plus the same
    column-summary fields as the MVP7-01 batch endpoint
    (conviction_score, conviction_percentile, delta_holders,
    distinctiveness_tier, caveat_severity, consensus_count,
    score_confidence) for header consistency.
  - **404** if the `stock_id` doesn't exist in `stocks`.
  - **200 with `available: false`** when the stock exists but
    has no qualifying 13F coverage in the period (matches
    MVP7-01 unavailable taxonomy: `no_holders`,
    `below_min_holders`, `no_qualifying_period`).
- **New frontend query hook** `useWatchlistStock13FDetail(stockId,
  period)` in `frontend/lib/watchlist13f.ts`:
  - `enabled: stockId !== null`.
  - 60s `staleTime`.
  - Returns the detail payload type.
- **New drawer component**
  `frontend/components/watchlist/Watchlist13FDrawer.tsx`:
  - Mounts `DrawerShell` from `@/components/admin13f/Admin13FPrimitives`
    (the existing shell, not duplicated).
  - Header recap row: the same four column chips
    (`Watchlist13FColumns` rendering reused via composition or a
    summary helper).
  - **Top Holders section**: 3 cards. Per card:
    - manager_name (link to `/admin/13f/managers/{id}` for admin
      drill-through).
    - manager_type badge (using `titleizeCode` from
      `frontend/lib/oraclesLens.js`).
    - position_weight chip ("X% of portfolio").
    - action chip (action-specific label + tone via
      MVP7-05 helpers).
    - share_delta_pct (only when action is `add` or `reduce` —
      shows the magnitude as a signed percent).
    - holding_streak_quarters ("Held N quarters").
    - filing date + accession_no, links to the EDGAR filing.
  - **Caveats section**: structured list of caveat flag cards.
    Per card: severity icon (warning vs info via existing
    `cautionTone` from `frontend/lib/oraclesLens.js`), label
    text (`flag.label`), group badge (`flag.group`).
    Renders "No caveats" placeholder when empty.
- **Trigger**: each Conviction badge in the watchlist row's 13F
  cells becomes a `<button>` when `snapshot.available === true`,
  with `onClick={() => openDrawer(stockId)}`. Cursor is
  `pointer`; the Badge style is unchanged.
- **State**: `selectedStockIdForDrawer` in `/watchlist/page.tsx`.
  Drawer closes via the existing DrawerShell close button or by
  clicking the backdrop.

## Plumbing Decision (locked here)

Pre-MVP7-01 SR4 already locked this: **separate per-stock detail
fetch**, not an extension of MVP7-01's batch endpoint. Rationale
preserved:

- The batch endpoint stays focused on column-summary fields. Top
  holders are heavyweight (≥ 18 fields × up to 3 holders × N
  rows) and slow to compute for every batch call.
- Drawer fetch is lazy — only when the user opens it. No upfront
  cost for the common case.
- Clean cache invalidation: `['watchlist-13f-stock-detail',
  stock_id, period]` is per-stock, doesn't fragment the batch
  cache.

## Scope In

- `backend/app/api/v1/endpoints/stocks_13f.py` — add the new
  detail endpoint alongside the existing batch endpoint.
- `backend/app/schemas/stocks_13f_snapshot.py` — add detail
  schemas (`StockDetailRequest` doesn't exist — path param +
  query; response models `AvailableStockDetail` /
  `UnavailableStockDetail` / `StockDetailResponse`).
- `backend/tests/unit/test_mvp7_05_stock_13f_detail.py` (new).
- `frontend/lib/watchlist13f.ts` — add detail-shape types +
  `useWatchlistStock13FDetail` hook + small helpers
  (`topHolderActionLabel`, `topHolderActionTone`,
  `caveatGroupLabel`).
- `frontend/components/watchlist/Watchlist13FDrawer.tsx` (new).
- `frontend/components/watchlist/Watchlist13FColumns.tsx` —
  accept an optional `onOpenDetail(stockId)` callback; render
  the Conviction badge inside a button when available.
- `frontend/app/(dashboard)/watchlist/page.tsx` — mount the
  drawer; wire `selectedStockIdForDrawer` state; pass
  `onOpenDetail` into `Watchlist13FColumns`.
- This task file.

## Scope Out / Scope Refinements

- **SR0**: Single trigger location — the Conviction badge — per
  Pre-MVP7-01 D-section. Other three badges remain non-clickable
  to keep the hover-tooltip UX undisturbed. Future tickets can
  expand to a row-level click or a dedicated "Detail" button.
- **SR1**: No per-stock detail prefetching on hover. Fetch only
  on open click.
- **SR2**: Top-holders count fixed at 3 per Pre-MVP7-01 (the
  dashboard's existing `top_holders[:3]` slice).
- **SR3**: No backend service-level caching on the detail
  endpoint. The dashboard run is the expensive part; one detail
  call per drawer open is acceptable for V1 watchlist sizes.
- **SR4**: No frontend unit tests for the new drawer (component
  composition only; lint + build + manual probe is the
  verification bar — matches MVP7-03 / MVP7-04 pattern).
- **SR5**: No keyboard shortcut for opening drawer (Conviction
  badge is keyboard-focusable + Enter-activatable via HTML
  `<button>` semantics).
- **SR6**: `use_persisted_scores=False` still gated per the
  MVP5-03 Phase 3 rule.
- **SR7**: Drawer reuses `@/components/admin13f/Admin13FPrimitives`
  `DrawerShell` despite the admin-prefixed path. The component is
  domain-agnostic; renaming / moving it is out of scope.

## PRD / Decision References

- `docs/tasks/2026-05-13_pre-mvp7-01-watchlist-13f-insight-decision-gate.md`
  D-section "Per-row 13F drawer" + SR4 "separate per-stock detail
  fetch".
- `docs/tasks/2026-05-13_mvp7-01-stocks-13f-snapshots-endpoint.md` —
  endpoint that the detail endpoint composes with.
- `backend/app/services/oracles_lens/dashboard.py` — `_stock_payload.top_holders[:3]`
  field set the detail endpoint projects.
- `frontend/lib/oraclesLens.js` — `titleizeCode`, `cautionTone`,
  `formatPercent` reused in the drawer.

## Files Expected To Change

- `backend/app/api/v1/endpoints/stocks_13f.py`
- `backend/app/schemas/stocks_13f_snapshot.py`
- `backend/tests/unit/test_mvp7_05_stock_13f_detail.py` (new)
- `frontend/lib/watchlist13f.ts`
- `frontend/components/watchlist/Watchlist13FDrawer.tsx` (new)
- `frontend/components/watchlist/Watchlist13FColumns.tsx`
- `frontend/app/(dashboard)/watchlist/page.tsx`
- This task file.

## Verification

- `docker compose exec api pytest -q tests/unit/test_mvp7_05_stock_13f_detail.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- Manual probe:
  1. Open `/watchlist`. Add a ticker with seeded 13F coverage.
  2. Click the Conviction badge on that row.
  3. Drawer slides in with the recap header + Top Holders cards
     + Caveats list.
  4. Close via the X button; confirm focus returns.
  5. Click Conviction on a stock with no 13F snapshot —
     should be non-clickable (button only renders when
     `available === true`).

## Progress Notes

- 2026-05-13: Task spec filed.
- 2026-05-13: Implementation:
  - **Backend endpoint** `GET /api/v1/stocks/{stock_id}/13f-detail`
    added to `backend/app/api/v1/endpoints/stocks_13f.py`. 404
    when stock_id doesn't exist (resolved via `_stock_meta`).
    200 + `available: false` + reason code when stock exists but
    has no qualifying coverage. 200 + full detail payload when
    ranked. Reuses `build_oracles_lens_dashboard(limit=0,
    use_persisted_scores=False)` exactly as MVP7-01 — no new
    scoring logic.
  - **Schemas** at `backend/app/schemas/stocks_13f_snapshot.py`:
    `StockDetailTopHolder` (18 fields projecting
    `_stock_payload.top_holders[:3]`), `StockDetailCaveatFlag`
    (key/group/severity/label), `AvailableStockDetail` /
    `UnavailableStockDetail` discriminated union with the same
    `unavailable_reason` literals as the batch endpoint.
  - **pytest** at `backend/tests/unit/test_mvp7_05_stock_13f_detail.py`
    — 6 tests covering available payload shape + top_holders +
    caveat_flags structure, 404 for unknown stock, the three
    unavailable branches, and that `top_holders.action` uses the
    dashboard vocabulary (`new`/`add`/`reduce`/`exit`/`flat`).
  - **Frontend hook** `useWatchlistStock13FDetail(stockId, period)`
    in `frontend/lib/watchlist13f.ts`. Query key
    `['watchlist-13f-stock-detail', stockId, period ?? 'latest']`.
    60s `staleTime`. Disabled when `stockId === null`.
  - **Frontend helpers** added: `topHolderActionLabel` /
    `topHolderActionTone` (5-branch action vocabulary mapper);
    `caveatGroupLabel` for the four caveat groups. TS types
    (`Watchlist13FAvailableDetail` / `Watchlist13FUnavailableDetail`
    / `Watchlist13FTopHolder` / `Watchlist13FCaveatFlag` /
    `Watchlist13FDetailPayload`) mirror the backend schemas.
  - **New component** `frontend/components/watchlist/Watchlist13FDrawer.tsx`
    mounts `DrawerShell` (reused from
    `@/components/admin13f/Admin13FPrimitives` per SR7). Three
    sections: header recap chips, Top Holders cards (link to
    `/admin/13f/managers/{id}` + manager_type badge +
    position_weight + action chip + share_delta_pct magnitude
    where applicable + holding_streak + accession_no), Caveats
    cards (severity icon + label + group badge). Loading /
    error / unavailable / available states all handled.
  - **`Watchlist13FColumns`** extended with two new props:
    `stockId` (per-row identifier) + `onOpenDetail` (callback).
    When `onOpenDetail` is provided AND `snapshot.available === true`,
    the Conviction badge renders inside a bare `<button>` with
    `cursor-pointer` and `aria-label`. Title tooltip suffix
    "(click for detail)" hints the click affordance.
  - **`/watchlist/page.tsx`** wires `drawerStockId` state + drawer
    mount below the table. Passes `stockId` + `onOpenDetail` into
    `Watchlist13FColumns`.
  - **Scope refinements** (recorded in spec):
    - SR0: single trigger (Conviction badge); other 3 chips stay
      hover-tooltip only.
    - SR1: no hover prefetch.
    - SR2: top_holders fixed at 3.
    - SR3: no service-level cache on detail endpoint.
    - SR4: no frontend unit tests for drawer.
    - SR5: no keyboard shortcut.
    - SR6: persisted-scores still gated.
    - SR7: DrawerShell reused from admin13f path despite
      domain-mismatch (cross-cutting refactor out of scope).

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_mvp7_05_stock_13f_detail.py`
  → **6 passed**.
- `docker compose exec api pytest -q` → **806 passed** (= 800
  baseline + 6 new); 0 warnings.
- `docker compose exec web npm run lint` → No ESLint warnings or
  errors.
- `docker compose exec web npm run build` → compiled successfully.
  `/watchlist` route bundle 16.8 → 20.5 kB (+3.7 kB for detail
  types + drawer component + hook); First Load JS 193 → 199 kB.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- Manual probe: open `/watchlist`, add a ticker with seeded 13F
  coverage. Click the Conviction badge on that row → drawer slides
  in with summary chips, top-holder cards, and caveat flags.
  Close via X button. Stocks without 13F coverage render the
  Conviction cell as `—` so no clickable button appears.
