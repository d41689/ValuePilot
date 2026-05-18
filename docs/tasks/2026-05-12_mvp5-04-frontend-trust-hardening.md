# 13F MVP5-04: Frontend Trust + Accessibility Hardening

## Status

Authorized to start. Fourth ticket of MVP 5
(`docs/tasks/2026-05-12_13f-mvp5-execution-plan.md`).

Independent of MVP5-03 Phase 3 / 4. Depends on MVP5-02 backend
(`53a9f2f`) for the `excluded_holders` field rendered in the
drilldown.

## Goal / Acceptance Criteria

Polish-tier pass on the Oracle's Lens user dashboard +
admin priority Card. The most consequential change is the
demotion-reason label mapping — investors should read
"Historical data needs validation", not `HISTORICAL_BACKFILL_NEEDS_VALIDATION`.

Source: FE #8 #2 / #3 / #5 / #7 in `docs/13f/mvp4-reviews.md`.

Acceptance criteria:

- `DEMOTION_REASON_LABELS` constant added to
  `frontend/lib/oraclesLens.js` mapping every rule_code in
  the union of `_LOW_CAVEATS`, `_MEDIUM_CAVEATS`, and
  `CONFIDENTIAL_TREATMENT` (per the canonical backend set)
  to a human-readable string. Unmapped codes fall back to
  the raw string rendered inside a `<details>` element so
  operator debugging still works without confusing
  investors.
- `normalizeOracleLensRows` exposes a `label` field on each
  `confidenceDemotionReasons` entry (resolved via the new
  map) alongside the existing `code` and `demotedTo` fields.
- `normalizeOracleLensRows` exposes a new `excludedHolders`
  array on every item, populated from
  `score_explanation.excluded_holders` (MVP5-02), with each
  entry shaped as `{managerId, managerCanonicalName,
  exclusionReason, exclusionReasonLabel}`.
- Demoted-to underscores replaced with spaces in the rendered
  string: `medium_confidence` → "medium confidence".
- `oracles-lens/page.tsx` drilldown renders the demotion
  reasons using the friendly `label`, drops the `font-mono`
  styling, and keeps the raw `code` accessible inside an
  expanded `<details>` for operator debugging.
- `oracles-lens/page.tsx` drilldown renders the MVP5-02
  `excludedHolders` array as a new "Holders excluded from
  score" section listing the manager name and the friendly
  exclusion-reason tag.
- Slide-out drilldown panel gets ARIA dialog semantics:
  - `role="dialog"`
  - `aria-modal="true"`
  - `aria-labelledby` pointing at the "Candidate Review"
    title (the title needs a stable `id`).
  - Focus moves to the close button when the panel opens.
  - Focus restores to the element that triggered the open
    (the row button or the bubble) when the panel closes.
- Admin Unknown Manager Priority Card empty states:
  - State 1 ("no persisted scores yet") reworded to include
    a directional hint pointing at the historical backfill
    section above.
  - State 2 ("no unknowns contribute") reframed as a
    positive all-clear, with the quarter label injected
    from the query response.
- Admin priority `<Table>` wrapped in
  `<div className="overflow-x-auto">` so the
  worst_score_confidence column doesn't clip on narrow
  viewports.
- Inline retirement comment in `oracles-lens/page.tsx`
  pointing at the `useEffect` + `useState` block that reads
  `?persisted=0` — when MVP5-03 Phase 4 lands and the flag
  retires, those two lines come out and
  `usePersistedScores=true` inlines in
  `buildOracleLensQueryParams`.
- `frontend/lib/oraclesLens.test.js` adds two new test
  cases pinning the new normalizer behavior:
  - `DEMOTION_REASON_LABELS` lookup happy path + raw-code
    fallback for an unknown rule_code.
  - `normalizeOracleLensRows` populates `excludedHolders`
    with `exclusionReason` + `exclusionReasonLabel`.

## Scope In

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- This task file.

## Scope Out

- Persisted badge label rename ("persisted" → "v1 scored").
  Stays for V1; needs a real UX consultation per FE
  rejection R5.
- New visualization (Track A3 bubble chart is post-MVP5).
- Manager-type editor deep-link from the admin Card. Lands
  in MVP5-05.
- Any backend schema or API change. MVP5-04 consumes the
  MVP5-02 payload as-is.

