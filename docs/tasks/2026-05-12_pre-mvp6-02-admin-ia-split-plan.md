# Pre-MVP6-02: Admin 13F Information Architecture Split Plan

## Status

**Authorized to start.** Second of two Pre-MVP6 Stabilization
Gate tickets. Must complete before MVP6 feature work can open.

**Planning / decision-gate ticket — not coding.** Output is a
written split plan that becomes the MVP6 task sequence
backbone. Per PO direction:

> 这个任务先不要直接拆 7 个页面。先写一个 decision gate, 确定
> 怎么拆、先拆哪几个.

## Goal / Acceptance Criteria

Resolve the structural mismatch between PRD §11.1 (which asks
for 7 distinct admin pages) and the current implementation
(one 3300-line `/admin/13f/page.tsx` that embeds every section
as an anchor-linked block). Produce a written plan that
answers the seven questions the PO surfaced, and that lands
as the input to the MVP6 task sequence.

The output of this ticket is a **decision document** — no
production code changes. The decisions captured here drive
each subsequent MVP6 ticket's scope.

Acceptance criteria — the plan must answer all seven of the
following with a recorded decision, not just "TBD":

1. **Is `/admin/13f` retained as the Overview hub?** Yes / no
   + rationale. If yes, the existing route stays as a
   navigation + overview page; if no, propose the
   replacement.
2. **Final route naming for the 7 PRD §11.1 pages.** Concrete
   paths, not just labels. PO's working proposal (open to
   revision):
   ```
   /admin/13f                       — Overview hub
   /admin/13f/managers              — Managers list
   /admin/13f/managers/[id]         — Manager detail
   /admin/13f/sync                  — Daily Sync + no-index calendar
   /admin/13f/filings               — Filings list (+ amendments)
   /admin/13f/holdings              — Holdings Coverage + CUSIP workflow
   /admin/13f/jobs                  — Jobs / workers / EDGAR rate limit
   /admin/13f/readiness             — Readiness levels detail
   ```
3. **Reusable components extracted from the 3300-line
   single-page.** Enumerate which existing UI blocks become
   shared components (Card primitives, Table helpers,
   Dialog patterns, query hooks). Map: section in current
   page → new component name + new file path.
4. **First batch — which 2 pages ship first.** PO's working
   suggestion:
   - Overview hub (MVP6-01)
   - Managers + Manager Detail (MVP6-02)
   Confirm or revise based on engineering risk + admin
   usage patterns.
5. **Read-only vs destructive-action pages.** Tag each of
   the 7 pages: which only display data (Overview,
   Readiness), which expose admin actions (Managers, Sync,
   Filings, Holdings, Jobs). Destructive-action pages need
   the existing confirmation-dialog pattern; read-only ones
   don't.
6. **Empty / loading / error state convention.** Today the
   page mixes Loader2 spinners, "—" placeholders, and
   ad-hoc text. The new pages need ONE convention. Decide:
   - Loading: Loader2 (existing) vs Skeleton component vs
     simple text.
   - Empty: directional text (MVP5-04 pattern) vs an
     `<EmptyState>` shadcn component.
   - Error: toast vs inline error vs Alert component.
   Pick one of each and apply consistently.
