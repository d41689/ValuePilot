# MVP6-07: Readiness + Quality Findings Page

## Status

**Authorized to start (PO 2026-05-12 after MVP6-06 ship).** Seventh
MVP6 ticket. Soft-depended on MVP6-04 (Manager + Filing deep
links from Quality reports). Hard-depended on MVP6-01.

## Goal / Acceptance Criteria

PRD §11.1 "Readiness" page. Lifts five surfaces off the index
page (one big Card + four smaller Cards + one drawer) into a
dedicated route that becomes the operational dashboard. After
this ticket, the index page's `/admin/13f` Overview hub shrinks
to: KPI nav strip + Admin Tasks Card + Manual Controls Card +
shared dialog mounts.

Acceptance criteria:

- **New route `/admin/13f/readiness`** wrapped with
  `<AdminPageLayout title="Readiness" description="Readiness
  level, blockers, quality findings, needs-validation queue,
  and per-quarter drill-through.">`.
- **Data Readiness & Operations Health Card** — full lift from
  index page lines 649–801. Same layout: 5 MetricTiles + freshness
  banner + ops health banner + 6 status badges + Current Quarter
  panel + Setup Checklist grid + Top Task banner.
- **Quality Reports Card** — full lift from index lines 807–855.
  Table of persisted `quality_reports` with status / error counts /
  summary.
- **Needs Validation Card** — full lift from index lines 1370–1411.
  Per-quarter open-findings count.
- **Unknown Manager Type Priority Card** — full lift from index
  lines 1413–1527. Includes the MVP6-02 manager deep-link to
  `/admin/13f/managers/{id}`.
- **Quarters Card + Quarter Detail Drawer** — full lift from
  index lines 865–931 + 1611–1890. Owns `selectedQuarter` +
  `quarterFilingStatus` + `quarterFilingOffset` state and uses
  `useQuarterDetailQuery`. The drawer surfaces filings paging /
  pending / failed / amendments / quality report sub-sections;
  retry-target buttons call the route's own `runJob` (the route
  owns its own copies of `pendingJob` / `triggerJob` /
  `JobPendingDialog` etc., per the MVP6-06 SR5 pattern).
- **`AdminPageLayout` nav** Readiness entry flipped to
  `shipped: true`, `href: '/admin/13f/readiness'`.
- **Overview hub Readiness card** on `/admin/13f` flipped from
  `<a href="#readiness">` to `<Link href="/admin/13f/readiness">`.
- **Overview hub Oracle's Lens card** href stays as
  `<a href="#oracles-lens">` — Oracle's Lens is on the
  user-facing `/13f/oracles-lens` page; the admin priority
  surface is now on `/admin/13f/readiness`. The Overview Oracle's
  Lens KPI nav card reads `unknownManagerPriorityQuery.data?.items
  ?.length` and should flip to `<Link href="/admin/13f/readiness">`
  too (it deep-links to the priority surface).

## Scope In

