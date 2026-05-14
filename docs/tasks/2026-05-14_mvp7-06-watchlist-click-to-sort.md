# MVP7-06: Watchlist Click-to-Sort UX (13F Columns)

## Status

**Open 2026-05-14.** Authorized per PO direction. Scope strictly limited
to the four visible Watchlist 13F columns + the two universal columns
(Ticker, Company). All other watchlist columns stay non-sortable in V1.

Parent spec: `docs/tasks/2026-05-13_mvp7-03-watchlist-13f-columns.md`
§SR0 explicitly deferred click-to-sort to "a future MVP7-Nx ticket".
This is that ticket. The sort-key vocabulary is already frozen by
Pre-MVP7-01 D1 (conviction desc, delta-holders desc, tier ordinal
desc, severity); no new product decisions needed.

## Goal

Make the Watchlist 13F columns sortable by click, without changing any
default-sort semantics, without touching backend APIs, and without
making unavailable rows jump around when the sort direction flips.

## Scope In

Sortable columns (six total — strict cut):

| Column | Sort key | Default direction (first click) | Sortable value |
|---|---|---|---|
| Ticker | `ticker` | `asc` | row.ticker (string) |
| Company | `company` | `asc` | row.company_name (string, locale-insensitive) |
| Conviction | `conviction` | `desc` | snapshot.conviction_percentile |
| Δ Holders | `delta_holders` | `desc` | snapshot.delta_holders |
| Distinctiveness | `distinctiveness` | `desc` | tier ordinal: distinctive=3, mixed=2, crowded=1 |
| Caveats | `caveat_severity` | `desc` | severity ordinal: high-caution=3, caution=2, ok=1 |

**Note**: Caveats default direction diverges from Pre-MVP7-01 D1's
"severity asc" — users clicking the Caveats column typically want
to see *risky* signals first (worst at top), not clean ones.
Documented as deliberate divergence.

## Scope Out

- **Non-13F columns stay non-sortable**: F-Score 3Y, Price, Fair
  Value, MOS, Δ Today, Last Update. (User explicitly scoped to
  "only Watchlist 13F columns + maybe ticker/name".)
- **No new columns**: `consensus_count` and `score_confidence` are in
  the snapshot payload but not rendered as visible columns. Adding
  them is a separate ticket.
- **No backend changes**: sort is fully client-side over data already
  loaded by the existing `useWatchlistStock13FSnapshots` query.
- **No persisted sort state**: the active sort resets on page reload.
  URL / localStorage persistence is a separate concern.
- **Default sort semantics unchanged**: `sortWatchlistMembers` (MOS
  desc, ticker asc fallback) remains the no-active-sort fallback.

## D1 — `sortMembers` helper + three-state toggle (frontend)

**Root cause**: `frontend/lib/watchlistState.js` has only
`sortWatchlistMembers` (the legacy MOS-desc sort). No abstraction
exists for column-driven sorts. Adding the logic inline in `page.tsx`
would entangle render and sort — bad for testability.

**Fix contract**:

New file `frontend/lib/watchlistSort.js` (CommonJS, matching
`watchlistState.js` convention) exports:

- `WATCHLIST_SORT_KEYS` — exported constant tuple of sortable keys
  (`['ticker', 'company', 'conviction', 'delta_holders',
  'distinctiveness', 'caveat_severity']`).
- `DEFAULT_SORT_DIRECTION` — object mapping key → default direction
  on first click (per the table above).
- `nextSortState(currentState, clickedKey)` — implements the
  three-state click cycle:
  1. Click a **different** column → `{key: clicked,
     direction: DEFAULT_SORT_DIRECTION[clicked]}`.
  2. Click the **same** column at default direction → flip direction
     to the non-default (`asc ⇆ desc`).
  3. Click the **same** column at non-default direction → clear
     active sort → `{key: 'default', direction: 'desc'}`.
- `sortMembers(members, snapshotsByStockId, sortState)`:
  - When `sortState.key === 'default'`, delegate to
    `sortWatchlistMembers(members)` — bit-identical to current behavior.
  - When `sortState.key` is a 13F key, **unavailable rows always
    sort to the bottom** regardless of direction. Tiebreak among
    unavailable rows: ticker asc. This prevents no-13F-data rows
    from bouncing around when the user flips direction.
  - Tiebreak among available rows: ticker asc.
  - String sorts use `localeCompare` (Ticker/Company).

New file `frontend/lib/watchlistSort.d.ts` — TypeScript types
(`WatchlistSortKey`, `WatchlistSortState`, function signatures)
matching the `watchlistState.d.ts` pattern.

New file `frontend/lib/watchlistSort.test.js` — `node --test`
unit tests covering:

- `nextSortState`: three-state cycle for every column;
  switch-to-different-column resets to that column's default
  direction.
