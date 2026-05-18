# MVP7-03: Four 13F Columns + Group Header on /watchlist

## Status

**Authorized to start (PO 2026-05-13 after MVP7-02 ship).** Third
ticket on the MVP7 Watchlist × 13F Insight track.

## Goal / Acceptance Criteria

Render the four V1 13F signals as columns on `/watchlist` under a
`13F (YYYY-Qn, as of YYYY-MM-DD)` group header. **Render only** —
responsive collapse + MOS × 13F glyph land in MVP7-04, drawer lands
in MVP7-05.

Acceptance criteria (anchored to Pre-MVP7-01 D1):

- **Watchlist Table** extended to a 2-row header:
  - **Row 1** (group header): existing 8 columns get a single
    transparent spacer (`colSpan={8}`); the new 13F group gets one
    `<TableHead colSpan={4}>` reading `13F (YYYY-Qn, as of YYYY-MM-DD)`
    where the date is `period_filing_deadline` from the MVP7-01
    payload.
  - **Row 2** (column names): existing 8 column headers preserved
    + 4 new headers (`Conviction` / `Δ Holders` / `Distinctiveness`
    / `Caveats`).
- **Four `<TableCell>` per row** rendered by a new
  `Watchlist13FColumns` component that consumes the snapshot from
  the Map built in MVP7-02.
- **Conviction column** — percentile bucket chip:
  - `> 0.85` → `"Top 15%"` chip, success variant.
  - `> 0.50` → `"Mid"` percentile chip, secondary variant
    (e.g. `"Mid 73%"`).
  - `≤ 0.50` → `"Bot N%"` chip, outline variant.
  - Tooltip on chip: `"Conviction percentile across {universe_size}
    ranked stocks for {period}."`
- **Δ Holders column** — signed integer chip:
  - `> 0` → `"+N"` chip, success variant.
  - `< 0` → `"−N"` chip, danger variant (Unicode minus
    `−`, not ASCII hyphen).
  - `0` → `"0"` chip, secondary variant.
  - Tooltip: `"{adders_count} adders, {reducers_count} reducers
    this quarter."`
- **Distinctiveness column** — 3-tier chip:
  - `distinctive` → success variant, label `"Distinctive"`.
  - `mixed` → secondary variant, label `"Mixed"`.
  - `crowded` → warning variant, label `"Crowded"`.
  - Tooltip: `"{consensus_count} qualifying ranked holders. Tier
    derived from coverage × consensus density."`
- **Caveats column** — severity chip + icon:
  - `ok` → success variant, label `"OK"`, no tooltip body.
  - `caution` → warning variant, label `"Caution"`, tooltip lists
    caveat codes (`caveat_codes.join(', ')`).
  - `high-caution` → danger variant, label `"Caution"` with an
    `AlertTriangle` icon, tooltip lists caveat codes.
- **Unavailable state** (snapshot has `available: false`):
  - All four cells render the same `—` placeholder.
  - The whole row's 13F section gets a single tooltip on each cell
    explaining the unavailable reason:
    - `no_holders` → `"No 13F-filer holds this stock above the
      $200M AUM reporting threshold for {period}."`
    - `below_min_holders` → `"Below min_holders threshold.
      Insufficient consensus for ranking."`
    - `no_qualifying_period` → `"13F data is unavailable for
      this period."`
- **Loading state**: while `snapshotsQuery.isPending`, the four
  cells per row render `—` with no tooltip. No skeleton in V1.
- **Error state**: if `snapshotsQuery.isError`, the four cells
  per row render `⚠` with tooltip `"13F snapshot failed to load."`
  Existing watchlist columns continue to render unaffected
  (failure isolation from MVP7-02).
- **Group header when no snapshot**: when
  `snapshotsQuery.data?.period` is null (no qualifying period in
  the DB), the group header reads `13F (no data)` with a tooltip
  `"No 13F filings indexed yet."`

## Sort Behavior (Scope Refinement)

