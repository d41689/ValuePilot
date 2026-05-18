# MVP6-04: Filings + Amendments Page

## Status

**Authorized to start (PO 2026-05-12 after MVP6-03 ship).** Fourth
MVP6 ticket. Depends on MVP6-01 only.

## Goal / Acceptance Criteria

PRD §11.1 "Filings" page. Today the Filings table + Amendment
Accessions table live as two large Cards on the index page with
side-drawer detail views.

Acceptance criteria:

- **New route `/admin/13f/filings`** wrapped with
  `<AdminPageLayout title="Filings" description="...">`.
- **Filings Card** — table with parse_status filter (already
  supported by `useFilingsQuery`). Click "Parse runs" on a row
  opens the parse-run history drawer. Optional V1 add: a
  "Reparse" button on the drawer header that POSTs
  `/admin/13f/filings/{accession_no}/reparse` directly (no
  preview dialog needed since the endpoint is a direct
  one-shot per `thirteenf_holdings_ingest.reparse_accession`).
- **Amendment Accessions Card** — table with pending count
  badges + per-row Review action that opens the amendment
  detail drawer. Drawer surfaces the amendment's
  `recommendedJob` (if any) plus a Resolve action that POSTs
  `/admin/13f/amendments/{accession_no}/resolve`.
- **DrawerShell** primitives reused from
  `@/components/admin13f/Admin13FPrimitives` — same component
  the index page used.
- **`AdminPageLayout` nav** flipped: `Filings` entry now
  `shipped: true`, `href: '/admin/13f/filings'`.
- **Overview hub Filings card** on `/admin/13f` flipped from
  `<a href="#filings">` to `<Link href="/admin/13f/filings">`.
- **Index page deletions**:
  - Filings Card (~106 lines).
  - Amendment Accessions Card (~102 lines).
  - Parse runs drawer (~80 lines).
  - Amendment detail drawer (~96 lines).
  - `selectedFilingAccession` + `selectedAmendmentAccession`
    state vars.
  - Whatever `parseRunsQuery` + `amendmentDetailQuery` usage
    remains only feeds the now-deleted drawers.

## Scope In

- `frontend/app/(dashboard)/admin/13f/filings/page.tsx` (new).
- `frontend/components/admin13f/AdminPageLayout.tsx` (nav
  flip).
- `frontend/app/(dashboard)/admin/13f/page.tsx` (section +
  drawer + state removal; Overview hub card href flip).
- This task file.

## Scope Out / Scope Refinements

- **SR1 — no JobPendingDialog reuse on the new route.** The
  amendment "Reprocess" button on the index page uses
  `runJob` which opens the preview-then-confirm
  `JobPendingDialog` (deferred to MVP6-06 lift per MVP6-01
  SR1). The new route uses direct POST mutations for the
  immediately-actionable surfaces (Reparse + Resolve) so it
  doesn't need the dialog. For "trigger a backfill job"
  flows the admin still uses the index page's Historical
  Backfill / Batch Reparse Cards.
- **SR2 — no quarter filter in V1.** D7 listed quarter as a
  filter dimension but the existing `/admin/13f/filings`
  endpoint doesn't support a `report_quarter` param. Adding
  a quarter filter requires either a backend change (off
  limits per MVP6 plan) or client-side filtering of the
  paginated 50-row response (lossy). Defer to a future
  ticket that adds the backend param.
- **No new endpoints.** PRD §11 API surface is complete for
  filings + amendments.
- **No frontend tests for the new page** — lint + build +
  manual probe is the verification bar (matches MVP6-02 /
  MVP6-03 pattern).

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §6
  (Filings + Amendment Policy), §11.1 (Filings admin page).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D4 + D6 + D7.

## Files Expected To Change

- `frontend/app/(dashboard)/admin/13f/filings/page.tsx` (new)
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
  2. `/admin/13f` Overview Filings card → `/admin/13f/filings`.
  3. Filings table shows seeded filings (64 from devseed
     across 2 quarters); parse_status filter works.
  4. Click "Parse runs" — drawer opens with the parse-runs
     history.
  5. Amendments table shows seeded amendment-pending row
     (one manager in current quarter).
  6. Click "Review" on an amendment — drawer opens; Resolve
     action posts; row updates on refresh.

## Progress Notes

- 2026-05-12: Task spec filed.
- 2026-05-12: Implementation:
  - New route
    `frontend/app/(dashboard)/admin/13f/filings/page.tsx`
    wrapped with `<AdminPageLayout>`. Two Cards (Filings +
    Amendment Accessions) plus two side drawers (parse-run
    history + amendment detail), all reusing existing
    primitives (`DrawerShell`, the four shared admin13f
    components, the `useFilingsQuery` /
    `useAmendmentsQuery` / `usePendingAmendmentsQuery` /
    `useParseRunsQuery` / `useAmendmentDetailQuery`
    hooks).
  - **Reparse** wired as a direct
    `POST /admin/13f/filings/{accession}/reparse` mutation
    inside the parse-runs drawer; invalidates the filings +
    parse-runs queries.
  - **Resolve** wired as a direct
    `POST /admin/13f/amendments/{accession}/resolve`
    mutation inside the amendment-detail drawer with an
    action select (`mark_resolved` / `mark_failed`) +
    optional note; invalidates the amendments + pending +
    filings + detail queries on success.
  - **`AdminPageLayout` nav** Filings entry flipped to
    `shipped: true` with `href: '/admin/13f/filings'`.
  - **Overview hub Filings card** on `/admin/13f` flipped
    from `<a href="#filings">` to
    `<Link href="/admin/13f/filings">`.
  - **Index page deletions**:
    - Filings Card (~106 lines).
    - Amendment Accessions Card (~102 lines).
    - Parse-runs drawer + amendment detail drawer
      (~180 lines combined).
    - `selectedFilingAccession` /
      `selectedAmendmentAccession` /
      `filingParseStatus` state vars.
    - `amendments` / `pendingAmendments` /
      `pendingAmendmentGroups` / `adminFilings` /
      `parseRuns` / `selectedAmendment` memos.
    - `amendmentsQuery` + `filingsQuery` hook calls. The
      underlying `pendingAmendmentsQuery` stays because the
      Overview hub Filings card KPI still reads its
      `items.length`.
    - Unused imports: `FileText`, `useAmendmentDetailQuery`,
      `useAmendmentsQuery`, `useFilingsQuery`,
      `useParseRunsQuery`, `normalizeAdminFilings`,
      `normalizeAmendments`, `normalizeParseRuns`.
    - Removed `amendmentsQuery.isLoading` + `filingsQuery.isLoading`
      from the page-level `isLoading` aggregate.
  - **Scope refinements** (recorded in spec):
    - SR1: no JobPendingDialog reuse on the new route;
      Reparse + Resolve are direct POST mutations. The
      "Reprocess via job preview" flow stays on the index
      page until MVP6-06 lifts the dialog.
    - SR2: no quarter filter in V1; backend
      `/admin/13f/filings` doesn't support a
      `report_quarter` param. Defer.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors.
- `docker compose exec web npm run build` → compiled
  successfully. New `/admin/13f/filings` route ~8 kB.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `pytest -q` → **781 passed** (unchanged; no
  backend changes).
- Manual: `curl -sI /admin/13f/filings` returns 307 →
  /login (correct middleware-gated behavior). After
  login + reseed, the filings table renders 64 seeded
  filings (status filter works); amendments table shows
  the one seeded amendment-pending row (devseed
  manager #0 in 2026-Q1); Parse runs + Amendment detail
  drawers open with their respective queries; Reparse +
  Resolve actions wired through.
