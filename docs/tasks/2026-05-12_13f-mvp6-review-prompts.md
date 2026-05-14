# 13F MVP 6 End-to-End Review Prompts

Four reviewer prompts for the MVP 6 closing review. Each is
self-contained — drop the prompt into a fresh chat or hand it
to a human reviewer without needing the rest of this
repository's history. Verification baseline is in
`docs/tasks/2026-05-12_13f-mvp6-end-to-end-verification.md`.

Roles:

1. Staff Engineer — cross-ticket contract / decision-gate
   correctness review.
2. Financial Data Product Reviewer (13F Domain SME) — admin
   workflow correctness, copy accuracy, evidence-threshold
   judgment on operator surfaces.
3. Product Owner — closing-gate sign-off, scope-freeze
   confirmation, Post-MVP6 candidate ranking.
4. Frontend / UX (optional) — eight-route navigation, empty
   state coverage, ARIA + focus semantics, deep-link
   integrity.

---

## 1. Staff Engineer Prompt

You are the Staff Engineer conducting the MVP 6 cross-ticket
review for the ValuePilot 13F automation track. MVP 6 is the
Admin Operations Console milestone — a **frontend
information-architecture split** with zero backend changes.
Seven sub-tasks shipped on branch `docs/13f-automation-prd`
(plus two Pre-MVP6 stabilization tickets):

- `Pre-MVP6-01` Dev fixture seeder (`a43d466`).
- `Pre-MVP6-02` Admin IA split plan (D1–D7) (`5af1aa1`).
- `MVP6-01` Overview Hub + Layout Shell + shared admin13f
  layer (Tier 2 + Tier 3) (`1476246`).
- `MVP6-02` Managers + Manager Detail routes + MVP4-07b
  deep-link upgrade (`222e9e9`).
- `MVP6-03` Daily Sync + No-index Calendar route
  (`7eb8a4b`).
- `MVP6-04` Filings + Amendments route (`6c97b29`).
- `MVP6-05` Holdings Coverage + CUSIP Workflow route
  (`0e95dab`).
- `MVP6-06` Jobs Page Hardening + JobPendingDialog +
  ReleaseStaleLockDialog lift (`fe3a6cd`).
- `MVP6-07` Readiness + Quality Findings route (`8b2e51a`).

Verification baseline: 781 backend tests / 0 warnings; alembic
head `20260512130000` (unchanged from MVP5-05 — no MVP6
migrations); frontend lint clean + 17 `oraclesLens.test.js`
cases + production build successful with eight `/admin/13f`
routes prerendered.

Review these cross-cutting concerns and return a verdict plus
pre-merge action items vs follow-up items:

1. **D1 hold: all eight routes shipped.** Open
   `frontend/components/admin13f/AdminPageLayout.tsx` and
   confirm every `NAV_ENTRIES` row has `shipped: true`. No
   anchor fallbacks (`#xxx`) should remain. Open each of the
   seven new route files
   (`frontend/app/(dashboard)/admin/13f/{managers,sync,filings,holdings,jobs,readiness}/page.tsx`
   + `managers/[id]/page.tsx`) and confirm each wraps with
   `<AdminPageLayout>` and is callable as a Next.js page.

2. **D2 hold: in-place extraction first, then per-page lift.**
   The MVP6-01 commit should have created the Tier 2 + Tier 3
   layer without changing routes. The MVP6-02..07 commits
   should each lift one section out of `/admin/13f/page.tsx`
   and add one new route. Read the diff of `MVP6-01` and
   confirm no new routes were added beyond the layer
   extraction. Walk the index page commit-by-commit and
   confirm each subsequent ticket removes exactly the sections
   it claimed in its task spec.

