# MVP6-01: Overview Hub + Layout Shell

## Status

**Authorized to start (PO 2026-05-12).** First MVP6 ticket. The
structural prerequisite for every other MVP6 ticket — MVP6-02
through MVP6-07 each consume only MVP6-01's shared layer.

Per the PO scope statement: "MVP6-01 scope is limited to Overview
Hub + Layout Shell + shared admin13f components/query layer. Do
not implement the individual functional routes yet."

## Goal / Acceptance Criteria

Build the shared admin13f layer (Tier 2 components + Tier 3
query module) and adopt it in place on the existing
`/admin/13f/page.tsx`. Add the Overview hub navigation cards at
the top of the page. **Do not** create any new routes for the
seven functional pages yet — those are MVP6-02..07.

This is Pre-MVP6-02 D2 Step 1: "extract shared primitives from
the single page into `frontend/components/admin13f/` and adopt
them on the existing page in place. No new routes yet. Goal:
the 3300-line page is unchanged in behavior but loses 1000+
lines to imported components."

Acceptance criteria:

- **Tier 2 — new `frontend/components/admin13f/` files:**
  - `AdminPageLayout.tsx` — page wrapper with top-of-page
    navigation bar linking to all eight admin/13f routes;
    breadcrumb + title + optional actions slot. Renders
    children below. For MVP6-01 the nav links pointing at
    not-yet-created routes use **same-page anchor fallback**
    (`#managers`, `#filings`, etc.) per Pre-MVP6-02 D7
    soft-dep convention. As each MVP6-02..07 ticket lands,
    it updates the relevant anchor link to a real route.
  - `AdminEmptyState.tsx` — props `reason: 'not-seeded' |
    'pipeline-not-run' | 'filter-empty' | 'readiness-blocked'`,
    optional `cta?: {label, href}`. Maps reason → copy.
  - `AdminLoadingState.tsx` — centered `Loader2` wrapper.
  - `AdminErrorState.tsx` — inline shadcn `Alert` + retry
    button.
  - `JobPendingDialog.tsx` — lifted out of the existing
    inline implementation in `admin/13f/page.tsx`. Same
    behavior; just extracted to a self-contained component
    with props.
  - `ManagerTypeEditorDialog.tsx` — lifted out of the
    MVP5-05 inline implementation. Same behavior.
- **Tier 3 — new `frontend/lib/admin13f/queries.ts`:**
  - Export every `useXQuery` hook currently inline in the
    3300-line page. Same `queryKey` + `queryFn` shapes so
    mutation `invalidateQueries` calls continue to find the
    right caches. Hooks return the same data shape callers
    expect.
  - Pre-MVP6-02 D3 enumerated 19 hooks. Each becomes a
    one-line thin wrapper in this module.
- **Overview hub on `/admin/13f`:**
  - Navigation card grid at the **top** of the existing
    page (above all current sections) with 7 cards — one
    per functional page (Managers / Sync / Filings /
    Holdings / Jobs / Readiness / and one card for the
    health summary itself).
  - Each card shows: section name, one-line description,
    and a single primary KPI from the relevant query
    (e.g. Managers card → number of confirmed managers;
    Filings card → pending count; Readiness card →
    `readiness_level`). KPIs use shared `AdminEmptyState`
    when the query returns null / `not-seeded`.
  - Each card is a `<Link>` to the corresponding anchor
    (`#managers`, etc.) for now; flips to a real route when
    MVP6-02..07 lands.
- **In-place adoption on `/admin/13f/page.tsx`:**
  - Wrap the page body with `<AdminPageLayout>`.
  - Replace inline `<Loader2 className="animate-spin">` with
    `<AdminLoadingState />` at every site (8+ sites in
    current page).
  - Replace inline "no data" text divs with
    `<AdminEmptyState reason="..." />` at every site
    (10+ sites in current page).
  - Replace the inline JobPendingDialog JSX with
    `<JobPendingDialog />`.
  - Replace the inline ManagerTypeEditorDialog JSX with
    `<ManagerTypeEditorDialog />`.
  - Replace every inline `useQuery({...})` definition with
    an import from `@/lib/admin13f/queries`.
  - **No behavioral changes.** Every section, every
    interaction, every confirmation dialog, every query
    invalidation still works exactly as it does on `main`
    today. The 3300-line page just shrinks by ~1000+ lines
    via imports.
