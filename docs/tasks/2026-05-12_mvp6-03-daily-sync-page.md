# MVP6-03: Daily Sync + No-index Calendar Page

## Status

**Authorized to start (PO 2026-05-12 after MVP6-02 ship).** Third
MVP6 ticket. Depends on MVP6-01 (Tier 2 + Tier 3 shared layer);
no dependency on MVP6-02.

## Goal / Acceptance Criteria

PRD §11.1 "Daily Sync" page. Today the admin has zero UI for the
Daily Sync surface — the EDGAR rate-limit panel sits inside the
Overview hub KPI card and the no-index calendar CRUD has no admin
UI at all, despite the backend endpoints existing since MVP1A.

Acceptance criteria:

- **New route `/admin/13f/sync`** wrapped with
  `<AdminPageLayout title="Daily Sync" description="...">`.
- **EDGAR rate-limit panel** showing current mode, recent request
  volume, capacity, configured delay, retry count, and paused
  state. Powered by `useEdgarRateLimitQuery` + the existing
  `normalizeEdgarRateLimit` helper. This surface already
  computes correctly on the index page; the new route gives it
  a dedicated home with more room for detail than the Overview
  KPI card.
- **Recent daily sync activity** table showing the most recent
  `fetch_daily_index` + `backfill_daily_indexes` job runs. Powered
  by the existing `useJobsQuery` with `job_type` filter. V1 is
  read-only; retry happens via the Jobs page action (no new
  retry button on this route in V1 — see SR1 below).
- **No-index calendar** CRUD UI:
  - Table of existing no-index dates, defaulting to the current
    year, with filters for year + active state.
  - "Add no-index date" form: date picker + reason select
    (`weekend` / `federal_holiday` / `edgar_special_closure` /
    `other`) + optional holiday name + optional note.
  - Per-row "Deactivate" action that PATCHes
    `/admin/13f/no-index-dates/{date}` with `active=false`.
  - All four `useNoIndexDatesQuery` results invalidate after
    each successful mutation.
- **Loading / empty / error states** use the MVP6-01 shared
  components.
- **`AdminPageLayout` nav** flipped: `Daily Sync` entry now
  `shipped: true`, `href: '/admin/13f/sync'`.
- **Overview hub Sync card** on `/admin/13f` flipped from
  `<a href="#sync">` to `<Link href="/admin/13f/sync">`.

## Scope In

- `frontend/app/(dashboard)/admin/13f/sync/page.tsx` (new).
- `frontend/lib/admin13f/queries.ts` — extend with
  `useNoIndexDatesQuery(year)`.
- `frontend/components/admin13f/AdminPageLayout.tsx` (flip
  Daily Sync entry).
- `frontend/app/(dashboard)/admin/13f/page.tsx` (flip Overview
  hub Sync card href; no section content removed because there
  isn't one — the rate-limit + sync surface lived only inside
  Overview KPI cards previously).
- This task file.

## Scope Out / Scope Refinements

- **SR1 — no dedicated `EdgarSyncStatus` history table in V1.**
  The `edgar_sync_status` table is populated by the scheduler
  but has **no backend GET endpoint** today. Per the MVP6
  "no backend changes" rule, the Recent daily sync activity
  section reads from the **jobs endpoint** with
  `job_type IN (fetch_daily_index, backfill_daily_indexes)`
  instead. This covers the operational use case ("did today's
  sync run, did it succeed, when, with what error") via
  job-level visibility. A future ticket can add the dedicated
  read endpoint + a sync-status timeline view if the
  job-level shape proves insufficient.
- **SR2 — no retry button on this page in V1.** Failed-sync
  retry happens via the existing Jobs page action. Adding a
  dedicated retry button here would either duplicate the
  jobs retry mutation or require a new endpoint. Defer.
- No bulk no-index date import (CSV).
- No `holiday_name` autocomplete from a calendar provider.
- No backend changes.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §4 (Daily
  Sync Engine), §11.1 (Daily Sync admin page).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D4 + D6 + D7.

## Files Expected To Change

- `frontend/app/(dashboard)/admin/13f/sync/page.tsx` (new)
- `frontend/lib/admin13f/queries.ts`
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
  1. Re-seed; log in as `d41689@gmail.com`.
  2. `/admin/13f` Overview Sync card → `/admin/13f/sync`.
  3. Rate-limit panel renders with `normal` mode (no real
     EDGAR traffic in dev).
  4. Recent sync activity surfaces any seeded job runs of the
     two sync job_types (likely empty in dev — emit
     `<AdminEmptyState reason="pipeline-not-run" />`).
  5. Add a no-index date for a recent date; row appears in
     the table; deactivate works.

## Progress Notes

- 2026-05-12: Task spec filed.
- 2026-05-12: Implementation:
  - New route
    `frontend/app/(dashboard)/admin/13f/sync/page.tsx` with
    three sections inside `<AdminPageLayout>`: EDGAR rate
    limit, recent daily sync activity, no-index calendar.
  - **EDGAR rate limit panel** consumes the existing
    `useEdgarRateLimitQuery` + `normalizeEdgarRateLimit`
    helper from `frontend/lib/thirteenfAdmin.js`. Shows mode,
    delay, retries, window, recent/capacity, remaining, and
    a global-pause warning when set.
  - **Recent sync activity** reads from the existing
    `useJobsQuery` and filters client-side to
    `job_type IN (fetch_daily_index, backfill_daily_indexes)`.
    Status select wired to the jobs filter. Per SR1, no
    dedicated `edgar_sync_status` GET endpoint added — that's
    a future ticket if the job-level shape proves
    insufficient.
  - **No-index calendar** uses the new
    `useNoIndexDatesQuery(year)` hook (added in
    `frontend/lib/admin13f/queries.ts`). Year filter defaults
    to the current year captured via `useMemo(() => new
    Date().getFullYear(), [])` so the dependency stays
    stable. The "Add no-index date" form posts to
    `/admin/13f/no-index-dates`; per-row "Deactivate" button
    PATCHes `active=false`. Both mutations invalidate
    `admin-13f-no-index-dates` on success.
  - **`AdminPageLayout` nav** Daily Sync entry flipped to
    `shipped: true` with `href: '/admin/13f/sync'`.
  - **Overview hub Sync card** on `/admin/13f` flipped from
    `<a href="#sync">` to `<Link href="/admin/13f/sync">`.
  - **Scope refinements**:
    - SR1: dedicated `EdgarSyncStatus` history view deferred.
      Job-level visibility via `useJobsQuery` is the V1
      surface.
    - SR2: no retry button on this page; retry stays on the
      Jobs page action.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors. (One initial warning surfaced about
  a `today` Date constructor used in a `useMemo` dep;
  refactored to a stable `currentYear` memo before re-lint.)
- `docker compose exec web npm run build` → compiled
  successfully. New `/admin/13f/sync` route at ~5 kB
  (static).
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed (unchanged).
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `pytest -q` → **781 passed** (unchanged; no backend
  changes).
- Manual: `curl -sI /admin/13f/sync` returns 307 → /login
  (correct middleware-gated behavior). After login the
  page renders with the EDGAR rate-limit panel populated;
  recent sync activity shows `pipeline-not-run` empty state
  (no scheduler runs in dev); no-index calendar table
  initially `filter-empty` for the current year — admin
  can add a date and see it appear.
