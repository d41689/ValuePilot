# MVP7-04: Watchlist 13F Responsive Collapse + MOS × 13F Cross-Signal Glyph

## Status

**Authorized to start (PO 2026-05-13 after MVP7-03 ship).** Fourth
ticket on the MVP7 Watchlist × 13F Insight track.

## Goal / Acceptance Criteria

Two independent UX additions on `/watchlist`, both anchored to
Pre-MVP7-01 D4 + D5:

1. **Responsive collapse** of the 13F column group across three
   viewport tiers.
2. **MOS × 13F cross-signal glyph** on the existing MOS column —
   not a new column, a visual enhancement.

### D4 Responsive Strategy

Pre-MVP7-01 D4 maps to Tailwind breakpoints:

| D4 tier | Pixel range | Tailwind prefix | Behavior |
|---------|-------------|------------------|----------|
| **lg+** | ≥ 1280px | `xl:` | All four 13F columns + group header visible inline. |
| **md**  | 768–1279px | `md:` through `xl:-1` | 13F group hidden by default. A "Show 13F" toggle button above the table reveals the four columns + group header. State persists in `localStorage` under key `watchlist-13f-expanded`. |
| **sm**  | < 768px | below `md:` | 13F group hidden entirely. Toggle button hidden too. (Per-row stacked view explicitly deferred per Pre-MVP7-01 D4 SR.) |

Implementation:

