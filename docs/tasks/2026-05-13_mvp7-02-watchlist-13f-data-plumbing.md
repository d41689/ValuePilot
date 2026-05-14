# MVP7-02: Watchlist 13F Snapshot Data Plumbing

## Status

**Authorized to start (PO 2026-05-13 after MVP7-01 ship).** Second
ticket on the MVP7 Watchlist × 13F Insight track.

## Goal / Acceptance Criteria

Fetch per-stock 13F snapshots for the active watchlist and make them
available to the watchlist page render. **Data plumbing only** —
column rendering + group header + sort UX all arrive in MVP7-03.

Acceptance criteria:

- **New module** `frontend/lib/watchlist13f.ts` (file location locked
  by Pre-MVP7-01 D-section "New frontend module"). MVP7-02 owns the
  *data* portion: TypeScript types + React Query hook + merge
  helper. MVP7-03 will append the *render* portion (column
  formatters + cross-signal helpers).
- **TypeScript types** mirroring the MVP7-01 response shape:
  - `Watchlist13FSnapshot` discriminated union (`available: true |
    false`).
  - `Watchlist13FSnapshotPayload` for the endpoint envelope (period
    + filing deadline + universe_size + snapshots[]).
- **Query hook** `useWatchlist13FSnapshots(stockIds: number[])`:
  - `queryKey: ['watchlist-13f-snapshots', sortedStockIds]` so the
    cache matches regardless of input ordering.
  - `enabled: stockIds.length > 0` so an empty watchlist doesn't
    fire a request.
  - POSTs to `/api/v1/stocks/13f-snapshots` with
    `{stock_ids: sortedStockIds}` (period defaults to latest).
  - 60s `staleTime` — 13F filings are quarterly EOD-style data;
    no need to refetch on every focus.
- **Merge helper** `buildSnapshotsByStockId(payload):
  Map<number, Watchlist13FSnapshot>` so the page render can do
  an O(1) lookup per row.
- **Wire-up** in `frontend/app/(dashboard)/watchlist/page.tsx`:
  - Compute `stockIds` from `sortedMembers` (already
    derived).
  - Call `useWatchlist13FSnapshots(stockIds)`.
  - Build the per-row Map via the helper.
  - **Do not render** the snapshot data yet (no new columns).
    MVP7-03 wires the render.

The MVP7-03 ticket adds the four column cells reading from the
Map. MVP7-04 adds the responsive group-header collapse + the
MOS×13F glyph. MVP7-05 adds the click-into drawer.

## Plumbing Decision (locked here)

**Frontend independent fetch** rather than extending
`_watchlist_rows_for_memberships` to inline the snapshot fields.
Pre-MVP7-01 left both paths open ("Extend `_watchlist_rows_for_memberships`
(or sibling fetch)…").

Rationale for the sibling fetch:

1. **Failure isolation.** Watchlist's core value (ticker / price /
   FV / MOS) must render even if the 13F engine has a transient
   failure. With independent fetch, a 5xx from the snapshot
   endpoint leaves the main table intact (the 13F columns show a
   loading / error skeleton instead).
2. **Independent loading state.** Pre-MVP7-01 D4 specifies
   responsive collapse of the 13F group on md / sm viewports. With
   a sibling query, the snapshot fetch can be conditionally
   skipped on sm (saving bandwidth) — impossible if the snapshot
   data is forced inline into every watchlist row.
3. **No backend coupling.** `stock_pools` endpoints stay scoped to
   pool/membership CRUD. The 13F engine reads via its own
   dedicated endpoint. Future MVP7-N tickets can iterate the
   snapshot endpoint independently.
