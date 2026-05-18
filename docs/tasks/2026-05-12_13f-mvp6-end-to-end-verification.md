# 13F MVP 6 End-to-End Admin IA Verification

## Goal / Acceptance Criteria

Close MVP 6 (Admin Operations Console — frontend IA split) with
a Docker-based verification pass across the seven MVP6 sub-tasks
and the four-role review pattern. MVP6 is a **frontend
information-architecture milestone** with zero backend changes
— the verification gate confirms that.

Acceptance criteria:

- The seven Pre-MVP6-02 D1 routes are live and reachable from
  the shared `AdminPageLayout` nav (Overview + 7 functional
  pages = 8 routes total).
- Each MVP6-01 through MVP6-07 task spec is closed against
  shipped code with passing verification.
- The Pre-MVP6-02 D1–D7 decisions are held against shipped
  code with **no silent deviations**.
- Alembic migrations apply cleanly to head; latest revision is
  the MVP5-05 `institution_manager_type_review_events` table
  (`20260512130000`) — **no MVP6 migrations**.
- Backend full unit suite passes at **781 passed / 0 warnings**
  (the MVP5-07 baseline; MVP6 added zero backend tests).
- Frontend lint, `node --test lib/oraclesLens.test.js` (17
  cases), and production `npm run build` all pass.
- Scope-freeze tally for MVP6 is **zero new backend / scoring
  debt** — every Track A2 / B / C / D / E item from
  `2026-05-12_post-mvp4-roadmap.md` stays deferred.

## Scope In

- Verification-only task log.
- Docker verification commands and results.
- Contract checklist for MVP6-01 through MVP6-07.
- Decision-gate verification for Pre-MVP6-02 D1–D7.
- Pre-MVP6 stabilization closure note (Pre-MVP6-01 + Pre-MVP6-02
  both shipped before MVP6 opened).
- Four review roles, prompts filed in
  `docs/tasks/2026-05-12_13f-mvp6-review-prompts.md`.
- Minimal fixes only if verification exposes a regression.

## Scope Out

- New feature work, backend additions, scoring changes.
- MVP5-03 Phase 3 server-default flip (still gated on staging /
  prod PO sign-off — unchanged by MVP6).
- MVP5-03 Phase 4 `?persisted=0` retirement (post-Phase 3).
- Track A2 (valuation overlay), Track B (pre-2023 backfill),
  Track C (admin G1 / G9), Track D (Watchlist), Track E
  (engineering debt) — all explicitly deferred.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §11 (Admin
  page list + filter dimensions + field set).
- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  D1–D7 decisions.
- `docs/tasks/2026-05-12_13f-mvp6-execution-plan.md` — MVP6
  scope and task sequence.
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` — track
  organization and deferral rationale.

## Docker Verification Commands

- `docker compose exec api alembic current`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run build`

## MVP 6 Contract Checklist

- [x] **Pre-MVP6-01** Dev fixture seeder (synthetic Path B).
      `a43d466`. Idempotent `--reset` and `--reset-only` flags;
      devseed CIK prefix `9999`; ticker prefix `DEVSEED`; real
      SEC 20-char accession format
      (`XXXXXXXXXX-YY-NNNNNN`); produces 8 stocks / 32
      managers / 64 filings / 252 holdings across 2 quarters
      with the four caveat codes present in one manager. Per
      [[feedback_dev-fixture-pollute-pytest]]: must run
      `--reset-only` before pytest to avoid 177-test
      pollution.
- [x] **Pre-MVP6-02** Admin IA split plan. `5af1aa1`. D1–D7
      decisions filled in: eight routes, three-step migration,
      three-tier component extraction, two-page first batch,
      four empty-state reason codes, read-only vs
      destructive-action tagging, eight-ticket sequence.
- [x] **MVP6-01** Overview Hub + Layout Shell. `1476246`.
      Tier 2 shared layer (`AdminPageLayout` /
      `AdminLoadingState` / `AdminEmptyState` /
      `AdminErrorState` / `DrawerShell` / `MetricTile`
      primitives + `JobPendingDialog` + `ManagerTypeEditorDialog`
      lifted). Tier 3 query module
      (`frontend/lib/admin13f/queries.ts`, 20 hooks).
      `/admin/13f` becomes Overview-only with KPI nav cards
      + Admin Tasks + Manual Controls. SR1: JobPendingDialog
      lift deferred from MVP6-01 to MVP6-06 (natural home with
      Jobs page).