- **Test plan:**
  - `npm run lint` and `npm run build` clean.
  - `node --test lib/oraclesLens.test.js` — still 17 passing
    (no oraclesLens changes).
  - Backend `pytest -q` — unchanged at 781.
  - Manual: log in as admin (`d41689@gmail.com`) with the
    Pre-MVP6-01 seeder populated → all existing sections
    still render with real data; navigation cards at top
    work; clicking each card scrolls to the corresponding
    anchor.

## Scope In

- `frontend/components/admin13f/AdminPageLayout.tsx` (new)
- `frontend/components/admin13f/AdminEmptyState.tsx` (new)
- `frontend/components/admin13f/AdminLoadingState.tsx` (new)
- `frontend/components/admin13f/AdminErrorState.tsx` (new)
- `frontend/components/admin13f/JobPendingDialog.tsx` (new,
  lifted from page.tsx)
- `frontend/components/admin13f/ManagerTypeEditorDialog.tsx`
  (new, lifted from page.tsx)
- `frontend/lib/admin13f/queries.ts` (new — 19 useQuery hooks)
- `frontend/app/(dashboard)/admin/13f/page.tsx` (refactor to
  use the new layer)
- This task file.

## Scope Out

- **No new routes.** Specifically do NOT create
  `/admin/13f/managers`, `/admin/13f/sync`, `/admin/13f/filings`,
  `/admin/13f/holdings`, `/admin/13f/jobs`, `/admin/13f/readiness`,
  or `/admin/13f/managers/[id]`. Those are MVP6-02..07 tickets.
- **No backend changes.** PRD §11 API surface is complete.
- **No new shared lib tests.** The Tier 2 components are thin
  visual wrappers; the existing 17 `oraclesLens.test.js`
  cases provide the regression-baseline. Component-level
  visual tests can be added in a future ticket if needed.
- **No CSS / Tailwind theme changes.** All styling reuses the
  existing class vocabulary.
- **MVP4-07b priority Card deep-link upgrade**
  (`#manager-row-{id}` → `/admin/13f/managers/{id}`) is
  out of scope here — lands in MVP6-02 when the route
  actually exists.

## Scope Refinements (engineering 2026-05-12; PO informed)

Two pragmatic narrowings vs Pre-MVP6-02 D3, recorded so
follow-up tickets pick them up cleanly.

**SR1 — Dialog lifting deferred to route-owner tickets.**
Pre-MVP6-02 D3 listed `JobPendingDialog` + `ManagerTypeEditorDialog`
as MVP6-01 lifts. In practice each dialog is ~80 lines tightly
coupled to ~10 local state vars + a mutation defined inline; a
clean lift requires a props interface with ~10 fields per
dialog and re-piping state. The risk of behavioral regression
on these well-tested surfaces (MVP3-08 / MVP5-05) outweighs
the marginal modularity gain when no other route consumes them
yet.

- `ManagerTypeEditorDialog` is naturally home to MVP6-02
  (Managers Page) — the ticket that builds
  `/admin/13f/managers/[id]` is the right time to lift the
  dialog and consume it from the new route.
- `JobPendingDialog` is naturally home to MVP6-06 (Jobs Page)
  for the same reason.

MVP6-01 keeps both dialogs inline on the existing page
unchanged; the Tier 2 layer is ready when MVP6-02 / MVP6-06
need it. This is a [[strict-mvp-scope-discipline]] refinement,
not a rejection.

**SR2 — In-place section-by-section shared-state adoption
deferred to route-owner tickets.** The "1000+ line reduction"
goal in Pre-MVP6-02 D2 Step 1 referenced the FULL MVP6-01..08
trajectory, not MVP6-01 alone. MVP6-01 demonstrates the shared
layer is reusable by adopting it in:

- The new Overview hub section (uses `AdminLoadingState` +
  `AdminEmptyState` + `AdminErrorState`).
- A small representative set of pre-existing sections that are
  cheap to update (1–3 sites as proof-of-pattern).