- Each 13F-related cell (group header `<TableHead colSpan={4}>`, 4
  column-name `<TableHead>`s, 4 per-row `<TableCell>`s) gets a
  conditional Tailwind class:
  - When the group is hidden: `hidden xl:table-cell` (group
    header uses `hidden xl:table-cell` too — the `xl:` prefix
    matches D4's "≥ 1280px lg+").
  - When the group is expanded (md only): add `md:table-cell` so
    cells become visible at md+.
  - At sm, no class applies → `hidden` wins → cells stay hidden.
- Toggle button visibility: `hidden md:inline-flex xl:hidden` so
  it only renders at md viewport (768–1279px).
- The toggle label reads `"Show 13F"` when collapsed, `"Hide 13F"`
  when expanded. A `ChevronDown` / `ChevronUp` lucide icon to its
  right communicates state.
- localStorage hydration via `useEffect`: read `watchlist-13f-expanded`
  on mount, default to `false` (collapsed). Write back on every
  state change.

### D5 MOS × 13F Cross-Signal Glyph

Compute a 4-tier cross-signal from each row's `mos` and the matching
snapshot's `delta_holders`. Render a small lucide icon glyph
**appended to the existing MOS cell** (not a new column), per D5.

| Signal | Condition | Glyph | Color | Tooltip |
|--------|-----------|-------|-------|---------|
| `aligned` | `mos ≥ 0.20` AND `delta_holders ≥ +1` | `Check` | emerald-600 | "Aligned: smart money is adding into your value setup." |
| `exit-divergence` | `mos ≥ 0.20` AND `delta_holders ≤ −1` | `TriangleAlert` | amber-600 | "Re-examine: smart money is exiting while you see value." |
| `buy-divergence` | `mos ≤ 0` AND `delta_holders ≥ +1` | `TriangleAlert` | amber-600 | "Re-examine FV: smart money is adding despite no margin of safety." |
| `neutral` | otherwise (including `mos === null` or `delta_holders` unavailable) | (none) | — | — |

When the snapshot is unavailable (no 13F data for the stock,
loading, error, or `available: false`), the glyph computation
returns `neutral` and nothing renders. The MOS cell continues to
display the value text exactly as before.

## Scope In

- `frontend/lib/watchlist13f.ts` — add `mosCrossSignal()` pure
  function returning `'aligned' | 'exit-divergence' | 'buy-divergence' | 'neutral'`.
- `frontend/components/watchlist/MosCrossSignalGlyph.tsx` (new) —
  tiny presentational component taking the signal + tooltip.
- `frontend/components/watchlist/Watchlist13FColumns.tsx` —
  accept new `mdExpanded: boolean` prop; apply responsive
  className composition (`hidden ${mdExpanded ? 'md:table-cell' : ''} xl:table-cell`)
  on each of the 4 cells.
- `frontend/app/(dashboard)/watchlist/page.tsx`:
  - Add `mdExpanded` state + localStorage sync.
  - Add toggle Button visible at md only.
  - Update Table header row 1 (group header) + row 2 (4 column
    names) to apply the same responsive class.
  - Inject `<MosCrossSignalGlyph>` into the MOS `<TableCell>`
    after the formatted MOS value.
- This task file.

## Scope Out / Scope Refinements

- **SR0**: No mobile (< 768px) per-row stacked view. Pre-MVP7-01
  D4 explicitly defers this.
- **SR1**: No click-to-sort UX (still deferred from MVP7-03 SR0).
- **SR2**: No drawer (MVP7-05).
- **SR3**: No backend changes.
- **SR4**: localStorage key namespace: just
  `watchlist-13f-expanded` (no per-user prefix). The current
  watchlist surface does not have per-user localStorage keys; if
  multi-user-on-same-browser becomes a concern, that's a
  cross-cutting auth-track concern, not a MVP7 concern.
- **SR5**: No SSR hydration race-condition guard. The state
  defaults to `false` on first render (matches localStorage's
  "no stored value" default), then a `useEffect` reads the stored
  value. The brief flash of "collapsed → expanded" on md when
  the user previously expanded is acceptable for V1.
- **SR6**: No frontend unit tests for the new helper. The
  `mosCrossSignal` function is a 4-branch pure function; lint +
  build + manual probe is the verification bar (matches
  MVP7-03 SR6).
- **SR7**: No keyboard shortcut for the toggle. The button is
  keyboard-focusable via Tab + activatable via Enter/Space (HTML
  default `<button>` semantics).

## PRD / Decision References

- `docs/tasks/2026-05-13_pre-mvp7-01-watchlist-13f-insight-decision-gate.md`
  D4 (responsive strategy) + D5 (MOS × 13F cross-signal).
- `docs/tasks/2026-05-13_mvp7-03-watchlist-13f-columns.md` — base
  column rendering that this ticket layers responsive + glyph on.

## Files Expected To Change

- `frontend/lib/watchlist13f.ts`
- `frontend/components/watchlist/MosCrossSignalGlyph.tsx` (new)
- `frontend/components/watchlist/Watchlist13FColumns.tsx`
- `frontend/app/(dashboard)/watchlist/page.tsx`
- This task file.

## Verification

- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec api pytest -q` (sanity)
- Manual probe across three viewport widths:
  1. **xl (≥ 1280px)**: 13F columns visible inline; no toggle
     button rendered.
  2. **md (768–1279px), first visit**: 13F columns hidden; "Show
     13F" toggle visible above the table. Click → columns expand,
     button label switches to "Hide 13F". Reload → expanded state
     persists.
  3. **sm (< 768px)**: 13F columns + toggle button both hidden.
- Glyph: pick a stock with `mos ≥ 0.20` AND positive `delta_holders`;
  confirm green ✓ renders next to MOS value with tooltip
  "Aligned: smart money is adding...". Pick a stock with
  `mos ≥ 0.20` AND negative `delta_holders`; confirm amber ⚠
  renders. Stocks with no snapshot show no glyph.

## Progress Notes

- 2026-05-13: Task spec filed.
- 2026-05-13: Implementation:
  - **`frontend/lib/watchlist13f.ts`** extended with the
    cross-signal helpers: `MosCrossSignal` 4-tier union,
    `mosCrossSignal()` pure function (D5 four-quadrant logic with
    `neutral` for any null input), `mosCrossSignalTooltip()`
    one-sentence body copy per signal, `responsive13FCellClass()`
    that returns the Tailwind class string for the D4 responsive
    tiers (`hidden xl:table-cell` collapsed, `hidden md:table-cell
    xl:table-cell` expanded).
  - **New component** `frontend/components/watchlist/MosCrossSignalGlyph.tsx`
    renders nothing on `neutral`, a small `Check` (emerald-600)
    on `aligned`, and a small `TriangleAlert` (amber-600) on
    `exit-divergence` / `buy-divergence`. The `<title>` SVG
    child + `aria-label` carry the tooltip body.
  - **`Watchlist13FColumns`** accepts a new `mdExpanded` prop +
    optional `firstCellLeadingClass` (used to draw the vertical
    separator only on the leftmost 13F cell). Every cell + the
    placeholder fallback (idle / pending / error / unavailable)
    threads `responsive13FCellClass(mdExpanded)` through.
  - **`/watchlist/page.tsx`** wires:
    - `mdExpanded` `useState(false)` + two `useEffect`s for
      localStorage read (on mount) + write (on change). Key
      `watchlist-13f-expanded`.
    - Toggle Button with `hidden md:flex xl:hidden` so it only
      renders at md viewport. Label flips between `Show 13F` /
      `Hide 13F` plus a `ChevronDown` / `ChevronUp` icon.
      `aria-expanded` + `aria-controls` reference the column
      headers row for screen readers.
    - Table `min-w-` flips: `min-w-[1080px]` when collapsed at md
      (matches the existing watchlist width), `min-w-[1400px]` when
      expanded or at xl+.
    - Table header row 1 (group header `<TableHead colSpan={4}>`)
      and row 2 (4 column-name `<TableHead>`s) all apply the same
      `responsiveCellClass`.
    - MOS `<TableCell>` injects the `<MosCrossSignalGlyph>` after
      the formatted MOS value. Signal is computed inline by
      looking up the row's snapshot and passing
      `{mos: row.mos, deltaHolders: snap.available ? snap.delta_holders : null}`
      so unavailable / pending / error all flatten to `neutral`.
  - **Scope refinements** (recorded in spec):
    - SR0: no mobile per-row stacked view (Pre-MVP7-01 D4 defer).
    - SR1: no click-to-sort (MVP7-03 SR0 continues).
    - SR2: no drawer (MVP7-05).
    - SR3: no backend changes.
    - SR4: localStorage key `watchlist-13f-expanded` without
      per-user prefix.
    - SR5: no SSR hydration race-condition guard; brief
      collapsed→expanded flash on md is acceptable.
    - SR6: no frontend unit tests for the 4-branch pure helper.
    - SR7: no keyboard shortcut; HTML `<button>` semantics suffice.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint warnings or
  errors.
- `docker compose exec web npm run build` → compiled successfully.
  `/watchlist` route bundle 16.1 → 16.8 kB (+0.7 kB for the
  responsive logic + glyph component + localStorage state); First
  Load JS 193 kB unchanged.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api pytest -q` → **800 passed**, 0
  warnings. No backend changes.
- Manual probe across viewport widths:
  - **xl (≥ 1280px)**: four 13F columns + group header render
    inline; no toggle button visible.
  - **md (768–1279px) first visit**: 13F columns hidden, "Show
    13F" toggle visible above the table. Click expands.
    `localStorage.getItem('watchlist-13f-expanded') === 'true'`
    after expand; reload preserves expanded state.
  - **sm (< 768px)**: 13F columns + toggle both hidden; main
    watchlist renders unaffected.
- MOS × 13F glyph: with the seeded fixture, stocks with positive
  `delta_holders` and `mos ≥ 0.20` render a green Check next to
  MOS with the "Aligned…" tooltip; stocks with `mos ≥ 0.20` and
  negative `delta_holders` render an amber TriangleAlert with
  the "Re-examine…" tooltip; stocks without a snapshot render no
  glyph.
