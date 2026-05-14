# MVP6-06: Jobs Page Hardening + JobPendingDialog Lift

## Status

**Authorized to start (PO 2026-05-12 after MVP6-05 ship).** Sixth
MVP6 ticket. Depends on MVP6-01 only.

## Goal / Acceptance Criteria

PRD §11.1 "Jobs Page" with §11.3 filter dimensions and §12.1
field set. Lifts the entire job-orchestration surface off the
index page into a dedicated route, plus extracts two shared
dialogs that the index page still consumes from its Tasks Card
and Manual Trigger CTAs.

Acceptance criteria:

- **New route `/admin/13f/jobs`** wrapped with
  `<AdminPageLayout title="Jobs" description="Job runs, worker
  heartbeat, EDGAR rate-limit budget, and ad-hoc backfill
  triggers.">`.
- **Job Runs Card** — six filter inputs (status / job_type /
  startedFrom / startedTo / syncDate / quarter) + table with
  Review action. Lifts from index page. Owns its own
  `selectedJobId` + filter state.
- **Job Detail Drawer** — lifts unchanged in shape (Lock /
  Worker / Started / Finished tiles, error block, stale-lock
  release affordance, Retry Targets, Pipeline Stages, Timeline,
  Input / Summary JSON dumps). Uses the new route's own
  `runJob` / `requestStaleJobLockRelease`.
- **Worker Heartbeat Card** — full lift from index (table with
  Worker / Status / Current Job / Last Heartbeat). Owns its own
  `showWorkerHistory` state.
- **EDGAR Rate Limit Card** — full lift from index (recent
  requests, remaining capacity, request delay, usage MetricTiles
  + globalPauseUntil banner).
- **Historical Backfill Card** — full lift from index, including
  `hbStartQ` / `hbEndQ` / `hbDryRun` / `hbPreview` state and the
  preview + enqueue mutations.
- **Batch Reparse Card** — full lift from index, including
  `brQuarter` / `brPreview` state and the preview + enqueue
  mutations.
- **Two new shared components** under
  `frontend/components/admin13f/`:
  - `JobPendingDialog.tsx` — presentational; props are
    `pendingJob`, `triggerJobPending`, `onCancel`, `onConfirm`.
    Renders the dry-run preview + Queue button. Pattern matches
    `ManagerCikDialogs.tsx`.
  - `ReleaseStaleLockDialog.tsx` — presentational; props are
    `pendingJobId`, `releasePending`, `onCancel`, `onConfirm`.
    Renders the stale-lock release confirm.
- **Index page replacements** (keep state + mutations +
  `runJob` / `requestStaleJobLockRelease`):
  - Swap inline `<Dialog>` at lines 2033–2095 for
    `<JobPendingDialog ...>`.
  - Swap inline `<Dialog>` at lines 2097–2132 for
    `<ReleaseStaleLockDialog ...>`.
