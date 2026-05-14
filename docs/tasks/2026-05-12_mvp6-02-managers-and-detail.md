# MVP6-02: Managers Page + Manager Detail Page

## Status

**Authorized to start (PO 2026-05-12 after MVP6-01 ship).** Second
MVP6 ticket. Depends on MVP6-01 (Tier 2 + Tier 3 shared layer).

## Goal / Acceptance Criteria

Move the manager management surface from the `/admin/13f` index
page's `#managers` section into two dedicated routes, and finally
honor the MVP4-07b admin priority Card's promise of a real deep
link.

Acceptance criteria:

- **New route `/admin/13f/managers`** (managers list):
  - Wrapped with `<AdminPageLayout title="Managers" description="...">`.
  - Same table content as the current index-page `#managers`
    section (Name / CIK / Manager Type / Candidate Evidence /
    Latest Audit / Status), with the Edit button on every row
    that opens the lifted `<ManagerTypeEditorDialog>`.
  - One new filter at the top: `match_status` select
    (`all` / `confirmed` / `candidate` / `needs_review` /
    `revoked` / `rejected`). V1 keeps the existing 100-row
    pagination cap; deeper filtering is a follow-up.
  - Each manager row's name links to
    `/admin/13f/managers/{id}` (real route — replaces the
    MVP5-05 anchor fallback that lived at the index page).
- **New route `/admin/13f/managers/[id]`** (manager detail):
  - Wrapped with `<AdminPageLayout title="{manager.legal_name}" description="CIK {manager.cik} · ...">`.
  - Header KPI row: status badge, match_status badge,
    manager_type badge with inline "Edit" button (opens the
    same `<ManagerTypeEditorDialog>`).
  - "manager_type history" card: most recent entries from
    `GET /admin/13f/managers/{id}/manager-type-events`
    (MVP5-05).
  - "CIK review history" card: most recent entries from
    `GET /admin/13f/managers/{id}/cik-review-events`.
  - Loading via `<AdminLoadingState>`, errors via
    `<AdminErrorState>`, empty audit logs via
    `<AdminEmptyState reason="not-seeded">` (for fresh
    managers with no history yet).
  - Manager metadata sourced client-side from the existing
    `useManagersQuery()` list by filtering on `id` — V1 does
    not need a `GET /managers/{id}` backend endpoint.
- **SR1 follow-through — lift `ManagerTypeEditorDialog`:**
  - New `frontend/components/admin13f/ManagerTypeEditorDialog.tsx`.
  - Props: open / managerType editor state /
    managerTypeDraft + setter / managerTypeNote + setter /
    onClose / onSave / isPending.
  - The inline JSX currently in the index page (`page.tsx`
    lines ~2762..2847) becomes the body of this component;
    the mutation `managerTypeMutation` stays where the
    caller is (each new route owns its own mutation
    instance).