## PRD / Decision References

- `docs/13f/mvp4-reviews.md` — FE #8 #2 / #3 / #5 / #7.
- `docs/tasks/2026-05-12_13f-mvp5-execution-plan.md` — MVP5-04
  scope.
- `docs/tasks/2026-05-12_mvp5-02-amendment-exclusion.md` —
  `excluded_holders` payload contract.

## Files Expected To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- This task file.

## Test Plan

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec api pytest -q` (regression check — no
  backend changes expected to regress).

## Progress Notes

- 2026-05-12: Task spec filed; reading existing frontend
  surface in `oraclesLens.js` and `oracles-lens/page.tsx`
  before code edits.
- 2026-05-12: Implementation:
  - `oraclesLens.js`: new `DEMOTION_REASON_LABELS` map covering
    8 canonical caveat codes (PARTIAL_COVERAGE,
    NT_QUARTER_STREAK_BREAK, PRE_2023_PRE_HISTORY_UNAVAILABLE,
    AMENDMENTS_PENDING, AMENDMENT_FAILED,
    HISTORICAL_BACKFILL_NEEDS_VALIDATION, CONFIDENTIAL_TREATMENT,
    stale_until_recompute) plus `EXCLUSION_REASON_LABELS` for
    the MVP5-02 codes. Helper functions
    `labelForDemotionReason` / `labelForExclusionReason` /
    `humanizeTier` exported for tests and for direct use by
    pages that don't go through `normalizeOracleLensRows`.
  - `normalizeOracleLensRows` now emits `label` and
    `demotedToLabel` on every `confidenceDemotionReasons`
    entry, and a new `excludedHolders` array with shape
    `{managerId, managerCanonicalName, exclusionReason,
    exclusionReasonLabel}`. Malformed entries are filtered
    out defensively (same pattern as the existing demotion
    reason normalizer).
  - `oracles-lens/page.tsx` drilldown renders the friendly
    `reason.label`, replaces the previous raw-code-with-mono
    display with a `<details>` element holding the raw code
    one click away, and uses the humanized tier
    ("medium confidence" instead of "medium_confidence").
  - Added a new "Holders excluded from score" section in the
    drilldown listing each excluded holder + an outline
    Badge with the friendly exclusion reason.
  - ARIA dialog semantics on the slide-out panel:
    `role="dialog"`, `aria-modal="true"`,
    `aria-labelledby="oracles-lens-drilldown-title"`.
    Title span gets the matching `id`. The bubble-tap and
    row-click handlers now go through `openDrilldown(stockId)`
    which captures `document.activeElement` into a ref
    before opening; a `useEffect` on `selectedStockId` focuses
    the close button on open (via `useRef`) and restores
    focus to the captured trigger on close.
  - Retirement comment added above the `?persisted=0`
    `useState` + `useEffect` block pointing at the cleanup
    steps when MVP5-03 Phase 4 lands.
  - Admin Unknown Manager Priority Card:
    - State 1 copy rewritten to point at the Historical
      Backfill section ("Use the Historical Backfill section
      above to score a quarter, then return here...").
    - State 2 copy reframed as a positive all-clear
      ("All contributing managers are typed for {quarter}.
      Signal weights are fully resolved...").
    - `<Table>` wrapped in
      `<div className="overflow-x-auto">` so the
      worst_score_confidence column stays visible on narrow
      viewports.

  Tests:
  - `oraclesLens.test.js`: extended the existing MVP4-07a
    test to assert the new `label` + `demotedToLabel` fields
    + the empty `excludedHolders` for legacy-shape rows.
    Added two new tests:
    `MVP5-04 labelForDemotionReason maps known codes and
    falls back to raw` (covers 8 canonical codes + 1 unknown
    code) and
    `MVP5-04 normalizeOracleLensRows surfaces excludedHolders
    with friendly labels` (covers both exclusion reasons +
    malformed-entry drop).

## Verification Results

- `docker compose exec web node --test lib/oraclesLens.test.js` -> **17 passed** (was 15 after MVP4 review fixes; +2 new MVP5-04 tests).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully (no Suspense regression; the `?persisted=0` `useEffect` workaround still in place).
- `docker compose exec api pytest -q` -> 772 passed (regression-check; no backend changes in this commit).