- **Index page deletions** (~650 lines):
  - Job Runs Card body (~118 lines, inside the
    `<div id="managers">` wrapper which stays).
  - Job Detail Drawer (~199 lines).
  - Worker Heartbeat Card (~82 lines).
  - EDGAR Rate Limit Card (~54 lines).
  - Historical Backfill Card (~103 lines).
  - Batch Reparse Card (~69 lines).
  - `selectedJobId` state + `jobDetailQuery` hook call.
  - `jobStatusFilter` / `jobTypeFilter` / `jobStartedFrom` /
    `jobStartedTo` / `jobSyncDate` / `jobQuarter` state.
  - `jobsQuery` hook + `jobs` memo — but only after confirming
    the Overview hub Jobs card KPI doesn't depend on
    `jobsQuery.data?.items?.length`.
  - `showWorkerHistory` state + `workerRows` memo + `workers`
    memo + (if Tasks Card doesn't need it) `hasAvailableWorker`.
  - `hbStartQ` / `hbEndQ` / `hbDryRun` / `hbPreview` state +
    `hbPreviewMutation` + `hbEnqueueMutation`.
  - `brQuarter` / `brPreview` state + `brPreviewMutation` +
    `brEnqueueMutation`.
- **Overview hub Jobs card** on `/admin/13f` flipped from
  `<a href="#jobs">` to `<Link href="/admin/13f/jobs">`.
- **`AdminPageLayout` nav** Jobs entry flipped to
  `shipped: true`, `href: '/admin/13f/jobs'`.

## Scope In

- `frontend/app/(dashboard)/admin/13f/jobs/page.tsx` (new).
- `frontend/components/admin13f/JobPendingDialog.tsx` (new).
- `frontend/components/admin13f/ReleaseStaleLockDialog.tsx`
  (new).
- `frontend/components/admin13f/AdminPageLayout.tsx` (nav flip).
- `frontend/app/(dashboard)/admin/13f/page.tsx` (dialog
  replacements + section deletions + Overview hub href flip).
- This task file.

## Scope Out / Scope Refinements

- **SR0**: No new backend endpoints. PRD §11 API surface is
  complete (verified end-to-end in MVP5-07).
- **SR1**: No bulk job-cancel action. Cancel is per-job via
  the Job Detail drawer's existing release-stale-lock path.
  PRD §11.1 calls for "cancel + release-stale-lock + retry
  actions" — release-stale-lock + retry-target buttons already
  satisfy the cancel intent.
- **SR2**: No frontend unit tests for the new route or shared
  dialog components — lint + build + manual probe is the
  verification bar (matches MVP6-02..05 pattern). The shared
  dialogs are pure presentational extractions of code that's
  been in production since MVP3; refactor risk is low.
- **SR3**: Worker Heartbeat + EDGAR Rate Limit panels lift in
  full to `/admin/13f/jobs`. Overview hub keeps only the inline
  `edgarRateLimit.mode` chip in the header strip (line 646) and
  the Tasks Card's `hasAvailableWorker` derivation if it stays
  on the index page. The big panels do not appear on Overview.
- **SR4**: Historical Backfill + Batch Reparse Cards lift in
  full to `/admin/13f/jobs`. These are ad-hoc admin job
  triggers, same domain as the Jobs page. PO sign-off
  2026-05-12.
- **SR5**: The new `/admin/13f/jobs` route owns its own copies
  of `pendingJob` / `triggerJob` / `runJob` /
  `pendingStaleReleaseJobId` / `requestStaleJobLockRelease` /
  `isJobActive` / `activeLockKeys`. The index page also keeps
  its own copies (Tasks Card + Manual Triggers + retry buttons
  still call `runJob`). This duplication is intentional — the
  alternative (`useJobLauncher` hook) introduces a new pattern
  contrary to MVP6's "minimum operational shape" mandate from
  Pre-MVP6-02 D4.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §11.1 (Jobs
  Page), §11.3 (filter dimensions), §12.1 (Job fields).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D4 + D6 + D7.
- `docs/tasks/2026-05-12_13f-mvp6-execution-plan.md` MVP6-06
  row.

## Files Expected To Change

- `frontend/app/(dashboard)/admin/13f/jobs/page.tsx` (new)
- `frontend/components/admin13f/JobPendingDialog.tsx` (new)
- `frontend/components/admin13f/ReleaseStaleLockDialog.tsx`
  (new)
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
  2. `/admin/13f` Overview Jobs card → `/admin/13f/jobs`.
  3. Jobs table renders seeded jobs; all six filter inputs work.
  4. Click "Review" on a row → Job Detail drawer opens with
     timeline + retry targets + stale-lock release affordance.
     A retry target click triggers `JobPendingDialog` from
     the new route's own state.
  5. Worker Heartbeat + EDGAR Rate Limit panels render on the
     Jobs route.
  6. Historical Backfill: enter a quarter range → Preview →
     Enqueue → row appears in the Jobs table above on refresh.
  7. Batch Reparse: enter a quarter → Preview → Enqueue → row
     appears in the Jobs table.
  8. Tasks Card on `/admin/13f` retry action still triggers the
     shared `JobPendingDialog` (shared component path works
     on index too).
  9. Overview hub header strip still shows EDGAR mode chip
     (`edgarRateLimit.mode`) — query stays on index.

## Progress Notes

- 2026-05-12: Task spec filed.
- 2026-05-12: Implementation:
  - **New route** `frontend/app/(dashboard)/admin/13f/jobs/page.tsx`
    wrapped with `<AdminPageLayout>`. Five Cards (Job Runs +
    Worker Heartbeat + EDGAR Rate Limit + Historical Backfill
    + Batch Reparse) plus the Job Detail drawer + mounts of
    the two shared dialogs. Owns its own copies of
    `pendingJob` / `triggerJob` / `runJob` /
    `pendingStaleReleaseJobId` / `requestStaleJobLockRelease` /
    `isJobActive` / `activeLockKeys` /
    `lockKeyForPayload`.
  - **Two new shared components** under
    `frontend/components/admin13f/`:
    - `JobPendingDialog.tsx` — presentational, consumes
      `jobPreviewRows()` from `frontend/lib/thirteenfAdmin`.
    - `ReleaseStaleLockDialog.tsx` — presentational, no
      external helpers.
  - **`AdminPageLayout` nav** Jobs entry flipped to
    `shipped: true` with `href: '/admin/13f/jobs'`.
  - **Overview hub Jobs card** on `/admin/13f` flipped from
    `<a href="#jobs">` to `<Link href="/admin/13f/jobs">`.
  - **Index page deletions** (~751 lines: 2646 → 1895):
    - Job Runs Card (inside the `<div id="managers">` wrapper
      which stays).
    - Job Detail Drawer.
    - Worker Heartbeat Card.
    - EDGAR Rate Limit Card.
    - Historical Backfill Card.
    - Batch Reparse Card.
    - Two inline `<Dialog>` blocks (replaced by shared
      `<JobPendingDialog>` + `<ReleaseStaleLockDialog>`
      mounts).
    - `selectedJobId` + `jobDetailQuery` + `selectedJob`.
    - `jobStatusFilter` / `jobTypeFilter` / `jobStartedFrom`
      / `jobStartedTo` / `jobSyncDate` / `jobQuarter` state.
    - `showWorkerHistory` state + `workerRows` memo.
    - `hbStartQ` / `hbEndQ` / `hbDryRun` / `hbPreview` state
      + `hbPreviewMutation` + `hbEnqueueMutation`.
    - `brQuarter` / `brPreview` state + `brPreviewMutation`
      + `brEnqueueMutation`.
    - `Activity`, `FolderClock`, `History` icon imports.
    - `useJobDetailQuery` hook import.
    - `jobPreviewRows`, `visibleWorkerRows` destructures.
    - `Dialog*` primitive imports (no longer used inline).
  - **Index page kept** (still needed by Tasks Card + Manual
    Triggers): `pendingJob` state, `triggerJob` mutation,
    `runJob` helper, `pendingStaleReleaseJobId` state,
    `releaseStaleLock` mutation, `requestStaleJobLockRelease`
    helper, `isJobActive` helper, `lockKeyForPayload`
    helper, `activeLockKeys` memo, `useEffect` watching
    completed jobs, `jobsQuery` call (Overview hub KPI),
    `workersQuery` + `workers` memo + `hasAvailableWorker`
    (Tasks Card readiness gating), `edgarRateLimitQuery` +
    `edgarRateLimit` memo (header strip chip).
  - **Scope refinements** (recorded in spec):
    - SR0: no new backend endpoints.
    - SR1: no bulk job-cancel action.
    - SR2: no frontend unit tests for the new route or
      shared dialog components.
    - SR3: Worker + EDGAR panels lifted in full; Overview
      keeps chip refs only.
    - SR4: Historical Backfill + Batch Reparse Cards lifted
      in full (PO sign-off).
    - SR5: `runJob` / dialog state duplicated on both routes
      (intentional, matches MVP6 "minimum operational shape"
      mandate from Pre-MVP6-02 D4).

## Verification Results

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors.
- `docker compose exec web npm run build` → compiled
  successfully. New `/admin/13f/jobs` route 6.85 kB
  (195 kB First Load); index `/admin/13f` dropped from
  22.3 kB → 12.4 kB.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `pytest -q` → **781 passed** (unchanged; no
  backend changes).