- [x] **MVP6-02** Managers + Manager Detail. `222e9e9`. New
      `/admin/13f/managers` route (list + filters + bulk
      import) and `/admin/13f/managers/[id]` (CIK history +
      manager_type history + linked filings + backfill
      history). MVP4-07b priority Card deep-link flipped from
      `#manager-row-{id}` anchor to `/admin/13f/managers/{id}`.
      Next.js 15 `params` Promise pattern adopted.
- [x] **MVP6-03** Daily Sync + No-index Calendar.
      `7eb8a4b`. New `/admin/13f/sync` route. Sync history
      table + retry action + no-index date CRUD UI with
      `currentYear` useMemo to avoid Date-construction unstable
      dep.
- [x] **MVP6-04** Filings + Amendments. `6c97b29`. New
      `/admin/13f/filings` route. Filings table with
      parse_status filter + Parse runs drawer with direct-POST
      Reparse + Amendment Accessions table with direct-POST
      Resolve. SR1: no JobPendingDialog reuse on the new route
      (direct mutations). SR2: no quarter filter in V1 (backend
      endpoint missing `report_quarter` param).
- [x] **MVP6-05** Holdings Coverage + CUSIP Workflow.
      `0e95dab`. New `/admin/13f/holdings` route. Coverage
      panel + Unresolved CUSIPs table (full, no longer capped
      at 6) + MVP3-08 Corporate Action confirm DrawerShell.
      SR0: no bulk-edit CUSIP UI. SR1: no `cusip_ticker_map`
      browse/search. SR2: no backend changes. SR3: no frontend
      tests for the new route.
- [x] **MVP6-06** Jobs Page Hardening + JobPendingDialog lift.
      `fe3a6cd`. New `/admin/13f/jobs` route: Job Runs with
      six PRD §11.3 filter dimensions + Job Detail Drawer +
      Worker Heartbeat + EDGAR Rate Limit + Historical Backfill
      + Batch Reparse. Two new shared components extracted:
      `JobPendingDialog.tsx` + `ReleaseStaleLockDialog.tsx`
      (presentational, used by both the index page Tasks Card
      and the new Jobs route). SR1: no bulk job-cancel. SR3:
      Worker + EDGAR panels lifted in full (Overview keeps
      chip refs only). SR4: HB + BR Cards lifted per PO sign-off.
      SR5: runJob / pendingJob / triggerJob duplicated on both
      routes (intentional, MVP6 "minimum operational shape"
      mandate).
- [x] **MVP6-07** Readiness + Quality Findings.
      `8b2e51a`. New `/admin/13f/readiness` route. Five Cards
      (Data Readiness & Operations Health, Quality Reports,
      Needs Validation, Unknown Manager Type Priority,
      Quarters) + Quarter Detail drawer. Overview hub Readiness
      + Oracle's Lens KPI cards flipped to next/links. SR2:
      Manual Controls stays on index. SR3: Admin Tasks Card
      stays on index. SR4: new route owns its own runJob /
      pendingJob / triggerJob.

## Verification Results

- `docker compose exec api alembic current` — at head
  `20260512130000` (MVP5-05). **No MVP6 migrations**, as
  expected for a frontend-only milestone.
- `docker compose exec api pytest -q` — **781 passed in
  55.81s, 0 warnings**. The MVP5-07 baseline holds; the
  MVP4-10 conftest savepoint hardening still passes; MVP6
  added zero backend tests.
- `docker compose exec web npm run lint` — No ESLint warnings
  or errors.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  — **17 passed** (15 baseline + 2 MVP5-04 cases). MVP6 added
  no frontend tests per the explicit SR pattern across
  MVP6-02..07.
- `docker compose exec web npm run build` — compiled
  successfully. Final route table:
  ```
  ┌ ○ /                                     153 B           105 kB
  ├ ○ /13f/oracles-lens                     15.5 kB         196 kB
  ├ ○ /admin/13f                            7.43 kB         168 kB
  ├ ○ /admin/13f/filings                    6.07 kB         191 kB
  ├ ○ /admin/13f/holdings                   5.26 kB         163 kB
  ├ ○ /admin/13f/jobs                       8.02 kB         195 kB
  ├ ○ /admin/13f/managers                   2.06 kB         191 kB
  ├ ƒ /admin/13f/managers/[id]              2.71 kB         191 kB
  ├ ○ /admin/13f/readiness                  9.85 kB         194 kB
  ├ ○ /admin/13f/sync                       5.42 kB         190 kB
  ... (non-admin/13f routes unchanged)
  ```
  All eight Pre-MVP6-02 D1 routes are present and prerendered.