- `frontend/app/(dashboard)/admin/13f/readiness/page.tsx` (new).
- `frontend/components/admin13f/AdminPageLayout.tsx` (nav flip).
- `frontend/app/(dashboard)/admin/13f/page.tsx` (Card +
  drawer + state + memo + query removal; Overview hub Readiness
  + Oracle's Lens hrefs flipped).
- This task file.

## Scope Out / Scope Refinements

- **SR0**: No new backend endpoints. PRD §11 API surface is
  complete.
- **SR1**: No frontend unit tests for the new route — lint +
  build + manual probe is the verification bar (matches
  MVP6-02..06 pattern).
- **SR2**: Manual Controls Card stays on the index page.
  Although the Card uses `runJob` heavily (just like Historical
  Backfill / Batch Reparse which moved to Jobs in MVP6-06),
  Manual Controls is the "setup + first-pipeline-run" surface
  (bootstrap whitelist / match CIK / bootstrap stocks) and
  naturally belongs alongside the Tasks Card on the Overview
  hub. A future ticket can revisit if PO finds the duplication
  with Jobs trigger surfaces awkward.
- **SR3**: Admin Tasks Card stays on the index page. The Tasks
  Card surfaces page-level action items from `useTasksQuery`
  and is the hub's primary CTA surface; it consumes `runJob`
  for retry actions which stays on the index page per MVP6-06
  SR5.
- **SR4**: The new `/admin/13f/readiness` route owns its own
  copies of `pendingJob` / `triggerJob` / `runJob` /
  `pendingStaleReleaseJobId` / `requestStaleJobLockRelease` /
  `isJobActive` / `activeLockKeys` / `lockKeyForPayload` so the
  Quarter Detail Drawer's "Suggested Actions" + the Unknown
  Manager Type Priority's deep-link can work without depending
  on index state. Pattern matches MVP6-06 SR5 (intentional
  duplication, "minimum operational shape" mandate from
  Pre-MVP6-02 D4).

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §11.1
  (Readiness Page), §11.3 (Quality Findings + Needs Validation).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D4 + D6 + D7.
- `docs/tasks/2026-05-12_13f-mvp6-execution-plan.md` MVP6-07
  row.

## Files Expected To Change

- `frontend/app/(dashboard)/admin/13f/readiness/page.tsx` (new)
- `frontend/components/admin13f/AdminPageLayout.tsx`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- This task file.

## Test Plan

- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `docker compose exec api pytest -q`
- Manual probe:
  1. Re-seed; log in as admin.
  2. `/admin/13f` Overview Readiness card → `/admin/13f/readiness`.
  3. Big Data Readiness Card renders with seeded fixture data
     (readiness level + setup checklist + top task).
  4. Quality Reports table renders.
  5. Needs Validation Card renders (empty for fresh seed).
  6. Unknown Manager Type Priority Card renders; manager
     deep-link goes to `/admin/13f/managers/{id}`.
  7. Quarters Card renders seeded quarters; "Review" opens the
     Quarter Detail drawer with filings paging + counts +
     suggested actions + retry-target buttons.
  8. Suggested action button on Quarter Detail drawer triggers
     `JobPendingDialog` from the new route's own state.

## Progress Notes

- 2026-05-12: Task spec filed.
- 2026-05-12: Implementation:
  - **New route** `frontend/app/(dashboard)/admin/13f/readiness/page.tsx`
    wrapped with `<AdminPageLayout>`. Five Cards (Data Readiness
    & Operations Health, Quality Reports, Needs Validation,
    Unknown Manager Type Priority, Quarters) plus the Quarter
    Detail drawer + JobPendingDialog mount. Owns its own copies
    of `pendingJob` / `triggerJob` / `runJob` / `isJobActive`
    / `activeLockKeys` / `lockKeyForPayload`.
  - **`AdminPageLayout` nav** Readiness entry flipped to
    `shipped: true` with `href: '/admin/13f/readiness'`.
  - **Overview hub Readiness card** on `/admin/13f` flipped from
    `<a href="#readiness">` to `<Link href="/admin/13f/readiness">`.
  - **Overview hub Oracle's Lens card** flipped from
    `<a href="#oracles-lens">` to `<Link href="/admin/13f/readiness">`
    (deep-links to the Unknown Manager Type Priority surface).
  - **Index page deletions** (~770 lines: 1895 → 1125):
    - Data Readiness & Operations Health Card (~150 lines).
    - Quality Reports Card (~49 lines).
    - Quarters Card (~67 lines).
    - Needs Validation Card (~42 lines).
    - Unknown Manager Type Priority Card (~115 lines).
    - Quarter Detail Drawer (~280 lines).
    - `selectedQuarter` / `quarterFilingStatus` /
      `quarterFilingOffset` state.
    - `quarterDetailQuery` + `selectedQuarterDetail`.
    - `qualityQuery` + `qualityReports` memo.
    - `quartersQuery` + `quarters` memo.
    - `needsValidationQuery`.
    - `workersQuery` + `workers` memo + `hasAvailableWorker`.
    - `operationalHealth` memo + `isLoading` aggregate +
      `readinessThresholds` derivation.
    - `openQuarterDetail` helper.
    - `formatJson` helper (only consumed inside the deleted
      drawer).
    - Lucide icon imports: `CheckCircle2`, `Database`,
      `ShieldAlert`, `UserSearch`, `Loader2`.
    - Helper destructures: `formatPercent`, `freshnessLine`,
      `normalizeQualityReports`, `normalizeQuarters`,
      `normalizeWorkers`, `operationsHealth`.
    - UI primitive imports: `AdminLoadingState`, `DrawerShell`,
      `MetricTile`, all `Select*`, all `Table*`.
  - **Index page kept** (still consumed): `readinessQuery` +
    `readiness` memo (Overview hub Readiness KPI nav card reads
    `readiness.readinessLevel`); `unknownManagerPriorityQuery`
    (Overview hub Oracle's Lens KPI nav card reads
    `items.length`); `edgarRateLimitQuery` + `edgarRateLimit`
    memo (header strip EDGAR mode chip).
  - **Scope refinements** (recorded in spec):
    - SR0: no new backend endpoints.
    - SR1: no frontend tests for the new route.
    - SR2: Manual Controls Card stays on the index page.
    - SR3: Admin Tasks Card stays on the index page.
    - SR4: new route owns its own `runJob` / `pendingJob` /
      `triggerJob` (matches MVP6-06 SR5 duplication pattern).

## Verification Results

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors.
- `docker compose exec web npm run build` → compiled
  successfully. New `/admin/13f/readiness` route 9.85 kB
  (194 kB First Load); index `/admin/13f` dropped from
  12.4 kB → 7.43 kB.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `pytest -q` → **781 passed** (unchanged; no backend
  changes).