- **Index page `/admin/13f` updates:**
  - The entire `<div id="managers" ...>` section block
    (~150 lines) is replaced with a small Card that links
    out: "Manager management lives on the dedicated Managers
    page" → `<Link href="/admin/13f/managers">Open Managers
    page</Link>`. The index page no longer carries the
    full managers table.
  - The MVP4-07b Unknown Manager Priority Card row's
    manager-name `<a href="#manager-row-{id}">` flips to a
    Next.js `<Link href="/admin/13f/managers/{manager_id}">`.
  - The inline `ManagerTypeEditorDialog` JSX is replaced
    with an import of the lifted component. The index page
    keeps the dialog because the existing per-row "Edit"
    buttons currently sit in the managers section — wait,
    those buttons are part of the section being moved.
    **Outcome:** the index page no longer needs the dialog
    at all; remove the dialog state + mutation from the
    index page entirely. Both new routes wire their own
    dialog state + mutation.
- **`AdminPageLayout` nav update:**
  - Flip the `Managers` entry: `shipped: true`,
    `href: '/admin/13f/managers'`. The other six remain
    anchor fallbacks until their routes ship.

## Scope In

- `frontend/components/admin13f/ManagerTypeEditorDialog.tsx`
  (new — lifted from index page per SR1).
- `frontend/lib/admin13f/queries.ts` (extend with
  `useManagerCikReviewEventsQuery` +
  `useManagerTypeEventsQuery`).
- `frontend/app/(dashboard)/admin/13f/managers/page.tsx`
  (new — list).
- `frontend/app/(dashboard)/admin/13f/managers/[id]/page.tsx`
  (new — detail).
- `frontend/components/admin13f/AdminPageLayout.tsx` (flip
  Managers entry to shipped).
- `frontend/app/(dashboard)/admin/13f/page.tsx`:
  - Remove the `<div id="managers">` section + its
    ManagerTypeEditorDialog usage + dialog state /
    mutation + the openManagerTypeEditor helper.
  - Replace with a small navigation Card.
  - Flip MVP4-07b priority Card row to use `<Link>` to
    `/admin/13f/managers/{id}`.
  - Drop the resulting unused imports.
- This task file.

## Scope Out

- **Bulk import UI.** API
  (`POST /admin/13f/managers/bulk-import`) exists; UI is a
  follow-up if PO asks.
- **Per-manager backfill controls on the detail page.**
  Backfill preview + enqueue APIs exist; surface lives on
  the index page Historical Backfill Card today. Not in
  V1; revisit if the manager detail use case demands it.
- **EFTS CIK search UI.** PRD §3.5 calls out the search
  endpoint; no UI search box yet. Out of V1 scope.
- **Deactivate / revoke-CIK action buttons on the detail
  page.** APIs exist; for V1 the detail page is mostly
  read-only with manager_type as the one editable surface.
  Other actions stay on the index page's CIK review flow
  (or migrate in a follow-up).
- **No backend changes.**
- **No frontend tests for the new pages.** Page-level
  component tests are deferred to a future ticket; lint +
  build + manual probe is the verification bar for MVP6-02
  (matches the MVP5-05 pattern).

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §3 (Manager
  Management Center), §11.1 (Managers admin page).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D1, D4, D6, D7.
- `docs/tasks/2026-05-12_mvp6-01-overview-hub-layout-shell.md`
  SR1 (dialog deferral now realized here).

## Files Expected To Change

- `frontend/app/(dashboard)/admin/13f/managers/page.tsx` (new)
- `frontend/app/(dashboard)/admin/13f/managers/[id]/page.tsx`
  (new)
- `frontend/components/admin13f/ManagerTypeEditorDialog.tsx`
  (new)
- `frontend/components/admin13f/AdminPageLayout.tsx` (nav flip)
- `frontend/lib/admin13f/queries.ts` (two new hooks)
- `frontend/app/(dashboard)/admin/13f/page.tsx` (section
  removal + priority Card link flip + unused-import cleanup)
- This task file.

## Test Plan

- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec web node --test lib/oraclesLens.test.js`
  (regression — 17 passing)
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `docker compose exec api pytest -q` (regression — 781
  passing)
- Manual probe:
  1. Re-seed and log in as `d41689@gmail.com`.
  2. `/admin/13f` Overview hub shows Managers card linking
     to `/admin/13f/managers`.
  3. `/admin/13f/managers` renders the table with all 32
     seeded managers + match_status filter.
  4. Clicking a manager name lands on
     `/admin/13f/managers/{id}` with metadata + audit logs.
  5. Editing manager_type from the detail page toasts
     success + invalidates managers list + the Unknown
     Manager Priority Card.
  6. Clicking a name in the MVP4-07b priority Card on
     `/admin/13f` lands directly on the manager detail
     route (not an anchor).

## Progress Notes

- 2026-05-12: Task spec filed. SR1 dialog lift moves here as
  promised in MVP6-01.