### Cumulative Index Page Reduction

The original `/admin/13f` page sat at ~3300 lines pre-MVP6.
Per-ticket reductions:

| After | Lines | Δ |
| ----- | ----- | - |
| Pre-MVP6 baseline | ~3300 | — |
| MVP6-01 Overview Hub | ~3300 | extracted Tier 2 + Tier 3 in place; behavior unchanged. |
| MVP6-02 Managers + Manager Detail | (Managers section replaced with link stub) | |
| MVP6-04 Filings | 2886 | Filings + Amendments + 2 drawers removed |
| MVP6-05 Holdings | 2646 | Holdings Coverage + Unresolved CUSIPs + Corporate Action Card + Drawer removed |
| MVP6-06 Jobs | 1895 | Jobs Card + 5 trigger Cards + Worker + EDGAR + Job Detail Drawer + 2 inline Dialogs (replaced by shared components) removed |
| MVP6-07 Readiness | **1125** | Data Readiness + Quality Reports + Needs Validation + Unknown Manager Priority + Quarters + Quarter Detail Drawer removed |

Net reduction: 3300 → 1125 lines (~66% of the original page
moved out). The remaining content on `/admin/13f` is the
Overview hub: KPI nav strip + Admin Tasks Card + Manual
Controls Card + shared dialog mounts.

### Route bundle sizes (kB First Load JS)

| Route | First Load |
| ----- | ---------- |
| `/admin/13f` Overview | 168 kB |
| `/admin/13f/managers` | 191 kB |
| `/admin/13f/managers/[id]` | 191 kB |
| `/admin/13f/sync` | 190 kB |
| `/admin/13f/filings` | 191 kB |
| `/admin/13f/holdings` | 163 kB |
| `/admin/13f/jobs` | 195 kB |
| `/admin/13f/readiness` | 194 kB |

## Decision-Gate Verification (Pre-MVP6-02 D1–D7)

| Decision | Status | Evidence |
| -------- | ------ | -------- |
| **D1** Eight routes total (Overview + 7 functional) | HELD | All eight Next.js routes ship and prerender (Overview + 6 functional list pages + 1 dynamic detail `managers/[id]`). `AdminPageLayout` nav has seven entries (Overview + 6 functional list pages), every one `shipped: true` post-MVP6-07. The Overview hub's KPI strip has 7 `<Link>` cards (one per nav entry minus self). |
| **D2** Three-step migration (extract → per-page lift → closing gate) | HELD | MVP6-01 extracted Tier 2 + Tier 3 in place; MVP6-02..07 each lifted one section + flipped the corresponding nav entry; MVP6-08 (this doc) is the closing gate. |
| **D3** Three-tier component extraction (UI primitives / admin13f layer / queries module) | HELD | `@/components/ui/*` primitives unchanged (Tier 1). `frontend/components/admin13f/` has 9 files (Tier 2): `Admin13FPrimitives` + 4 state components + `AdminPageLayout` + 3 dialog components. `frontend/lib/admin13f/queries.ts` is the single Tier 3 module. |
| **D4** First batch = MVP6-01 + MVP6-02; minimum operational shape per ticket | HELD | MVP6-01 shipped the shared layer first; MVP6-02 shipped Managers second. Every subsequent ticket explicitly recorded scope refinements deferring non-V1 features (no bulk edits, no quarter filter where backend missing, etc.). |
| **D5** Four empty-state reason codes + toast vs alert convention | HELD | `AdminEmptyState` exports the four canonical reason codes (`not-seeded` / `pipeline-not-run` / `filter-empty` / `readiness-blocked`). Toasts used for action results across every new route; inline `AdminErrorState` used for query errors. |
| **D6** Read-only vs destructive-action page tagging | HELD | Overview + Readiness are read-only (no destructive actions on the page). Managers / Sync / Filings / Holdings / Jobs all expose destructive admin actions through confirmation dialogs (`ManagerCikDialogs` / `ManagerTypeEditorDialog` / `JobPendingDialog` / `ReleaseStaleLockDialog` / Corporate Action confirm DrawerShell). |
| **D7** Eight-ticket sequence, soft MVP6-04 → MVP6-07 dep | HELD | All eight tickets shipped in execution-plan order. MVP6-07 deep-links to `/admin/13f/managers/{id}` (MVP6-02 dep) and the historical-backfill copy redirects to `/admin/13f/jobs` (MVP6-06 dep). No anchor fallbacks remain in `AdminPageLayout`. |