7. **MVP6 task sequence + sequencing constraints.** Write
   the MVP6-01..N task list with each task's scope-in
   summary + dependency notes (e.g. MVP6-02 Managers depends
   on MVP6-01's shared layout component). The plan ships
   this sequence as MVP6's execution plan when MVP6 opens.

## Scope In

- A new decision-document task file as the deliverable.
  This file (Pre-MVP6-02) gets the answers filled in to the
  seven sections above.
- Code reading + design diagrams (mental or rendered) as
  needed to support the decisions. No production code
  changes.
- A draft MVP6 execution plan document path:
  `docs/tasks/YYYY-MM-DD_13f-mvp6-execution-plan.md`
  (filed but not opened — opens only after Pre-MVP6-01 also
  completes and PO authorizes MVP6 kickoff).

## Scope Out

- Any production code change (component extraction, route
  scaffolding, file moves). All actual work happens in
  individual MVP6 tickets that this plan defines.
- Backend changes. PRD §11.1 backend APIs are already
  shipped; this is a frontend IA decision.
- Decisions on MVP6 scope beyond the IA split itself —
  e.g. new admin features, manager bulk-import UI, CSV
  uploader. Those become MVP6 candidates only after the
  IA split is stable.
- Watchlist / Oracle's Lens M3 / Phase 4 retirement /
  Track C G1+G9 — all deferred per PO decision.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §11
  (Admin Dashboard pages + Oracle's Lens admin metrics +
  Jobs page filter requirements).
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` Pre-MVP6
  Stabilization Gate.
- 2026-05-12 PO assessment surfacing the 3300-line
  single-page problem: "把 7 个页面塞一页的代价: 滚动深度大、
  信息密度高、空数据状态下整页看起来 'broken'."

## Files Expected To Change

- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  (this file — answer the seven questions inline below).
- `docs/tasks/YYYY-MM-DD_13f-mvp6-execution-plan.md` (new,
  drafted but not opened).

## Test Plan

This ticket has no executable tests — it's a planning gate.
Acceptance is: the seven questions have recorded decisions,
the engineer doing MVP6-01 can follow the plan without
re-asking, and the PO has signed off on the proposed sequence.

## Review Pattern

Two reviewer roles:

- **Staff Engineer** — confirm the proposed component
  extraction map is technically realistic; flag any section
  in the current page that doesn't decompose cleanly.
- **Product Owner** — sign off on the route naming, page
  ordering, and read-only vs destructive-action tagging.

## Progress Notes

- 2026-05-12: Task spec filed per PO Pre-MVP6 stabilization
  decision. Engineer is asked to fill in the seven
  decisions below; PO will sign off on the sequence before
  MVP6 opens.

## Decisions (engineer recommendations 2026-05-12; PO sign-off pending)

### D1. Route structure

**Decision:** Eight routes total. `/admin/13f` is retained as the
Overview hub (read-only navigation + health summary). Seven
functional pages each get a dedicated route; the Manager Detail
page is a separate Next.js route per row, not a query-param
drawer.

```
/admin/13f                  → Overview hub (read-only)
/admin/13f/managers         → Manager list + filters + bulk import
/admin/13f/managers/[id]    → Manager detail (drilldown)
/admin/13f/sync             → Daily Sync history + no-index calendar
/admin/13f/filings          → Filings list + amendments
/admin/13f/holdings         → Holdings Coverage + CUSIP workflow
/admin/13f/jobs             → Job runs + workers + EDGAR rate limit
/admin/13f/readiness        → Readiness levels + blockers + quality findings
```

Rationale:

- Real routes (not query-param drawers) give the admin a working
  browser back button + deep-linkable URLs + clean tab-per-page
  separation. The MVP4-07b priority-Card deep link
  (`#manager-row-{id}`) gets upgraded to
  `/admin/13f/managers/{id}` once MVP6-02 ships.
- Eight routes match PRD §11.1's seven pages + an explicit
  Overview hub. The PRD never says "one page must own
  everything"; that was MVP3-08's pragmatic expedient.

Trade-off considered: collapsing Managers list + detail into one
page with a side drawer. Rejected — the Manager detail surface
(CIK history + manager_type history + linked filings + backfill
history) is too rich for a drawer.

### D2. Migration strategy from the current 3300-line page

**Decision:** Three-step migration; never rewrite in one PR.

1. **Step 1 (in MVP6-01)** — extract shared primitives from the
   single page into `frontend/components/admin13f/` and adopt
   them on the existing page in place. No new routes yet. Goal:
   the 3300-line page is unchanged in behavior but loses 1000+
   lines to imported components.
2. **Step 2 (MVP6-02..07)** — for each new page, create the
   route, move the relevant section's JSX out of the original
   page, and replace the original page's section with a
   navigation link to the new route. The original `/admin/13f`
   page shrinks one section at a time.
3. **Step 3 (MVP6-08 verification)** — after all seven
   functional pages migrate, the original `/admin/13f` becomes
   the Overview hub with only health-summary panels +
   navigation cards.

Rationale:

- In-place extraction (Step 1) de-risks Step 2 — every new
  page imports the same components the old page uses, so we
  don't have to verify two implementations of the same UI.
- No "big-bang" route migration. Each MVP6-N ticket lands an
  isolated, reviewable PR.
- The seeder (Pre-MVP6-01) means every page-migration ticket
  has visible data to verify against.

### D3. Shared components extracted from the 3300-line page

**Decision:** Three tiers of extraction, scoped to MVP6-01.

Tier 1 — primitives (already imported from
`@/components/ui/*`, no extraction needed): `Card`, `Button`,
`Badge`, `Dialog`, `Select`, `Textarea`, `Table`, `Input`,
`Toast`. These stay where they are.

Tier 2 — `frontend/components/admin13f/` shared layer (new):

- `<AdminPageLayout>` — wraps every admin/13f sub-page; nav
  links + auth gate + breadcrumbs + page title. New.
- `<AdminEmptyState reason="...">` — D5 standard empty-state
  component. New.
- `<AdminLoadingState>` — single Loader2 wrapper with
  consistent positioning. New.
- `<AdminErrorState>` — query-error fallback (inline Alert
  + retry button). New.
- `<JobPendingDialog>` — already exists inline in the 3300-line
  page; lift out.
- `<ManagerTypeEditorDialog>` — already exists inline (MVP5-05);
  lift out.
- `<ManagerCikDialogs>` — already its own component at
  `@/components/admin13f/ManagerCikDialogs`; keep.

Tier 3 — query hooks (new
`frontend/lib/admin13f/queries.ts` module):

- `useReadinessQuery`, `useQuartersQuery`, `useTasksQuery`,
  `useManagersQuery`, `useJobsQuery`, `useQualityQuery`,
  `useAmendmentsQuery`, `usePendingAmendmentsQuery`,
  `useFilingsQuery`, `useHoldingsCoverageQuery`,
  `useUnresolvedCusipsQuery`, `useWorkersQuery`,
  `useEdgarRateLimitQuery`, `useJobDetailQuery`,
  `useAmendmentDetailQuery`, `useParseRunsQuery`,
  `useQuarterDetailQuery`, `useNeedsValidationQuery`,
  `useUnknownManagerPriorityQuery`.

Each hook is a thin `useQuery(...)` wrapper; the existing
queryKey + queryFn pattern lifts out unchanged.

Rationale:

- Tier 2 turns 4 boilerplate states (loading / empty / error /
  data) into 4 shared components used by every page. Without
  this, each new page reinvents its own.
- Tier 3 means every new page imports a typed query hook with
  a single line; the queryKey stays consistent across pages
  so refetches on mutation invalidate the right things.

### D4. First batch — which 2 pages ship first

**Decision:** **MVP6-01 (Overview hub + layout shell) and
MVP6-02 (Managers + Manager Detail)** ship in the first batch.

Rationale:

- MVP6-01 is the structural prerequisite for every other page
  — it produces the shared components (Tier 2 + Tier 3) every
  subsequent ticket imports. Trying to ship MVP6-02 before
  MVP6-01 would mean reinventing the shared layer.
- Managers is the highest-traffic admin surface: every other
  page eventually links into a manager (via CIK review, type
  classification, backfill enqueue). Building it second means
  the Manager Detail deep-link (currently `#manager-row-{id}`
  inside the priority Card) gets a real route to point at.

Trade-off considered: shipping Daily Sync as MVP6-02 because
the PRD calls it out. Rejected — Sync is mostly read-only and
less critical to weekly admin workflow than Managers.

### D5. Empty / loading / error state convention

**Decision:** One component per state, four reason codes for
empty, applied consistently across every new page.

```tsx
// Loading
<AdminLoadingState />          // wraps Loader2 in a centered card region.

// Error (query failure)
<AdminErrorState
  error={query.error}
  onRetry={() => query.refetch()}
/>                              // inline Alert with retry button.

// Empty (4 reason codes)
<AdminEmptyState reason="not-seeded" />        // "No data yet — run the dev fixture seeder or wait for production ingestion."
<AdminEmptyState reason="pipeline-not-run" />  // "Pipeline hasn't run for this quarter yet — trigger the relevant job."
<AdminEmptyState reason="filter-empty" />      // "No results match the current filters. Try clearing one."
<AdminEmptyState reason="readiness-blocked"    // "Readiness blocks this surface — visit /admin/13f/readiness."
  cta={{ label: 'See blockers', href: '/admin/13f/readiness' }}
/>
```

For toasts vs inline alerts: **toasts** for action results
(save succeeded / job enqueued), **inline alerts** for query
errors. Two different lifecycles; existing pattern.

Rationale:

- Four reason codes are exactly the four cases the PO called
  out. Encoding them as a `reason` prop forces each page to
  pick the right copy rather than reinventing "—" or "no data."
- Pre-MVP6-01 produced a populated dev DB; once the seeder is
  wiped (`--reset-only`), pages should show `not-seeded` empty
  state, not look broken.

### D6. Read-only vs destructive-action page tagging

**Decision:**

| Page | Tag | Destructive actions allowed |
| ---- | --- | --- |
| Overview | Read-only | None |
| Managers list | Mixed | Bulk import (POST); inline manager_type edit (PATCH); deactivate (POST) |
| Manager Detail | Mixed | confirm-cik / reject-cik / revoke-cik / retry-cik-search / manager_type edit (all PATCH/POST) |
| Daily Sync | Mixed | Trigger retry of failed sync (POST); add/edit no-index date (POST/PATCH) |
| Filings | Mixed | Reparse individual filing (POST); resolve amendment (POST) |
| Holdings | Mixed | Confirm CUSIP mapping (POST); corporate-action confirm (POST) |
| Jobs | Mixed | Cancel job (POST); release stale lock (POST); retry failed filings (POST); enqueue job (POST) |
| Readiness | Read-only | None — links into other pages for action |

Rationale:

- Read-only pages can render fast without confirmation dialogs.
- Destructive pages need the existing confirmation pattern
  (`<JobPendingDialog>` / structured confirm dialog). MVP6-01
  ensures the dialog primitive is shared.
- Readiness stays read-only so the surface is fast to scan
  during incident response — actions live on the pages each
  blocker links to.

### D7. MVP6 task sequence

**Decision:** Eight tickets in this order.

| # | Title | Scope summary | Deps |
| - | ----- | ------------- | ---- |
| MVP6-01 | Overview Hub + Layout Shell | Extract Tier 2 + Tier 3 shared layer; `/admin/13f` becomes Overview-only with navigation cards. No new routes for other pages yet. | — |
| MVP6-02 | Managers + Manager Detail | New `/admin/13f/managers` route (list + filters + bulk import) and `/admin/13f/managers/[id]` (detail: CIK history + manager_type history + linked filings + backfill history). Original page's Managers section becomes a "go to Managers" link. MVP4-07b priority Card deep links flip from `#manager-row-{id}` to the new route. | MVP6-01 |
| MVP6-03 | Daily Sync + No-index Calendar | New `/admin/13f/sync` route. Sync history table + retry action + no-index date CRUD UI. | MVP6-01 |
| MVP6-04 | Filings + Amendments | New `/admin/13f/filings` route. Filings table with status / quarter / form_type filters; amendment resolve dialog; filing detail drawer or sub-route. | MVP6-01 |
| MVP6-05 | Holdings Coverage + CUSIP Workflow | New `/admin/13f/holdings` route. Coverage summary + unresolved CUSIP queue + corporate-action confirm UI. | MVP6-01 |
| MVP6-06 | Jobs Page Hardening | New `/admin/13f/jobs` route. Jobs table with PRD §11.3 filter dimensions (job_type / status / sync_date / quarter / date range); cancel + release-stale-lock + retry actions; worker status + EDGAR rate limit panel. | MVP6-01 |
| MVP6-07 | Readiness + Quality Findings | New `/admin/13f/readiness` route. Readiness-level detail + blockers list + quality-finding drill-throughs + needs-validation queue. | MVP6-01, MVP6-04 (for finding → filing deep links) |
| MVP6-08 | Admin E2E Verification | Closing gate: original `/admin/13f` no longer carries non-Overview content; all seven pages reachable from nav; seeder produces non-empty rendering on every page; four-role review pass (Staff Engineer / SME / PO / Frontend-UX). | MVP6-01..07 |

Parallelism:

- MVP6-02 through MVP6-07 are mutually independent (each
  consumes MVP6-01 only) — they can run in parallel if the team
  has capacity.
- MVP6-07 has a soft dependency on MVP6-04 only for cross-page
  deep links; can ship before MVP6-04 with the links
  short-circuited to "see Filings page (coming soon)" if the
  team prefers to front-load Readiness.

## Verification Results

- 2026-05-12: D1-D7 filled in by engineer. **Pre-MVP6-02 ready
  for PO sign-off.** No code changes yet. After PO sign-off,
  MVP6 opens with MVP6-01 as the first ticket; the draft MVP6
  execution plan in
  `docs/tasks/2026-05-12_13f-mvp6-execution-plan.md` becomes
  active.
