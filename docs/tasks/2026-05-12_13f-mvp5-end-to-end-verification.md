# 13F MVP 5 End-to-End GA Readiness Verification

## Goal / Acceptance Criteria

Close MVP 5 (Oracle's Lens V1 GA-readiness track) with a
Docker-based verification pass across the six MVP5 sub-tasks
and the four-role review pattern, and define the **conditional
GA gate** that opens once the PO completes the MVP5-03 Phase 3
sign-off path on production data.

Acceptance criteria:

- Alembic migrations apply cleanly to head; latest revision is
  the MVP5-05 `institution_manager_type_review_events` table
  (`20260512130000`).
- Backend MVP5 targeted suites pass.
- Full backend unit suite passes with **zero warnings** (the
  MVP4-10 acceptance bar must not regress).
- Frontend lint, `node --test lib/oraclesLens.test.js`, and
  production `npm run build` all pass.
- The MVP4-12 verification baseline (754 backend / 15 frontend)
  is met or exceeded.
- Every MVP5-01 through MVP5-06 task spec is closed against
  shipped code with passing tests.
- The four follow-up trackers in the MVP5-03 task spec
  (`Phase 3 Sign-Off Tracker` + `Phase 4 Retirement Tracker`)
  remain explicit work items, NOT silently elided by this gate.
- Scope-freeze tally for MVP5 is **zero new debt** — every
  Track A2 / B / C / D / E item from
  `2026-05-12_post-mvp4-roadmap.md` stays deferred.

## Scope In

- Verification-only task log.
- Docker verification commands and results.
- Contract checklist for MVP5-01 through MVP5-06.
- Phase 3 / Phase 4 GA gate definition.
- Three review roles + one optional, prompts filed in
  `docs/tasks/2026-05-12_13f-mvp5-review-prompts.md`.
- Minimal fixes only if verification exposes a regression.

## Scope Out

- New feature work.
- Schema changes unless verification finds a blocker.
- Server-default flip for `use_persisted_scores` — that's
  Phase 3 of MVP5-03 and explicitly gated on PO sign-off.
- `?persisted=0` retirement — Phase 4, post-observation.
- Track A2 (valuation overlay), Track B (pre-2023 backfill),
  Track C (admin G1/G9), Track D (Watchlist),
  Track E (engineering debt). All remain deferred per the
  Post-MVP4 roadmap.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7 (Oracle's
  Lens scoring vocabulary), §17 (delivery plan).
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7
  (V1 score surface), §14 (milestone plan), §17 (V1.1 / V2
  additions).
- `docs/tasks/2026-05-12_13f-mvp5-execution-plan.md` — MVP5
  scope.
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` — track
  organization and deferral rationale.
- `docs/13f/mvp4-reviews.md` — eight reviewer passes that
  produced the MVP5 backlog.

## Tests First

This is a verification gate, not a feature. The MVP5-01..06
per-task test suites are the source of truth unless a failing
gap is discovered.

## Docker Verification Commands

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_01_wire_behavior_manager_type.py tests/unit/test_13f_mvp5_02_amendment_exclusion.py tests/unit/test_13f_mvp5_03_formula_comparison.py tests/unit/test_13f_mvp5_05_manager_type_editor.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run build`

## MVP 5 Contract Checklist

- [x] **MVP5-01** Wire behavior-derived manager_type into live
      scoring path. `c3887be`. Three-tier precedence
      (admin → behavior → fallback_unknown) now real in
      production; lazy per-manager profile cache amortizes the
      cost.
- [x] **MVP5-02** Exclude amendment-blocked holder
      contributions. `53a9f2f`. Class B narrow scope
      (amendments only); `(contributions, excluded)` tuple
      partition; new `excluded_holder_count` /
      `excluded_holders` fields on score explanation; floor
      check re-validates included count; CUSIP-unresolved
      verified already covered by
      `cusip_mapping_status == "linked"`.
- [x] **MVP5-03 Phase 1 + 2** Formula reconciliation utility +
      action-magnitude normalization. `c7d525c`. New
      `GET /api/v1/admin/13f/oracles-lens/formula-comparison`
      admin endpoint (pure function + session wrapper);
      dashboard `_position_signal_weight` action magnitudes
      aligned with `constants.ACTION_ADJUSTMENT_*`
      (`new=+0.20`, `add=+0.10`, `reduce=-0.10`, new
      `exit=-0.20`). **Phase 3 + 4 explicitly deferred**
      pending PO comparison run.
- [x] **MVP5-04** Frontend trust + accessibility hardening.
      `06232ea`. `DEMOTION_REASON_LABELS` +
      `EXCLUSION_REASON_LABELS` maps; `excludedHolders`
      normalizer; friendly-label drilldown render; ARIA
      dialog + focus management on the slide-out;
      admin Card empty-state copy + overflow-x-auto.
- [x] **MVP5-05** Manager-type editor. `2f7673b`. New
      migration `20260512130000` creates
      `institution_manager_type_review_events`; new ORM model
      + service + two admin routes (PATCH + history GET);
      inline Dialog editor on managers section; MVP4-07b
      priority Card name now deep-links via
      `#manager-row-{id}` anchor.
- [x] **MVP5-06** Documentation + naming cleanup. `78749ad`.
      `anti_crowding_factor` → `quality_agreement_factor`;
      CLAUDE.md write-conflict-handling note (upsert vs
      IntegrityError two-pattern rule); plan §7.13.1
      "Caveat Tier Resolution" recording the SME-vs-SME
      decision on `PRE_2023_PRE_HISTORY_UNAVAILABLE` →
      `_MEDIUM_CAVEATS`.

## Verification Results

- `docker compose exec api alembic upgrade head` — at head
  `20260512130000` (MVP5-05 manager_type review events). No
  pending migrations.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_*.py`
  (four targeted suites) — **26 passed**.
- `docker compose exec api pytest` — **781 passed, 0
  warnings**. The MVP4-10 conftest savepoint hardening still
  holds; no new SAWarning introduced by MVP5.
- `docker compose exec web npm run lint` — no ESLint warnings
  or errors.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  — **17 passed** (15 baseline + 2 new MVP5-04 tests).
- `docker compose exec web npm run build` — compiled
  successfully; no Suspense / `useSearchParams` regression.

Cumulative test growth across MVP5 (from per-task verification
logs and `git log`):

- MVP4 closing baseline (after the eight-reviewer fixes):
  755 backend / 15 frontend.
- After MVP5-01 wire behavior manager_type: 759 (+4 backend).
- After MVP5-02 amendment exclusion: 764 (+5 backend).
- After MVP5-03 Phase 1 + 2 formula reconciliation: 772
  (+8 backend, all comparison-utility tests).
- After MVP5-04 frontend trust hardening: 772 backend
  unchanged; **17 frontend (+2 new MVP5-04 tests).**
- After MVP5-05 manager-type editor: 781 (+9 backend).
- After MVP5-06 naming + docs cleanup: 781 unchanged;
  rename only, no new tests.

MVP5 totals: **+26 backend tests / +2 frontend tests** since
the MVP4 baseline.

## Decision-Gate Verification (MVP5 internal)

| Decision | Status | Evidence |
| -------- | ------ | -------- |
| GA-blocking correctness 1: behavior-derived manager_type wired in live scoring | CLOSED | MVP5-01 + `signal_weighted_score.py:510` no longer hardcodes `derived_profile=None`; three-tier precedence test pinned. |
| GA-blocking correctness 2: amendment-blocked holders excluded from score aggregate | CLOSED | MVP5-02 `_contributions_for_stock` returns `(contributions, excluded)`; conviction + distinctive consume the included list only; eligibility floor re-validates included count. |
| Formula reconciliation cluster (action-magnitude normalization + comparison utility shipped) | CLOSED FOR PHASES 1+2 | MVP5-03 commit. Phase 3 (server-default flip) **OPEN — gated on PO comparison-report sign-off**. Phase 4 (retirement) **OPEN — post-observation**. |
| Frontend trust + accessibility pass | CLOSED | MVP5-04 commit. Persisted-mode badge label rename explicitly deferred per FE rejection R5 (UX consultation required). |
| Admin classification loop closure (priority Card → editor) | CLOSED | MVP5-05 commit. Anchor-link from priority Card to inline Dialog editor; manager-type changes write a row to the new audit table. |
| Naming + docs cleanup | CLOSED | MVP5-06 commit. `anti_crowding_factor` rename + CLAUDE.md two-pattern note + plan §7.13.1 PRE_2023 tier resolution. |

## Scope-Freeze Tally

All MVP5 scope-out items from the execution plan remain
deferred:

- **Track A2** Oracle's Lens Milestone 3 (quality / valuation
  overlay) — explicitly off-limits until MVP5-07 closes.
- **Track A3 / A4 / A5 / A6** later Oracle's Lens milestones
  and V2 deferreds.
- **Track B** Pre-2023 historical backfill productionization
  — no investor demand signal, stays curated dry-run.
- **Track C** Admin G1 (email alerts) and G9 (external
  ticketing) — Slack / Discord webhooks remain sufficient.
- **Track D** Watchlist V1 / Value Line ingestion /
  F-Score formalization — revisit after MVP5-03 Phase 3 lands.
- **Track E** `_HolderContribution` data-loader extraction,
  score-input sanity guards, `score_version` admin query
  param — stay deferred until their triggering condition
  appears.

Cumulative scope-freeze tally: **zero new debt opened by
MVP5**.

## Conditional GA Gate

**MVP 5 ships as conditionally GA-ready.** Six of the seven
sub-tasks are closed against shipped code at 781 / 0 warnings
on backend and 17 frontend tests passing. The remaining gate
is the MVP5-03 Phase 3 sign-off path, which is **not a code
change** — it is a product judgment that requires running the
Phase 1 comparison utility against the current active
production quarter and the PO accepting the ranking-divergence
report.

### Phase 3 Sign-Off Tracker (MVP5-03)

- [x] Phase 1 comparison utility deployed
      (`build_formula_comparison` + admin endpoint).
- [x] **Phase 1 utility contract validated against dev DB
      (2026-05-12).** Empty-state call returns the correct
      `{quarter: null, ...}` shape; synthetic 30-stock
      seeded scenario produces correct
      `TOP10_RANK_SWAP=1, MAGNITUDE_DIFF_25_PCT=2` flags with
      per-item attribution. **Real-data sign-off not run in
      dev** because all 4022 dev holdings are
      `cusip_mapping_status="pending_mapping"` → persisted
      scoring writes zero signal rows. See
      "MVP5-03 Phase 1 Validation Outcome" in the MVP5-03
      task file.
- [ ] Comparison report run against the current active
      production quarter (**blocked on staging/prod
      environment with linked CUSIPs + at least one
      persisted scoring backfill**). Output archived to
      `docs/tasks/YYYY-MM-DD_mvp5-03-comparison-report.md`.
- [ ] PO reviewed the comparison report. Sign-off recorded
      inline.
- [ ] Server default flipped from
      `use_persisted_scores: bool = Query(False)` →
      `Query(True)` in `read_oracles_lens`. One-line change.

### Phase 4 Retirement Tracker (MVP5-03)

- [ ] One full scoring cycle observed under the persisted
      default.
- [ ] No `TOP10_RANK_SWAP` flags on the current active
      quarter under the new default.
- [ ] `?persisted=0` debug flag retirement ticket filed and
      shipped (deletes the `useState` + `useEffect` block in
      `oracles-lens/page.tsx` per the inline retirement
      comment added in MVP5-04).

### What "GA-ready" means here

Investor-facing GA of Oracle's Lens V1 is approved once **both**:

1. All six MVP5 sub-tasks are landed (✓ as of `78749ad`).
2. The Phase 3 Sign-Off Tracker reaches all-checked state.

Until Phase 3 closes, the production read path serves the
**persisted scoring** via the frontend default
(`use_persisted_scores=true` in
`buildOracleLensQueryParams` since MVP4-07a) while the API
server default stays `False` for direct API consumers. This
is an intentional staging window — the frontend already runs
the GA configuration; the API default flip is the
last-mover signal.

## Review Pattern

Four reviewer prompts filed in
`docs/tasks/2026-05-12_13f-mvp5-review-prompts.md`:

- **Staff Engineer** — cross-task contract review (MVP5-01
  cache correctness, MVP5-02 partition + floor invariants,
  MVP5-03 comparison-utility math, MVP5-05 audit trail
  integrity).
- **Financial Data Product Reviewer (13F Domain SME)** —
  formula correctness post-action-magnitude normalization,
  behavior-path output sanity on production data,
  amendment-exclusion impact on rankings.
- **Product Owner** — final GA sign-off, comparison-report
  acceptance, Phase 3 server-default flip approval, MVP5
  scope-freeze tally confirmation, MVP6 candidate decision.
- **Frontend / UX (optional)** — confirm the MVP5-04
  hardening items render cleanly (friendly labels,
  excluded-holders drilldown, ARIA dialog semantics) and
  the MVP5-05 inline editor + deep-link work end-to-end.

## Recommendation

**Open the MVP5-03 Phase 3 sign-off process when a
staging/prod environment with linked CUSIPs is available.**

Pre-condition: PO obtains a production-shape comparison
report by running the Phase 1 utility against the current
active quarter (`GET /api/v1/admin/13f/oracles-lens/formula-comparison`)
in an environment where holdings have
`cusip_mapping_status="linked"` and at least one persisted
scoring backfill has populated `oracles_lens_signals`. Dev
DB is **not** suitable (validated 2026-05-12; all 4022 dev
holdings are `pending_mapping`).

If the staging/prod report shows `top10_swap_count == 0`
and `magnitude_diff_count` falls within an acceptable
threshold (PO judgment; suggest reviewing items individually
if any are flagged), sign off and ship the one-line
server-default flip as a hotfix-style ticket. If the report
flags material divergence, the formula reconciliation needs
deeper investigation before Phase 3 can close.

**Engineering must not flip the server default ahead of PO
sign-off** even if a low-volume dev / CI run looks clean —
the dev environment doesn't generate persisted signals so
any "clean" dev result is a false positive.

Pre-MVP6 candidates that should be triaged after Phase 3
closes:

1. **Track D Watchlist V1** decision gate — eligible to open
   once Phase 3 ships (Watchlist parallelism was conditioned
   on MVP5-03 closure in the execution plan).
2. **Track A2 Quality + Valuation Overlay** — Oracle's Lens
   Milestone 3 backlog.
3. **Phase 4 retirement** of `?persisted=0` — after the
   observation cycle.
4. **Track C G1 Email alerts** + G9 External ticketing —
   if production observation surfaces a Slack / Discord
   coverage gap.

None of these are committed; they are inputs to the next
decision gate, not outputs of this one.