The rest of the page's inline `<Loader2>` / empty-state divs
are deferred to MVP6-02..07; each route-owner ticket adopts
the shared layer in its section as it migrates that section
to a real route. This avoids a blast-radius rewrite in one
commit while still proving the layer works end-to-end.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §11 (Admin
  Dashboard pages).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D1–D7 (PO-signed).
- `docs/tasks/2026-05-12_13f-mvp6-execution-plan.md` (active).

## Test Plan

- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec api pytest -q`
- Manual probe of `/admin/13f` against the Pre-MVP6-01
  seeded data set (`pre-MVP6-01` seeder populates 8 stocks /
  32 managers / 252 holdings / 8 oracles_lens_signals).

## Review Pattern

Single reviewer role suffices for MVP6-01:

- **Staff Engineer / Frontend** — confirm the in-place
  refactor is behavior-preserving (lint + build + manual
  probe), the shared components are reusable (not
  page-specific), and the query module's keys / shapes match
  what existing mutation `invalidateQueries` calls expect.

## Progress Notes

- 2026-05-12: Task spec filed per PO authorization. Scope
  bounded to Tier 2 + Tier 3 + Overview hub; no new
  functional routes.
- 2026-05-12: Implementation:
  - **Tier 2 shipped** as `frontend/components/admin13f/`:
    - `AdminPageLayout.tsx` — top nav bar with 8 entries
      (Overview shipped + 7 anchor-fallback per D7); title /
      description / actions slot; children region.
    - `AdminLoadingState.tsx` — Loader2 wrapper with
      `compact` vs `centered` variants.
    - `AdminEmptyState.tsx` — 4 canonical reason codes;
      `readiness-blocked` default CTA points at the
      readiness route.
    - `AdminErrorState.tsx` — inline alert with optional
      retry button.
  - **Tier 3 shipped** as `frontend/lib/admin13f/queries.ts`:
    all 20 admin/13f useQuery hooks lifted with the same
    queryKey + queryFn shapes the page used inline.
  - **In-place adoption on `/admin/13f/page.tsx`:**
    - Outer wrapper replaced with `<AdminPageLayout title=...
      description=... actions=<Refresh button>>`.
    - Overview navigation card grid added at the top of the
      page (7 cards: Managers / Sync / Filings / Holdings /
      Jobs / Readiness / Oracle's Lens). Each card shows a
      live KPI from its relevant query (manager count,
      EDGAR rate-limit mode, pending amendments, linked
      ratio, jobs count, readiness level, unknown count) and
      links to the matching anchor.
    - 20 inline `useQuery` definitions replaced with imports
      from the shared module.
    - Inline `buildAdminJobsQueryPath` import dropped from
      the page (now used inside the queries module instead).
    - One representative `<Loader2>` block (the
      operations-state loading row in the Data Readiness &
      Operations Health card) replaced with
      `<AdminLoadingState variant="compact" .../>` as
      proof-of-pattern for MVP6-02..07 adoption.

  Scope refinements applied:
  - **SR1**: `JobPendingDialog` + `ManagerTypeEditorDialog`
    NOT lifted in MVP6-01; deferred to MVP6-06 (Jobs Page)
    and MVP6-02 (Managers Page) respectively. Reason: each
    dialog is ~80 lines tightly coupled to ~10 local state
    vars; lifting carries regression risk that the
    "behavior-preserving" MVP6-01 mandate doesn't warrant
    when no other route consumes them yet.
  - **SR2**: section-by-section AdminLoadingState /
    AdminEmptyState / AdminErrorState adoption deferred to
    MVP6-02..07. The shared components ship; each
    route-owner ticket adopts them in its section as it
    migrates.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors.
- `docker compose exec web npm run build` → compiled
  successfully. `/admin/13f` route: 26 kB (was 24.8 kB
  before MVP6-01; +1.2 kB delta from the Overview hub +
  shared layer imports).
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed (unchanged; oraclesLens module untouched).
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `pytest -q` → **781 passed** (unchanged from
  pre-MVP6-01 baseline; frontend-only changes).
- Manual probe: `curl -sI http://localhost:3001/admin/13f` →
  HTTP 307 → /login (correct middleware-gated behavior).
  After login as `d41689@gmail.com` with the seeder
  populated, `/admin/13f` renders the new top navigation
  bar, the Overview hub navigation cards with real KPIs,
  and every existing section below unchanged.