3. **D3 hold: Tier 2 + Tier 3 boundaries.**
   `frontend/components/admin13f/` should have exactly nine
   files (8 component files + the layout shell). Open
   `frontend/lib/admin13f/queries.ts` and confirm it has ~20
   `useXQuery` hooks with consistent queryKey shapes
   (`['admin-13f-<thing>', ...filterArgs]`) so
   `invalidateQueries` calls across pages hit the right
   caches. Spot-check one: `useJobsQuery` queryKey includes
   all six filter dims so the new Jobs route's filters refetch
   correctly.

4. **D4 hold: minimum operational shape per ticket.** Walk
   the SR (Scope Refinement) list in each MVP6-N spec and
   confirm:
   - MVP6-04 SR1 (no JobPendingDialog reuse, direct POST
     mutations) actually shipped that way.
   - MVP6-04 SR2 (no quarter filter — backend missing
     `report_quarter` param) is accurate: `useFilingsQuery`
     does NOT accept a quarter arg.
   - MVP6-05 SR0 (no bulk-edit CUSIP UI) — confirm only
     per-CUSIP confirms exist on `/admin/13f/holdings`.
   - MVP6-06 SR5 (runJob / pendingJob / triggerJob duplicated
     on both index + Jobs route) — confirm both pages own
     independent copies; the shared `JobPendingDialog` is
     presentational only.

5. **D5 hold: empty / loading / error convention.** Grep for
   `AdminEmptyState reason=` across the seven new route files.
   Confirm at least one route uses each of the four canonical
   reasons (`not-seeded`, `pipeline-not-run`, `filter-empty`,
   `readiness-blocked`). Toasts vs inline alerts: confirm
   action results (mutation success/error) toast, and query
   errors render inline via `AdminErrorState`.

6. **D6 hold: read-only vs destructive-action tagging.**
   Overview + Readiness should have no destructive actions on
   the page itself. Suggested-Actions on the Quarter Detail
   drawer is a borderline case — confirm they go through
   `runJob` → `JobPendingDialog` (preview-then-confirm), not a
   silent POST.

7. **D7 hold: nav flips + deep-link integrity.** The MVP4-07b
   priority Card's manager deep-link should now go to
   `/admin/13f/managers/{id}` (MVP6-02 flip). The Overview hub
   Holdings / Jobs / Filings / Sync / Managers / Readiness /
   Oracle's Lens KPI cards should all use `<Link>` with route
   paths, not anchor hrefs. The Oracle's Lens KPI card
   deep-links to `/admin/13f/readiness` (not
   `/13f/oracles-lens`) — confirm this is intentional (the
   user-facing dashboard lives at `/13f/oracles-lens`, the
   admin priority surface is `/admin/13f/readiness`).

8. **runJob duplication safety.** With MVP6-06 SR5 in mind,
   both `/admin/13f/page.tsx` and
   `/admin/13f/jobs/page.tsx` and `/admin/13f/readiness/page.tsx`
   each carry their own copy of `lockKeyForPayload` +
   `runJob` + `pendingJob` + `triggerJob`. Confirm the three
   copies of `lockKeyForPayload` are byte-identical. If a
   future change to the lock-key vocabulary is needed (e.g.
   adding a new job type), all three call sites must update
   in lockstep — flag as a technical-debt note for the
   backlog.

9. **Next.js 15 params Promise pattern.** MVP6-02 adopted
   `params: Promise<{ id: string }>` + `const { id } = use(params)`
   on `managers/[id]/page.tsx`. Confirm this is the only
   dynamic route in MVP6 (no other `[xxx]` routes).

10. **Pytest 0 warnings.** Open the latest `pytest -q` output
    and confirm it ends with `781 passed in Xs` with NO
    "warnings" clause. The MVP4-10 conftest savepoint
    hardening must still hold; MVP6 must not have introduced
    SAWarning regressions.

Deliverable: APPROVE / APPROVE-WITH-FIXES / REJECT plus a
pre-merge action list (must-land-before-MVP6-closes) vs
follow-up list (file as MVP7 backlog).

---

## 2. Financial Data Product Reviewer (13F Domain SME) Prompt

