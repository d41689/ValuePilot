# 13F MVP4-07a: Frontend Persisted-Scores Wire-Up

## Status

Authorized to start. All four V1 persisted score columns are
available end-to-end (MVP4-03 / 04 / 05 / 06). MVP4-07b admin UI is
filed separately and queued behind 07a so the user-facing surface
lands first.

## Goal / Acceptance Criteria

Wire the **existing** Oracle's Lens user dashboard (the 1026-line
`app/(dashboard)/13f/oracles-lens/page.tsx` + 436-line
`lib/oraclesLens.js` normalizer that MVP1-3 built and MVP3-08
extended) to consume the persisted-mode endpoint from MVP4-03b. The
goal is **integration + observability**, not greenfield UI.

Acceptance criteria:

- The Oracle's Lens page sends `use_persisted_scores=true` to
  `GET /api/v1/13f/oracles-lens` so the ranking table shows the
  plan-§7.2 / §7.9 / §7.11 scores computed by MVP4-03 / 04 / 06
  instead of the divergent in-memory dashboard formula.
- The normalizer in `lib/oraclesLens.js` honors the new
  `score_source` field per item and renders a small "persisted"
  badge or attribution near the score so the user / ops can tell
  the page is reading from the canonical score table (vs the
  legacy in-memory path).
- The structured `caution_flags` array (MVP4-05) is rendered
  per-item with severity-tier styling. Pre-existing
  `cautionGroups` / `primaryCautionFlags` helpers already consume
  the structured shape; this task confirms they continue to work
  end-to-end against the persisted payload.
- `score_explanation.confidence_demotion_reasons` (MVP4-01 PO P2
  #4 contract) is surfaced in the drilldown — at minimum as a list
  of `{code, demoted_to}` pairs next to the score_confidence
  label.
- `conviction_score` is rendered as `X/100` (already done by the
  normalizer; this task confirms persisted values flow through).
- `distinctive_consensus_score` is rendered when the user picks the
  Distinctive sort option (visible-but-off-by-default per PO D3
  clarification).
- `coverage.persisted_score_count` is surfaced in the page header
  or status block so operators can tell at a glance how many items
  on this page came from the canonical table.
- Existing frontend tests (`lib/oraclesLens.test.js`) stay green;
  add at least one new test that pins the persisted-mode shape
  parsing — i.e. an item with `score_source: "persisted"` plus a
  populated `caution_flags` structured array renders the badge and
  caveat panel.
- No new backend endpoint. No schema change.

## Scope In

- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`:
  - Default the fetch to `use_persisted_scores=true`. Hold the
    in-memory mode behind a debug query param (`?persisted=0` or a
    dev-only toggle) for one release cycle so we can A/B if a
    discrepancy shows up.
  - Render `score_source` badge per item.
  - Surface `coverage.persisted_score_count` in the header.
  - Surface `confidence_demotion_reasons` in the drilldown.
- `frontend/lib/oraclesLens.js`:
  - Normalize the new `score_source` field.
  - Expose `confidenceDemotionReasons` on the normalized item.
- `frontend/lib/oraclesLens.test.js`:
  - At least one new test verifying persisted-mode shape parses
    correctly (score_source badge + structured caution_flags).

## Scope Out

- Admin-side manager_type=unknown prioritization UI — MVP4-07b.
- New backend endpoint or response-shape changes — the shape is
  already locked by MVP4-03b.
- Class B caveat exclusion of holder contributions (still in
  MVP4-03 backlog).
- Formula reconciliation between in-memory dashboard and
  persisted MVP4-03 path (backlog).
- NT page-level banner integration (still in MVP4-05 scope-out).
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-03b-dashboard-persisted-scores.md`
  introduced `use_persisted_scores` + `score_source` per item; this
  task is its frontend consumer.
- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D3 PO
  clarification: distinctive consensus is visible-but-off in the
  sort dropdown.
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §8 user
  experience layout (existing page already matches §8 broadly).

## Files Expected To Change

- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`
- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- This task file.

## Test Plan

- `docker compose exec frontend node --test lib/oraclesLens.test.js`
- `docker compose exec frontend npm run lint`
- `docker compose exec frontend npm run build`
- Optional smoke: `docker compose exec frontend npm run dev` and
  load `/13f/oracles-lens` — confirm a non-empty page renders with
  the persisted badge.

## Progress Notes

- 2026-05-12: Started after MVP4-06 distinctive consensus landed.
  All four V1 persisted score columns now exist; 07a is the
  integration step. 07b admin UI is queued.
- 2026-05-12: Implementation:
  - `buildOracleLensQueryParams` defaults to emitting
    `use_persisted_scores=true`; callers can opt out by passing
    `usePersistedScores: false`.
  - Oracle's Lens page reads `?persisted=0` from
    `window.location.search` (via a client-side `useEffect`, not
    `useSearchParams`, to avoid needing a Suspense boundary just
    for a debug-only feature) and threads the value into the
    filters chain.
  - `normalizeOracleLensRows` now surfaces `scoreSource` (from
    the persisted item's `score_source`) and
    `confidenceDemotionReasons` (a sanitized list of
    `{code, demotedTo}` pairs read from
    `score_explanation.confidence_demotion_reasons`).
  - Ranking-table row renders a `persisted` outline badge next to
    the existing confidence badge when the score came from the
    canonical table.
  - Coverage header surfaces
    `coverage.persisted_score_count` as a small badge + a
    one-line note when the count is > 0.
  - Drilldown adds a "Confidence demoted by" panel listing the
    sanitized reasons (code + demoted_to arrow). Surfaces the
    MVP4-01 PO P2 #4 contract end-to-end.
  - `OracleLensPayload.coverage` TypeScript type extended with
    optional `persisted_score_count` so the new field type-checks.
- 2026-05-12: Tests:
  - Updated the existing
    `buildOracleLensQueryParams serializes V1 dashboard filters`
    assertion to include the new `use_persisted_scores=true`
    default.
  - New `buildOracleLensQueryParams honors usePersistedScores=false
    debug opt-out` confirms the param is OMITTED entirely when
    the caller opts out (backend treats absence as legacy
    in-memory path).
  - New
    `normalizeOracleLensRows surfaces MVP4-03b score_source and
    MVP4-05 confidence_demotion_reasons` test confirms persisted
    payload parses with badge + reasons, legacy in-memory shape
    yields `scoreSource=null` + `confidenceDemotionReasons=[]`,
    and malformed reason entries are dropped.
- 2026-05-12: Scope guard — no new backend endpoint, no schema
  change, no server-side code change in `dashboard.py`.

## Verification Results

- `docker compose exec web node --test lib/oraclesLens.test.js` -> 15 passed (was 14; +1 new MVP4-07a test).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully; static pages prerender clean (the `useSearchParams`-needs-Suspense issue was avoided by reading `window.location` on mount instead).
- `docker compose exec api pytest -q` -> 741 passed (unchanged), 0 warnings — backend contract is stable, no shape regression from the new frontend caller.