## Scope-Freeze Tally

All MVP6 scope-out items from the execution plan remain
deferred:

- **Track A2** Oracle's Lens Milestone 3 (quality / valuation
  overlay) — explicitly off-limits per the MVP6 plan.
- **Track A3 / A4 / A5 / A6** later Oracle's Lens milestones
  and V2 deferreds.
- **Track B** Pre-2023 historical backfill productionization
  — no investor demand signal, stays curated dry-run. The
  Historical Backfill Card on `/admin/13f/jobs` is the V1
  surface; it does not productionize the backfill itself.
- **Track C** Admin G1 (email alerts) and G9 (external
  ticketing) — Slack / Discord webhooks remain sufficient.
- **Track D** Watchlist V1 / Value Line ingestion /
  F-Score formalization — eligible to open as a Post-MVP6
  decision input.
- **Track E** `_HolderContribution` data-loader extraction,
  score-input sanity guards, `score_version` admin query
  param — stay deferred until their triggering condition
  appears.
- **MVP5-03 Phase 3** server-default flip — still gated on
  staging / prod PO sign-off. The frontend default has
  been `use_persisted_scores=true` since MVP4-07a; the API
  server default flip is the last-mover signal.
- **MVP5-03 Phase 4** `?persisted=0` retirement — post-Phase 3
  + one observation cycle.

Cumulative scope-freeze tally: **zero new backend / scoring
debt opened by MVP6**. Zero new Alembic migrations.
Zero new backend tests. Zero new frontend tests (per the
explicit SR pattern). Zero new pytest warnings.

## Post-MVP6 Decision Inputs

When MVP6-08 closes, the following candidates are ready for
the next decision gate (NOT committed yet — inputs to the
next gate, not outputs of this one):

1. **Track D Watchlist V1** — eligible to open since the
   admin surface is now operable across all 7 PRD §11.1
   pages.
2. **MVP5-03 Phase 3** server-default flip — still gated on
   staging / prod comparison + PO sign-off (no change).
3. **Track A2** Oracle's Lens Milestone 3 (quality + valuation
   overlay).
4. **MVP5-03 Phase 4** `?persisted=0` retirement — still
   gated on Phase 3 + one observation cycle.
5. **Track C G1 + G9** admin email + external ticketing — only
   if production observation surfaces a Slack / Discord
   coverage gap.
6. **Manual Controls + Tasks card UX refresh** — both still
   live on the Overview hub. A future ticket can revisit
   whether Manual Controls belongs on `/admin/13f/jobs`
   (it's a job-trigger surface co-located with the page
   that already has HB + BR), and whether the Tasks Card
   should adopt the four-reason `AdminEmptyState` pattern
   instead of inline copy.

## Review Pattern

Four reviewer prompts filed in
`docs/tasks/2026-05-12_13f-mvp6-review-prompts.md`:

- **Staff Engineer** — cross-ticket contract review (D1–D7
  hold, shared-component coupling, runJob duplication
  pattern, query module invalidation correctness, Next.js
  15 params-Promise adoption).
- **Financial Data Product Reviewer (13F Domain SME)** —
  admin workflow correctness (CIK review loop, manager_type
  editor evidence threshold, corporate-action confirm
  semantics, batch reparse + historical backfill copy
  accuracy).
- **Product Owner** — closing-gate sign-off, scope-freeze
  tally confirmation, Post-MVP6 candidate ranking, MVP7
  decision gate timing.
- **Frontend / UX (optional)** — eight-route navigation
  flow, `AdminEmptyState` reason code coverage, drawer +
  dialog ARIA semantics, deep-link integrity (priority Card
  → manager detail, Quarter Detail drawer → suggested
  actions).

## Recommendation

**MVP 6 is closed as shipped.** The seven PRD §11.1 admin
pages exist and are reachable. The Overview hub is a thin
nav surface as Pre-MVP6-02 D4 specified. Pre-MVP6-02 D1–D7
all held against shipped code with no silent deviations.
Verification baseline (781 backend / 17 frontend / 0
warnings) is met.

The four-role review can run in parallel and is not blocking
for declaring MVP6 done — it is a quality gate. Any
follow-up items surfaced by reviewers should be filed as
backlog tickets, not retro-fitted into MVP6.

The next decision gate is MVP7. Inputs are listed above
under "Post-MVP6 Decision Inputs"; the PO ranks them and
opens the chosen first ticket. Track D Watchlist V1 and
MVP5-03 Phase 3 are the two natural front-runners — the
former because the admin surface that gated it is now
operable, the latter because it's the GA gate that's been
waiting since MVP5-07.