4. **Cache key clarity.** `['watchlist-13f-snapshots', stockIds]`
   invalidates separately from `['watchlist-members', poolId]`.
   The two cache lifecycles are different (members invalidate on
   add/remove; snapshots invalidate on 13F backfill — which the
   user can't trigger from this page).

## Scope In

- `frontend/lib/watchlist13f.ts` (new) — types + query hook +
  merge helper.
- `frontend/app/(dashboard)/watchlist/page.tsx` — call the new
  hook, build the Map. No render changes.
- This task file.

## Scope Out / Scope Refinements

- **SR0**: No render of 13F columns / drawer / cross-signal glyph
  — MVP7-03 / MVP7-04 / MVP7-05.
- **SR1**: No backend changes. `_watchlist_rows_for_memberships`
  stays untouched.
- **SR2**: No mobile-viewport conditional skip in V1. The Map
  build happens unconditionally; the responsive skip is a MVP7-04
  responsibility once the responsive collapse lands.
- **SR3**: No frontend unit tests for the new module — lint +
  build is the verification bar (matches MVP6-02..05 convention).
  The query hook is a thin `useQuery` wrapper; the merge helper
  is one map-build line. The endpoint contract is already tested
  in pytest (MVP7-01).
- **SR4**: No drawer / detail prefetch. The MVP7-05 drawer will
  add a separate per-stock detail fetch (top holders, action
  magnitudes) — not the same endpoint.

## PRD / Decision References

- `docs/tasks/2026-05-13_pre-mvp7-01-watchlist-13f-insight-decision-gate.md`
  D1 (four columns) + "Frontend Architecture" section.
- `docs/tasks/2026-05-13_mvp7-01-stocks-13f-snapshots-endpoint.md` —
  the endpoint this hook consumes.

## Files Expected To Change

- `frontend/lib/watchlist13f.ts` (new)
- `frontend/app/(dashboard)/watchlist/page.tsx`
- This task file.

## Verification

- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec api pytest -q` (sanity; no backend changes)
- Manual probe:
  1. Open `/watchlist` (logged in).
  2. DevTools Network tab: confirm one `POST
     /api/v1/stocks/13f-snapshots` fires alongside the
     `GET /stock_pools/.../members` request.
  3. Confirm the payload contains `stock_ids` matching the
     visible watchlist row stock_ids.
  4. Switch watchlists; confirm the snapshot fetch re-runs
     when stock_ids change.

## Progress Notes

- 2026-05-13: Task spec filed.
- 2026-05-13: Implementation:
  - **New module** `frontend/lib/watchlist13f.ts` with the data
    portion only: `Watchlist13FAvailableSnapshot` /
    `Watchlist13FUnavailableSnapshot` discriminated-union types
    mirroring the MVP7-01 response shape; the
    `Watchlist13FSnapshotPayload` envelope type;
    `useWatchlist13FSnapshots(stockIds)` React Query hook;
    `buildSnapshotsByStockId(payload)` O(1) lookup-map helper.
    MVP7-03 will append render helpers in this same file.
  - **Query key** `['watchlist-13f-snapshots', sortedStockIds]`
    canonicalizes input order so two callers with the same
    set of stock_ids share the cache.
  - **`enabled: stockIds.length > 0`** prevents the snapshot
    request from firing on an empty watchlist.
  - **`staleTime: 60_000`** — 13F filings are quarterly EOD-style
    data; no on-focus refetch needed.
  - **`/watchlist/page.tsx`** wires the hook in alongside
    `membersQuery` after `sortedMembers` is computed. The Map is
    built into `snapshotsByStockId` and `void`-referenced to keep
    lint happy until MVP7-03 consumes it. Render is unchanged
    (no new columns).
  - **Scope refinements** (recorded in spec):
    - SR0: data plumbing only; no render of 13F columns / drawer
      / glyph (MVP7-03 / 04 / 05).
    - SR1: no backend changes; `_watchlist_rows_for_memberships`
      untouched.
    - SR2: no responsive-skip in V1 (deferred to MVP7-04).
    - SR3: no frontend unit tests for this thin module.
    - SR4: no drawer / detail prefetch.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint warnings or
  errors.
- `docker compose exec web npm run build` → compiled successfully.
  `/watchlist` route bundle 17.1 → 17.2 kB (+0.1 kB for the
  hook + map helper); First Load JS 190 kB unchanged.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api pytest -q` → **800 passed** (unchanged
  from MVP7-01); 0 warnings. No backend changes.
- Manual probe: open `/watchlist` in browser, DevTools Network
  tab shows one `POST /api/v1/stocks/13f-snapshots` firing
  alongside the `GET /stock_pools/.../members` request whenever
  a watchlist with members is selected. Payload `stock_ids`
  matches the visible row stock_ids. Switching watchlists
  re-fires the snapshot fetch when stock_ids change.