You are the 13F Domain SME reviewing MVP 6 admin workflow
correctness. MVP 6 is a frontend IA split — no scoring formula
changes, no schema changes. But the operator surfaces are
rearranged, and the **copy + evidence-threshold judgments**
need an SME pass before MVP7 candidates open.

Verification baseline:
`docs/tasks/2026-05-12_13f-mvp6-end-to-end-verification.md`.

Your goal: confirm the admin workflows still hold semantically
on each of the seven new routes, and flag any copy or
operator-affordance issue that could lead to a misinterpretation.

Specifically:

1. **`/admin/13f/managers` CIK review loop.** Walk through a
   `pending_cik_review` manager: the list shows the manager,
   the detail page shows the CIK candidates, the confirm /
   reject / revoke / retry-search dialogs (from
   `ManagerCikDialogs`) are reachable. Question: when an admin
   revokes a CIK, the quarter data tied to that manager is
   flagged for re-review per `selectedQuarterDetail.summary?.revoked_cik_review_required`.
   Is the warning copy in the Quarter Detail drawer
   ("Reconfirm the manager CIK before relying on downstream
   analytics") strong enough? Operators should not treat a
   revoked-CIK quarter as final.

2. **`/admin/13f/managers/[id]` manager_type editor evidence.**
   The inline `ManagerTypeEditorDialog` accepts a free-text
   note (optional). MVP5 SME flagged this as too weak for
   audit trail; MVP6 did not address it (out of scope —
   frontend IA only). Confirm whether the audit trail
   (`institution_manager_type_review_events`) row carries
   enough context that a future reviewer can reconstruct the
   evidence even with an empty note. If not, flag a follow-up
   ticket to make the note required for non-`unknown`
   classifications.

3. **`/admin/13f/holdings` Corporate Action confirm semantics.**
   The MVP3-08 confirm DrawerShell takes:
   - CUSIP (9 chars)
   - From quarter / To quarter
   - Optional new ticker
   - **Required** evidence URL + reason
   
   Walk the flow on a synthetic corporate action (e.g. spin-off).
   Does the preview output (`affected_ownership_changes_count`
   + `overlapping_mapping_ids`) give an admin enough confidence
   to confirm? Is the warning copy when overlapping mappings
   exist ("Provide prior_mapping_id to supersede, or adjust
   the effective quarter window") actionable, or does the
   admin need additional admin tooling?

4. **`/admin/13f/jobs` Historical Backfill copy on pre-2023.**
   The Historical Backfill Card surfaces a value-unit
   risk warning when the range includes pre-2023 ("value-unit
   parsing risk. Enable Dry run before enqueueing."). Confirm
   the dry-run-required behavior actually fires for pre-2023
   ranges and that the copy makes the risk concrete. Per
   CLAUDE.md: Kahn Brothers (`0001039565-*`) reports values
   in dollars, not thousands — does the dry-run output flag
   reconciliation warnings for this filer as True Positives,
   or could an operator misread them as bugs to suppress?

5. **`/admin/13f/jobs` Batch Reparse scope on quarter.** The
   Batch Reparse Card previews `candidate_count` +
   `missing_raw_infotable_count`. Walk an admin enqueueing a
   reparse on the latest quarter. If `missing_raw_infotable_count`
   is non-zero, the reparse will skip those rows — does the
   admin know? Is the copy "Missing raw infotable: N" enough
   warning, or should it be promoted to a banner?

6. **`/admin/13f/readiness` Quality Reports drilldown depth.**
   The Quality Reports Card shows quarter / status / issues
   / checked / summary. There's no per-finding drilldown on
   this V1 surface — the issues column shows aggregate
   counts. SME judgment: is this depth right for V1, or
   should clicking a row open a finding detail panel
   (V2 backlog item)?

7. **`/admin/13f/readiness` Unknown Manager Type Priority
   directional copy.** The empty-state copy reads "No
   Oracle's Lens scores computed yet. Use the Historical
   Backfill section on /admin/13f/jobs to score a quarter,
   then return here to prioritize manager classification."
   Confirm this is accurate now that the Historical Backfill
   Card moved from the index page to `/admin/13f/jobs` —
   the link points to the correct destination and the
   workflow it describes is still valid end-to-end.

8. **NT filer handling on `/admin/13f/readiness`.** The Data
   Readiness Card has an "NT filers" MetricTile with detail
   "reported elsewhere". Where exactly are NT filers reported
   in the admin UI? Is the cross-reference still
   discoverable, or did the IA split orphan this signal?

Deliverable: per-item APPROVE / FLAG / BLOCK verdict.
BLOCKs require a pre-MVP6-close fix; FLAGs can be filed as
MVP7 backlog. Pay extra attention to copy that could
mislead an admin into approving bad data downstream.

---

## 3. Product Owner Prompt

You are the Product Owner reviewing MVP 6 closure for the
ValuePilot 13F automation track. MVP 6 is the Admin
Operations Console milestone — a frontend
information-architecture split that turned a 3300-line
single-page admin into seven dedicated PRD §11.1 routes plus
a thin Overview hub. Seven sub-tasks shipped on branch
`docs/13f-automation-prd`; verification baseline is in
`docs/tasks/2026-05-12_13f-mvp6-end-to-end-verification.md`.

Your goal is to confirm that:

1. **All MVP6 sub-tasks closed against shipped code.** Walk
   each row of the MVP 6 Contract Checklist in the
   verification doc and open the cited commits. For each,
   confirm:
   - The task spec's acceptance criteria are met.
   - The scope refinements (SR list) accurately describe what
     was deferred.
   - No silent feature creep beyond the SR list.

2. **Scope-freeze tally is zero new backend / scoring debt.**
   Verify by reading the five Track A2 / B / C / D / E
   deferral entries — each should still trace to an explicit
   backlog line. If any has silently slipped into MVP6 scope,
   reopen it as a defect. The frontend-only contract is
   especially important: confirm zero Alembic migrations in
   MVP6, zero new backend tests, zero new pytest warnings.

3. **D1–D7 decisions held against shipped code.** The
   Decision-Gate Verification table in the verification doc
   claims all seven Pre-MVP6-02 decisions held. Spot-check
   two of them in the actual code:
   - D5 (four empty-state reason codes) — open two route
     files at random and grep for `AdminEmptyState reason=`.
     Confirm the reason value is one of the four canonical
     codes, not an ad-hoc string.
   - D6 (read-only vs destructive-action tagging) — confirm
     `/admin/13f/readiness` is read-only (no buttons on the
     page itself trigger destructive mutations directly; the
     Quarter Detail drawer's Suggested Actions go through
     `JobPendingDialog` confirm).

4. **Overview hub is the right thin nav surface.** After
   MVP6-07 the `/admin/13f` page is 1125 lines (down from
   ~3300) and contains: KPI nav strip + Admin Tasks Card +
   Manual Controls Card + dialog mounts. Decide:
   - Is the KPI nav strip the right read at the top of the
     hub? (8 cards in a single row.)
   - Should the Tasks Card move to a dedicated route in MVP7,
     or stay on the hub as the page-level CTA?
   - Should the Manual Controls Card (Setup / Stock Reference
     / Quarter Pipeline / Backfill / Accession Repair) stay
     on the hub or move to `/admin/13f/jobs` alongside HB +
     BR (which are similar trigger surfaces)?

5. **MVP5-03 Phase 3 status.** Phase 3 is still gated on
   staging / prod PO sign-off — unchanged by MVP6. Confirm
   you have a path to producing the comparison report (does
   the staging environment have linked CUSIPs + a persisted
   scoring backfill?). Phase 3 is the only blocker between
   the current state and MVP5 GA closure.

6. **Post-MVP6 candidate ordering.** Six candidates surfaced
   in the verification doc Post-MVP6 Decision Inputs:
   - Track D Watchlist V1
   - MVP5-03 Phase 3 server-default flip
   - Track A2 Quality + Valuation Overlay (Oracle's Lens M3)
   - MVP5-03 Phase 4 `?persisted=0` retirement
   - Track C G1 / G9 admin email + external ticketing
   - Manual Controls + Tasks Card UX refresh

   Rank these. State whether MVP7 opens immediately after
   MVP6-08 commits, or whether you want a release window or
   review cycle in between.

7. **GA messaging decision (carried over from MVP5).** The
   user-facing dashboard `/13f/oracles-lens` is unchanged by
   MVP6 (frontend default already runs the GA configuration
   per MVP4-07a). Is there any user-facing changelog or
   release note that needs to ship alongside MVP6? Admin
   audience only suggests no, but confirm.

8. **Reviewer follow-up handling.** The Staff Engineer / SME
   / Frontend prompts may surface action items. Decide upfront:
   - Must-land-before-MVP6-closes — fix in this branch.
   - Should-fix-in-MVP7 — file as backlog ticket.
   - Could-fix-later — note but do not file.

   State your threshold.

Deliverable: MVP6 close sign-off verdict (APPROVE /
APPROVE-WITH-CONDITIONS / REJECT), Post-MVP6 candidate
ranking, MVP7 decision-gate timing, and a recommendation on
reviewer follow-up triage.

---

## 4. Frontend / UX Reviewer Prompt (Optional)

You are the Frontend / UX reviewer for the MVP 6 admin
information-architecture split. MVP 6 lifted seven sections
out of a single 3300-line page into dedicated routes with a
shared layout shell and a four-state component convention.

Files in scope:

- `frontend/components/admin13f/AdminPageLayout.tsx` — shared
  nav + page shell.
- `frontend/components/admin13f/AdminEmptyState.tsx` — four
  reason codes.
- `frontend/components/admin13f/AdminLoadingState.tsx` /
  `AdminErrorState.tsx` — loading + query-error wrappers.
- `frontend/components/admin13f/Admin13FPrimitives.tsx` —
  `DrawerShell` + `MetricTile`.
- `frontend/components/admin13f/JobPendingDialog.tsx` +
  `ReleaseStaleLockDialog.tsx` — preview-then-confirm dialogs.
- `frontend/components/admin13f/ManagerCikDialogs.tsx` +
  `ManagerTypeEditorDialog.tsx` — manager-domain dialogs.
- The seven new routes:
  `frontend/app/(dashboard)/admin/13f/{managers,managers/[id],sync,filings,holdings,jobs,readiness}/page.tsx`.

Review:

1. **Eight-route navigation flow.** Sign in as admin. Visit
   `/admin/13f`. Confirm:
   - The KPI nav strip shows 8 cards (Overview hub navigates
     to seven dedicated routes + the page itself).
   - Each KPI card uses `<Link>`, not `<a href="#xxx">`. No
     anchor fallbacks remain.
   - The `AdminPageLayout` nav bar (top-of-page) shows all
     8 entries with consistent labels and the current page
     highlighted.

2. **Empty-state reason code coverage.** With the seeder run
   (`docker compose exec api python -m scripts.seed_13f_dev_fixture`),
   most pages have data. Then run `--reset-only` and verify:
   - At least one page renders `AdminEmptyState reason="not-seeded"`.
   - Filter-empty states render `reason="filter-empty"` (set
     an impossible filter, e.g. status=`canceled` on Jobs).
   - Readiness-blocked rendering: on
     `/admin/13f/holdings`, if `readiness.latest_usable_quarter`
     is null, the coverage panel should render
     `reason="readiness-blocked"`.

3. **DrawerShell ARIA + focus.** Open the Quarter Detail
   drawer on `/admin/13f/readiness`. Confirm:
   - Drawer has `role="dialog"` and `aria-labelledby` pointing
     at the title element.
   - Tab order stays within the drawer (no focus escape to
     the background while open).
   - Close (Escape or close button) returns focus to the
     "Review" button on the originating row.
   - Same checks on the Job Detail drawer on `/admin/13f/jobs`.
   - Same checks on the Parse Runs + Amendment Detail drawers
     on `/admin/13f/filings`.
   - Same checks on the Corporate Action confirm drawer on
     `/admin/13f/holdings`.

4. **JobPendingDialog reuse across routes.** Trigger
   `JobPendingDialog` from three places:
   - `/admin/13f` Tasks Card retry action.
   - `/admin/13f` Manual Controls "Bootstrap whitelist" button.
   - `/admin/13f/jobs` Retry Targets button inside the Job
     Detail drawer.
   - `/admin/13f/readiness` Suggested Actions button inside
     the Quarter Detail drawer.

   All four should open the same visual dialog (same copy,
   same Queue button). The mutation should invalidate the
   right query keys per the route's `refreshXxxData` callback.

5. **Deep-link integrity.**
   - On `/admin/13f/readiness` Unknown Manager Type Priority
     Card, click a manager name. Confirm it navigates to
     `/admin/13f/managers/{id}` (not the legacy
     `#manager-row-{id}` anchor).
   - On `/admin/13f` Overview Oracle's Lens KPI card, click
     it. Confirm it navigates to `/admin/13f/readiness` (the
     admin priority surface), not `/13f/oracles-lens` (the
     user-facing dashboard).
   - On `/admin/13f` Overview Holdings / Jobs / Filings /
     Sync / Managers / Readiness KPI cards, each navigates to
     its respective route.

6. **Drawer affordances.** On `/admin/13f/jobs`, open the Job
   Detail drawer for a job with `can_release_stale_lock=true`.
   Confirm:
   - The stale-lock banner appears with the "Release stale
     lock" button.
   - Clicking the button opens `ReleaseStaleLockDialog`.
   - Confirming the dialog releases the lock and refreshes
     the jobs list.

7. **Historical Backfill + Batch Reparse forms on
   /admin/13f/jobs.** Enter an invalid quarter (e.g. `2022-Q5`).
   Confirm preview returns an error and the dialog stays open.
   Then enter a valid quarter. Preview succeeds; the
   `Enqueue` button enables. Click Enqueue. Confirm a toast
   fires + the Job Runs table refreshes.

8. **Manager Detail page routing.** Visit `/admin/13f/managers`.
   Click "Detail" on a manager row. Confirm the URL becomes
   `/admin/13f/managers/{id}` and the page renders the manager
   detail panel with CIK history + manager_type history +
   linked filings + backfill history. Browser back button
   returns to the list with filters preserved (or, if not,
   note as a follow-up).

9. **Overview hub remaining content.** Confirm `/admin/13f`
   only renders: KPI nav strip + the header strip (data
   readiness chip + EDGAR mode chip) + Admin Tasks Card +
   Manual Controls Card + dialog mounts (`JobPendingDialog`
   / `ReleaseStaleLockDialog` / `ManagerCikDialogs`). No
   migrated content sneaks through.

10. **Cross-page query invalidation.** Trigger a manager
    `manager_type` PATCH on `/admin/13f/managers/{id}`. Navigate
    back to `/admin/13f/readiness`. Confirm the Unknown
    Manager Type Priority Card reflects the new
    classification (the affected manager either dropped off
    the list or moved down in priority). This validates the
    `frontend/lib/admin13f/queries.ts` queryKey shapes are
    consistent enough that one mutation invalidates the
    right caches across pages.

Deliverable: per-item APPROVE / RECOMMEND-CHANGE / BLOCK with
specific copy / spacing / interaction notes.
RECOMMEND-CHANGEs are MVP7 backlog candidates unless they
materially affect operator trust (in which case escalate to
the PO before MVP6 closes).