- 2026-05-12: Implementation:
  - **SR1 realized**: lifted `ManagerTypeEditorDialog` from
    the index page's inline JSX into
    `frontend/components/admin13f/ManagerTypeEditorDialog.tsx`.
    Self-contained component with explicit prop interface
    (`editor`, `setEditor`, `draft`, `setDraft`, `note`,
    `setNote`, `onSave`, `isPending`). The
    `MANAGER_TYPE_OPTIONS` const moved into the same file
    (the only consumer is the dialog itself).
  - **New route `/admin/13f/managers`** built with
    `<AdminPageLayout title="Managers" ...>`. Table mirrors
    the previous inline columns (Name / CIK / Manager Type /
    Match Status / Status) plus a `match_status` filter at
    the top. Manager names link to
    `/admin/13f/managers/[id]`. The Edit button on every row
    opens the lifted dialog; the mutation invalidates
    `admin-13f-managers`,
    `admin-13f-oracles-lens-unknown-manager-priority`, and
    `admin-13f-manager-type-events`.
  - **New route `/admin/13f/managers/[id]`** built with
    `<AdminPageLayout title={legalName} ...>`. Renders:
    - Manager profile card (canonical_name, EDGAR legal
      name, source, confidence, superinvestor / featured
      flags, optional review note).
    - "Edit manager_type" button opens the same lifted
      dialog.
    - "Manager_type history" card from
      `useManagerTypeEventsQuery` (MVP5-05 audit table).
    - "CIK review history" card from
      `useManagerCikReviewEventsQuery`.
    - Manager metadata sourced client-side from
      `useManagersQuery()`; missing manager renders
      `<AdminEmptyState reason="not-seeded">` with a back
      link. Loading via `<AdminLoadingState>`, errors via
      `<AdminErrorState>` with retry.
    - Next.js 15 `params` Promise handled via `use(params)`.
  - **Two new query hooks** added to
    `frontend/lib/admin13f/queries.ts`:
    `useManagerCikReviewEventsQuery(managerId, limit)` +
    `useManagerTypeEventsQuery(managerId, limit)`, both
    gated by `enabled: managerId !== null`.
  - **AdminPageLayout nav** flipped: Managers entry now
    `shipped: true` with `href: '/admin/13f/managers'`.
    Active-route match-check expanded so a sub-route like
    `/admin/13f/managers/123` still highlights "Managers".
  - **Index page `/admin/13f` updates:**
    - Managers Card (inside the `<div id="managers">`
      container) replaced with a small "Manager management
      lives on the dedicated Managers page" link Card. The
      sibling Job Runs Card inside the same container was
      preserved untouched — earlier surgery overshot and
      removed Job Runs by accident; reverted and re-cut more
      carefully.
    - Inline `<Dialog open={managerTypeEditor !== null}>`
      JSX deleted (the lifted component takes over for the
      new routes).
    - `managerTypeEditor` / `managerTypeDraft` /
      `managerTypeNote` state + `managerTypeMutation` +
      `openManagerTypeEditor` helper removed from the index
      page.
    - `MANAGER_TYPE_OPTIONS` const removed (moved to the
      lifted dialog).
    - `Textarea` import removed (only used in the deleted
      dialog).
    - `managers = useMemo(...)` removed (only consumed in
      the deleted section; Overview hub reads
      `managersQuery.data?.items?.length` directly).
    - Four `handle{Confirm/Reject/Revoke/Retry}Manager`
      helpers removed (the only callers were the deleted
      managers table; their state +
      `submit*/close*Dialog` helpers + the
      `<ManagerCikDialogs>` render remain wired so the CIK
      review flow can be re-triggered from the new Managers
      page in a follow-up without re-plumbing).
    - `managerCikReviewDefaults` and `prioritizeManagersForReview`
      imports removed.
    - Overview hub Managers card flipped from
      `<a href="#managers">` to `<Link href="/admin/13f/managers">`.
    - MVP4-07b priority Card row flipped from
      `<a href="#manager-row-{id}">` to
      `<Link href="/admin/13f/managers/{id}">`. The
      MVP6-01 anchor placeholder is now a real route.
  - **`Link` import** added to the index page.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors.
- `docker compose exec web npm run build` → compiled
  successfully. Routes:
  `/admin/13f` (≈25 kB) + new `/admin/13f/managers`
  (≈4 kB) + new `/admin/13f/managers/[id]` (≈5 kB,
  dynamic).
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed (unchanged).
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `pytest -q` → **781 passed** (unchanged; no backend
  changes).
- Manual: `curl -sI` on both new routes returns
  `HTTP 307 → /login` (correct middleware-gated behavior).
  After login as `d41689@gmail.com` with the seeder
  populated, `/admin/13f` Overview card "Managers" link
  navigates to `/admin/13f/managers` (32 managers shown,
  filter works); clicking a name lands on the detail route
  with metadata + audit logs; the MVP4-07b priority Card on
  the index also deep-links to the manager detail route.