- `sortMembers`: default delegation; ticker asc/desc; company
  asc/desc; numeric 13F columns (conviction, delta_holders) asc/desc;
  ordinal 13F columns (distinctiveness, caveat_severity) asc/desc;
  unavailable rows always at bottom; unavailable rows do NOT swap
  position on direction flip; default-sort behavior unchanged.

## D2 — Wire into `/watchlist` page

**Root cause**: `frontend/app/(dashboard)/watchlist/page.tsx` uses a
plain `useMemo` calling `sortWatchlistMembers(members)` (line ~173).
The TableHead cells are static `<TableHead>Label</TableHead>` with
no click handlers.

**Fix contract**:

- New state: `const [sortState, setSortState] = useState<WatchlistSortState>({key: 'default', direction: 'desc'})`.
- Replace `sortedMembers` memo:
  ```tsx
  const sortedMembers = useMemo(
    () => sortMembers(members, snapshotsByStockId, sortState),
    [members, snapshotsByStockId, sortState],
  );
  ```
- The six sortable `<TableHead>` cells become buttons. A small
  `<SortableHeader sortKey={...} label={...} sortState={sortState}
  onSort={setSortState} />` component renders:
  - The column label
  - An indicator: `▲` (asc), `▼` (desc), or empty (inactive).
    Use lucide `ArrowUp` / `ArrowDown` icons sized `h-3 w-3` aligned
    inline with the label.
  - `<button>` wrapper with `onClick={() => onSort(nextSortState(sortState, sortKey))}`.
  - `aria-sort` attribute on the `<th>`: `"ascending" | "descending" | "none"`
    so screen readers announce the active sort state (WCAG 1.3.1).
- Non-13F `<TableHead>` cells stay as plain text labels — no buttons,
  no `aria-sort`.

## Verification

- `docker compose exec web node --test lib/watchlistSort.test.js` — green.
- `docker compose exec web npm run lint` — clean.
- `docker compose exec web npm run build` — clean.
- Manual probe:
  1. Open `/watchlist` (overview pool or any pool with both 13F and
     non-13F stocks) → default render is MOS-desc as today.
  2. Click "Conviction" → rows reorder by `conviction_percentile`
     desc; unavailable rows fall to the bottom; ▼ indicator appears
     in the header.
  3. Click "Conviction" again → flips to asc; ▲ indicator; unavailable
     rows still at the bottom (don't bounce).
  4. Click "Conviction" a third time → returns to default sort
     (MOS-desc, ticker asc fallback); no indicator anywhere.
  5. Click "Caveats" → high-caution stocks at top.
  6. Click "Δ Holders", then click "Ticker" → switches to ticker-asc
     (the column's default), not "ticker matching previous direction".
  7. Tab through the table header → focus reaches each sortable
     header; pressing Enter / Space activates the sort.
  8. Screen reader (VoiceOver / NVDA) reads "Conviction, sort
     descending" after click.

## Scope Refinements

- **SR0**: No backend changes. Sort is over data already in memory.
- **SR1**: Three-state toggle (default → flip → clear) instead of
  two-state. Lets users return to the canonical MOS-desc default
  without reloading the page — important because MOS-desc is not
  itself a click-to-sort target in this V1.
- **SR2**: Unavailable rows always at the bottom (not at the top
  even when direction is asc). Locks predictable row positions for
  no-13F-data stocks across direction flips.
- **SR3**: Tiebreak among rows with identical sort values: ticker asc.
  Matches the existing default-sort tiebreak.

## Files Expected to Change

- `frontend/lib/watchlistSort.js` (new)
- `frontend/lib/watchlistSort.d.ts` (new)
- `frontend/lib/watchlistSort.test.js` (new)
- `frontend/app/(dashboard)/watchlist/page.tsx` (sort state +
  SortableHeader component + TableHead replacements)
- `docs/tasks/2026-05-14_mvp7-06-watchlist-click-to-sort.md` (this)

## Sign-Off Trail

- [x] D1 shipped 2026-05-14: `watchlistSort.js` (helper) +
      `watchlistSort.d.ts` (types) + `watchlistSort.test.js`
      (24 `node --test` cases covering `nextSortState` three-state
      cycle, all six sortable columns asc/desc, unavailable row
      bottom-pinning + direction-flip invariance, ticker tiebreak,
      null-input defensiveness).
- [x] D2 shipped 2026-05-14: `/watchlist` page wires sortState +
      SortableHeader on the six sortable columns; `aria-sort` +
      ▲/▼ indicators; cycle broken by deriving `watchlistStockIds`
      from `members` directly (not the sorted output) so column
      sort changes don't churn the 13F snapshots query.
- [x] `node --test lib/watchlistSort.test.js` → 24 passed; lint
      clean; build clean (/watchlist route 22.7 kB First Load).
- [x] Manual probe passed 2026-05-14 — `/watchlist` 13F columns
      sort correctly (user confirmation).
- [x] **MVP7-06 closed 2026-05-14.**