## Review Outcomes (2026-05-12)

Two of the four review roles ran against shipped code:

### Staff Engineer — APPROVE-WITH-FIXES

All 10 cross-cutting items PASS or FLAG (no FAIL). Two FLAGs
landed as code-level fixes in the same MVP6-08 review-fix
commit:

- **FLAG #8** — `lockKeyForPayload` was duplicated on three
  routes with non-byte-identical formatting (single-line vs
  multi-line `if`s, mismatched return-type annotations).
  Extracted to `frontend/lib/admin13f/lockKey.ts`; the three
  route files now import the single canonical helper.
- **FLAG #5** — `AdminErrorState` was unused on
  `/admin/13f/jobs` and `/admin/13f/readiness` (D5 convention
  consistency gap). Adopted on the two primary tables (Job
  Runs on jobs route, Quarters on readiness route) with
  `error` + `onRetry` + custom `title` wiring.

### Financial Data Product Reviewer (13F SME) — 2 BLOCKs + 3 MVP7 FLAGs

Both BLOCKs landed in the same MVP6-08 review-fix commit:

- **BLOCK Item 3** — Corporate Action confirm DrawerShell on
  `/admin/13f/holdings` told the operator to "Provide
  `prior_mapping_id` to supersede" but the form had no input
  for the value. The backend service accepts the field
  (`thirteenf_corporate_action.py:22`); the affordance gap
  was a copy-vs-form mismatch. Fix: added a new
  `caPriorMappingId` state + form input
  (`#ca-prior-mapping-id`), threaded into the confirm payload
  with `prior_mapping_id: Number(...)`, gated the Confirm
  button (disabled when overlaps detected but field empty),
  auto-populated when the preview returns exactly one
  overlapping mapping. Warning copy rewritten to surface the
  overlapping IDs inline.
- **BLOCK Item 8** — NT filers MetricTile on
  `/admin/13f/readiness` had `detail="reported elsewhere"`,
  but the IA split left no other admin surface for NT filer
  detail. Replaced with `detail="NT-HR amendment expected"`,
  which does not promise a destination.

MVP7-backlog FLAGs (filed, not landed in MVP6):

- `manager_type` editor: make `note` required when
  transitioning away from `unknown`; thread `evidence_json`
  from the dialog to the audit row.
- Historical Backfill pre-2023: add per-filer caveat block
  for Kahn Brothers (CIK `0001039565` — values in dollars
  per CLAUDE.md) so operators recognize reconciliation
  warnings as True Positives.
- Batch Reparse: promote `missing_raw_infotable_count > 0`
  from a MetricTile to an amber banner with explicit
  skip-count language; align the generic `warnings` array
  copy with the actual skip behavior.
- Quality Reports: V2 per-finding drilldown panel (replaces
  the raw JSON dump in the Quarter Detail drawer).

NEEDS-PRODUCTION-DATA:

- SME Item 4 (Kahn dry-run output shape) — requires
  staging/prod environment with linked CUSIPs + Kahn filings
  in scope. Defer alongside MVP5-03 Phase 3.

### Frontend / UX — optional, not run

Skipped in favor of consolidating the Staff Engineer + SME
fixes. Browser-interaction items (Tab order in drawers,
focus-return on Escape, deep-link click flows) can run
during MVP7 admin smoke-testing without re-opening the MVP6
gate.

### Product Owner — pending

PO sign-off on the MVP6 closure is the gating output. The
two BLOCKs + two FLAGs from the engineering reviews are now
addressed in shipped code; PO reviews the consolidated
state and ranks Post-MVP6 candidates.

### Final verification after review-fix commit

- `docker compose exec web npm run lint` → No ESLint
  warnings or errors.
- `docker compose exec web npm run build` → compiled
  successfully. Bundle deltas vs pre-fix:
  `/admin/13f` 7.43 → 7.19 kB (lockKey lifted out),
  `/admin/13f/filings` 6.07 → 5.97 kB,
  `/admin/13f/holdings` 5.26 → 5.38 kB (new input + state),
  `/admin/13f/jobs` 8.02 → 8.08 kB (AdminErrorState added,
  lockKey lifted out),
  `/admin/13f/readiness` 9.85 → 10.1 kB (AdminErrorState +
  NT copy edit + lockKey lifted out),
  `/admin/13f/sync` 5.42 → 5.32 kB.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec api pytest -q` → 781 passed, 0
  warnings.