The Pre-MVP7-01 D1 table specified sort keys per column
(conviction desc, delta-holders desc, tier ordinal desc, severity
asc). **V1 does not implement user-controlled click-to-sort** —
the existing `/watchlist` table has no click-to-sort on any
column (MOS / Price / FV / etc.), and introducing it for only
the 13F columns would be UX-inconsistent. The 13F sort-key
specification is preserved in this spec as the canonical default
ordering for a future MVP7-Nx ticket that adds table-wide
click-to-sort across all columns at once.

Watchlist default ordering remains **MOS desc** + ticker
alphabetical fallback (`sortWatchlistMembers`). The four 13F
columns render as **visual-scan-only** chips — operators eyeball
the column for the strongest signal; sortable lift comes later.

## Scope In

- `frontend/lib/watchlist13f.ts` — extended with render helpers:
  - `formatConvictionLabel(percentile: number): string` →
    `"Top 15%"` / `"Mid 73%"` / `"Bot 22%"`.
  - `convictionTone(percentile: number): BadgeVariant`.
  - `formatDeltaHolders(delta: number): string` → `"+3"` /
    `"−1"` / `"0"`.
  - `deltaHoldersTone(delta: number): BadgeVariant`.
  - `distinctivenessLabel(tier): string` (capitalized form).
  - `distinctivenessTone(tier): BadgeVariant`.
  - `caveatSeverityLabel(severity): string`.
  - `caveatSeverityTone(severity): BadgeVariant`.
  - `unavailableTooltip(reason, period): string`.
  - `groupHeaderLabel(period, periodFilingDeadline): string`.
- `frontend/components/watchlist/Watchlist13FColumns.tsx` (new):
  - Props: `{snapshot, period, queryStatus}` where queryStatus is
    `"idle" | "pending" | "error" | "success"`.
  - Renders four `<TableCell>`s.
- `frontend/app/(dashboard)/watchlist/page.tsx`:
  - Replace the single-row `<TableHeader>` with a 2-row header.
  - Insert `<Watchlist13FColumns>` per row inside the existing
    `sortedMembers.map`.
- This task file.

## Scope Out / Scope Refinements

- **SR0**: No click-to-sort UX (sort key spec preserved for future
  ticket).
- **SR1**: No responsive collapse / mobile hiding (MVP7-04).
- **SR2**: No MOS × 13F cross-signal glyph (MVP7-04).
- **SR3**: No click-into drawer with top holders / per-manager
  magnitudes (MVP7-05).
- **SR4**: No backend changes.
- **SR5**: No new shadcn Tooltip primitive. Use the HTML `title`
  attribute for V1 chip tooltips. Adding a shadcn Tooltip with
  full ARIA semantics is a UX-track ticket, not blocking V1.
- **SR6**: No frontend unit tests for the new helpers — they're
  thin pure functions; lint + build + manual probe is the
  verification bar (matches MVP6-02..05 pattern).
- **SR7**: No skeleton loading state per cell. The 4 cells render
  `—` while pending. A skeleton system is a UX-track future
  improvement.

## PRD / Decision References

- `docs/tasks/2026-05-13_pre-mvp7-01-watchlist-13f-insight-decision-gate.md`
  D1 (column display + sort-key spec), D2 (group header format),
  D3 (empty state copy).
- `docs/tasks/2026-05-13_mvp7-01-stocks-13f-snapshots-endpoint.md` —
  upstream endpoint payload contract.
- `docs/tasks/2026-05-13_mvp7-02-watchlist-13f-data-plumbing.md` —
  data layer this ticket consumes.

## Files Expected To Change

- `frontend/lib/watchlist13f.ts`
- `frontend/components/watchlist/Watchlist13FColumns.tsx` (new)
- `frontend/app/(dashboard)/watchlist/page.tsx`
- This task file.

## Verification

- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec api pytest -q` (sanity)
- Manual probe:
  1. Open `/watchlist`.
  2. Confirm 2-row header: top row shows `13F (YYYY-Qn, as of
     YYYY-MM-DD)` over the four new columns; bottom row shows
     `Conviction / Δ Holders / Distinctiveness / Caveats` plus
     the existing 8 column names.
  3. Add a ticker that exists in seeded 13F data (run dev
     fixture seeder first if needed); confirm the four cells
     populate with chips.
  4. Add a ticker with no 13F coverage (e.g. a small-cap not in
     fixture); confirm the cells render `—` with tooltip.
  5. Hover each chip; confirm tooltip copy renders.

## Progress Notes

- 2026-05-13: Task spec filed.
- 2026-05-13: Implementation:
  - **`frontend/lib/watchlist13f.ts`** appended with the MVP7-03
    render helpers: `formatConvictionLabel` (percentile → "Top
    N% / Mid N% / Bot N%"), `convictionTone`, `formatDeltaHolders`
    (signed integer with Unicode minus `−`), `deltaHoldersTone`,
    `distinctivenessLabel` + `distinctivenessTone`,
    `caveatSeverityLabel` + `caveatSeverityTone`,
    `unavailableTooltip` (three reason-code branches),
    `groupHeaderLabel` (period + deadline format). All pure
    functions; type-narrowed via the snapshot discriminated union.
  - **New component** `frontend/components/watchlist/Watchlist13FColumns.tsx`
    renders four `<TableCell>`s per row with discriminated handling
    of available / unavailable / pending / error states. Native
    HTML `title` attribute carries tooltip copy per MVP7-03 SR5.
    The `caveat_severity="high-caution"` chip prepends an
    `AlertTriangle` icon (the existing lucide-react icon already in
    the bundle).
  - **`/watchlist/page.tsx`** Table extended to a 2-row header:
    row 1 = spacer (`colSpan={8}`) + 13F group label (`colSpan={4}`)
    + trailing action-cell placeholder; row 2 = existing 8 column
    headers + 4 new 13F column headers + trailing placeholder.
    Group header carries a tooltip explaining the filing deadline.
    Per-row `<Watchlist13FColumns>` receives the snapshot from the
    MVP7-02 Map plus the derived `queryStatus` (idle / pending /
    error / success) so the four cells can compose the right state
    locally.
  - Snapshot query status derivation: `idle` when there are no
    stocks; `pending` while React Query is fetching; `error` on
    failure; `success` on data. Idle / pending render placeholder
    `—`; error renders `⚠` with a "13F snapshot failed to load"
    tooltip. Watchlist's core columns (ticker / price / FV / MOS)
    are unaffected by 13F snapshot state — failure isolation per
    MVP7-02 design intent.
  - **`min-w-[1080px]` → `min-w-[1400px]`** on the Table to make
    room for the four new columns. The Table primitive already
    wraps in `overflow-auto` so narrow viewports still scroll.
  - Subtle vertical separator (`border-l border-border/60`) on the
    first 13F column header and group header to visually delimit
    the 13F group from the existing watchlist columns.
  - **Scope refinements** (recorded in spec):
    - SR0: no click-to-sort UX in V1.
    - SR1: no responsive collapse (MVP7-04).
    - SR2: no MOS × 13F glyph (MVP7-04).
    - SR3: no drawer (MVP7-05).
    - SR4: no backend changes.
    - SR5: no shadcn Tooltip primitive — native `title`.
    - SR6: no frontend unit tests for the new helpers.
    - SR7: no skeleton loading state per cell.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint warnings or
  errors.
- `docker compose exec web npm run build` → compiled successfully.
  `/watchlist` route bundle 17.2 → 16.1 kB (Next.js extracted the
  Watchlist13FColumns helper into a shared chunk); First Load JS
  190 → 193 kB.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api pytest -q` → **800 passed**, 0
  warnings. No backend changes.
- Manual probe: browser hits `/watchlist`. 2-row header renders
  with `13F (YYYY-Qn, as of YYYY-MM-DD)` spanning the four new
  columns. Seeded stocks with 13F coverage show conviction
  percentile / Δ holders / distinctiveness / caveats chips. Stocks
  without 13F coverage show `—` with hover tooltip explaining the
  reason. Loading state shows `—`; killing the snapshot endpoint
  network response shows `⚠` with the error tooltip.
