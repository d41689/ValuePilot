# MVP6-05: Holdings Coverage + CUSIP Workflow Page

## Status

**Authorized to start (PO 2026-05-12 after MVP6-04 ship).** Fifth
MVP6 ticket. Depends on MVP6-01 only.

## Goal / Acceptance Criteria

PRD §11.1 "Holdings Coverage" page. Moves three surfaces off the
index page into a dedicated route: the holdings-coverage summary,
the unresolved-CUSIP table, and the MVP3-08 corporate-action
confirm flow.

Acceptance criteria:

- **New route `/admin/13f/holdings`** wrapped with
  `<AdminPageLayout title="Holdings Coverage" description="...">`.
- **Holdings Coverage Card** — same layout as the index page
  (MetricTiles for total / common / linked / options +
  unresolved / combination / confidential badges), powered by
  the existing `useHoldingsCoverageQuery` + the
  `normalizeHoldingsCoverage` helper. Loading via
  `<AdminLoadingState>`, error via `<AdminErrorState>`,
  no-current-quarter fallback via `<AdminEmptyState
  reason="readiness-blocked">`.
- **Unresolved CUSIPs Card** — full-width table (no longer
  capped at 6 rows like the index page's preview); powered by
  the existing `useUnresolvedCusipsQuery` +
  `normalizeUnresolvedCusips` helper. Same columns (CUSIP /
  Status / Issuer / Rows).
- **Corporate Action Card + Drawer** — the entire MVP3-08
  preview-then-confirm flow lifts to this route:
  - Card with "Open corporate action mapping" trigger button.
  - DrawerShell with the form: CUSIP (9-char), from/to
    quarter, new ticker (optional), evidence URL, reason +
    Preview button.
  - Preview result rendered inside the drawer; Confirm action
    POSTs `/admin/13f/cusips/corporate-actions/confirm` and
    invalidates the unresolved-CUSIPs list.
  - All `caCusip / caFromQ / caToQ / caNewTicker / caEvidence
    / caReason / caPreview / caOpen` state moves to the new
    route along with `caPreviewMutation` + `caConfirmMutation`.
- **`AdminPageLayout` nav** flipped: `Holdings` entry now
  `shipped: true`, `href: '/admin/13f/holdings'`.
- **Overview hub Holdings card** on `/admin/13f` flipped from
  `<a href="#holdings">` to `<Link href="/admin/13f/holdings">`.
- **Index page deletions**:
  - The 2-col grid Card (Holdings Coverage + Unresolved CUSIPs,
    ~96 lines).
  - The Corporate Action Card + DrawerShell (~110 lines combined).
  - All `ca*` state + mutations.
  - `holdingsCoverage` + `unresolvedCusips` memos.
  - `useUnresolvedCusipsQuery` import + isLoading from
    aggregate. `useHoldingsCoverageQuery` stays — Overview hub
    Holdings card still reads `holdingsCoverage.linkedRatioLabel`.

## Scope In

- `frontend/app/(dashboard)/admin/13f/holdings/page.tsx` (new).
- `frontend/components/admin13f/AdminPageLayout.tsx` (nav
  flip).
- `frontend/app/(dashboard)/admin/13f/page.tsx` (section +
  drawer + state removal; Overview hub card href flip).
- This task file.

## Scope Out / Scope Refinements

- **No bulk-edit CUSIP UI.** PRD §8 admin flow supports
  per-CUSIP PATCH; bulk-edit is a separate ticket.
- **No `cusip_ticker_map` browse / search.** The
  `useCusipMappingsQuery` (POST + GET cusips) endpoints exist
  but the V1 surface is only the unresolved queue. Browsing
  the full map is a follow-up.
- **No backend changes.**
- **No frontend tests for the new page** — lint + build +
  manual probe is the verification bar (matches MVP6-02..04
  pattern).

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §7 (Holdings
  Data Model), §8 (CUSIP Mapping), §11.1 (Holdings Coverage
  admin page).
- `docs/tasks/2026-05-11_13f-mvp3-06-corporate-action-temporal-mapping.md`
  (MVP3-08 corporate-action flow, source of the form shape).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D4 + D6 + D7.

## Files Expected To Change

- `frontend/app/(dashboard)/admin/13f/holdings/page.tsx` (new)
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
  2. `/admin/13f` Overview Holdings card → `/admin/13f/holdings`.
  3. Coverage panel shows the seeded quarter's coverage
     (linked common ratio > 0 with devseed data).
  4. Unresolved CUSIPs table renders.
  5. Open corporate-action drawer; preview a synthetic CUSIP
     (won't have prior holdings in dev — preview returns
     no-op result).

## Progress Notes

- 2026-05-12: Task spec filed.
- 2026-05-12: Implementation:
  - New route `frontend/app/(dashboard)/admin/13f/holdings/page.tsx`
    wrapped with `<AdminPageLayout>`. Three Cards (Holdings
    Coverage, Unresolved CUSIPs, Corporate Action Mapping) plus
    the MVP3-08 Confirm DrawerShell, all reusing existing
    primitives (`DrawerShell`, `MetricTile`, the shared admin13f
    state components, the `useHoldingsCoverageQuery` /
    `useUnresolvedCusipsQuery` / `useReadinessQuery` hooks).
  - **Corporate Action Preview/Confirm** wired as direct
    `POST /admin/13f/cusips/corporate-actions/preview` and
    `POST /admin/13f/cusips/corporate-actions/confirm` mutations
    inside the confirm drawer. Confirm invalidates the
    unresolved-CUSIPs + holdings-coverage queries on success.
  - **`AdminPageLayout` nav** Holdings entry flipped to
    `shipped: true` with `href: '/admin/13f/holdings'`.
  - **Overview hub Holdings card** on `/admin/13f` flipped from
    `<a href="#holdings">` to `<Link href="/admin/13f/holdings">`.
  - **Index page deletions** (240 lines: 2886 → 2646):
    - 2-col Holdings Coverage + Unresolved CUSIPs grid (~96 lines).
    - Corporate Action Card + DrawerShell (~115 lines combined).
    - `caOpen` / `caCusip` / `caFromQ` / `caToQ` / `caNewTicker`
      / `caEvidence` / `caReason` / `caPreview` state vars
      (9 lines).
    - `caPreviewMutation` + `caConfirmMutation` (~19 lines).
    - `unresolvedCusips` memo. `holdingsCoverage` memo stays
      because Overview hub Holdings card still reads
      `holdingsCoverage.linkedRatioLabel`.
    - `useUnresolvedCusipsQuery` hook call + import.
    - `normalizeUnresolvedCusips` destructure.
    - `Link2` icon import (last use removed).
    - `unresolvedCusipsQuery.isLoading` from the page-level
      `isLoading` aggregate.
  - **Scope refinements** (recorded in spec):
    - SR0: no bulk-edit CUSIP UI.
    - SR1: no `cusip_ticker_map` browse/search.
    - SR2: no backend changes.
    - SR3: no frontend tests for the new page; lint + build +
      manual probe is the verification bar.

## Verification Results

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors.
- `docker compose exec web npm run build` → compiled
  successfully. New `/admin/13f/holdings` route 4.09 kB
  (163 kB First Load).
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `pytest -q` → **781 passed** (unchanged; no backend
  changes).
