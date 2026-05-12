# Post-MVP4 Forward Roadmap

Compiled 2026-05-12 after MVP4 end-to-end review closed. This is a
**survey doc**, not a commitment. Items are sourced from existing
PRDs / plans / review backlog; nothing here adds new scope beyond
what's already approved or filed as backlog.

Pointer doc only — when an item is opened, the owner creates a real
`docs/tasks/YYYY-MM-DD_*.md` task file and removes the line here.

## Source Documents

- `docs/prd/13f_automation_and_resilience_prd.md` — 13F backend
  automation PRD (§17 MVP delivery plan stops at MVP 3, already
  shipped).
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` — Oracle's
  Lens dashboard product plan (§14 Milestone 1-5; §17 V1.1 / V2
  additions).
- `docs/plans/13f_admin_data_operations_dashboard_product_plan.md`
  — Admin dashboard product plan (§20 MVP 1A-5; §22 gap register).
- `docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`
  — MVP4 verification log including the eight-reviewer outcome
  log (accepted-deferred + rejected items).
- `docs/13f/mvp4-reviews.md` — raw reviewer feedback.
- `docs/prd/value-pilot-prd-v0.1.md` + `docs/prd/watchlist/watchlist-v1.md`
  — non-13F product surfaces.

## Naming Note

"MVP N" is overloaded across at least three parallel tracks:

- **13F automation backend MVPs** (§17 of the automation PRD) — 1A,
  1B, 1C-1, 1C-2, 2, 3. All shipped.
- **Oracle's Lens scoring "MVP4"** (our internal track that just
  closed) — MVP4-01 through MVP4-12.
- **Admin Data Operations Dashboard MVPs** (§20 of the admin plan)
  — admin MVP1A through admin MVP5. Independent numbering from
  the scoring track.

This doc uses "Track A / B / C / D / E" labels instead of "MVP N"
to avoid ambiguity. "MVP5" specifically still refers to the
next-up scoring track milestone (Track A1 below) because that's
the user-facing label we've been using in conversation.

---

## Track A — Oracle's Lens Scoring (the "MVP5+" track)

### A1. MVP5 review backlog (next-up after MVP4)

From `2026-05-12_13f-mvp4-end-to-end-verification.md` Eight-Reviewer
Pass Outcome Log.

**Critical (GA-blocking):**

- **Wire `derive_manager_signal_profile` into the live scoring
  path.** SME #6 #6: `resolve_manager_type(manager,
  derived_profile=None)` at `signal_weighted_score.py:510`
  hardcodes the behavior-tier to None, so the MVP4-11 three-tier
  precedence collapses to two tiers in production. Long-term
  fundamental managers who haven't been admin-typed get the 0.60
  unknown fallback instead of 1.00; high-turnover managers get 0.60
  instead of 0.30. Must wire before any investor-facing GA.
- **Class B caveat exclusion (narrow scope — amendments only).**
  Holder contributions from filings with `AMENDMENTS_PENDING` or
  `AMENDMENT_FAILED` should be excluded from the score, not just
  caveat-flagged on the existing snapshot. PO #3 / PO #4 both
  agreed. Verify whether the `cusip_mapping_status == "linked"`
  eligibility filter already covers the unresolved-CUSIP case;
  if yes, MVP5 Class B is amendments-only. Defer NT / combination
  / confidential omission to V2.

**Formula reconciliation cluster (one ticket):**

- Flip `/api/v1/oracles-lens` `use_persisted_scores` server default
  from `False` to `True` (TL #1 #5).
- Define and execute the `?persisted=0` retirement condition:
  formula reconciliation complete + one full scoring cycle with no
  ranking divergence + PO sign-off on a side-by-side comparison
  report (PO #3 #3). The MVP5 ticket's first deliverable should be
  a lightweight comparison utility, not the deletion.
- Document the action-magnitude inversion in the reconciliation
  task: dashboard has `new=+0.10, add=+0.20`; persisted has
  `new=+0.20, add=+0.10`. Normalize toward persisted (a new
  position is more decisive than an add). SME #6 #1.

**Frontend hardening pass (one ticket — items 2/3/5/7 from FE #8):**

- `DEMOTION_REASON_LABELS` friendly map in
  `frontend/lib/oraclesLens.js` so `PARTIAL_COVERAGE` etc. render
  as readable strings. Resolves a11y screenreader concern
  (FE #8 #3 + #7b).
- Surface every active caveat in the drilldown (not just the
  tier-winning ones); pairs with the SME #6 #5 backend follow-up
  if any UI seam still drops codes.
- Empty-state copy refinement on `/admin/13f` Unknown Manager
  Priority Card (FE #8 #5): directional hint on "no backfill yet"
  state; positive framing on "no unknowns" state.
- Slide-out panel A11y on `oracles-lens/page.tsx`: `role="dialog"`,
  `aria-modal`, focus trap, restore focus on close (FE #8 #7a).
- `overflow-x-auto` wrapper on the admin priority Table for
  narrow viewports (FE #8 #7c).
- Persisted-mode retirement comment in the page source so the
  cleanup is obvious when the legacy path goes away (FE #8 #1
  follow-up).

**Manager-type editor (one ticket — closes the MVP4-07b loop):**

- Lightweight editor on the manager detail page: one dropdown
  showing the canonical 8-value taxonomy with the current value
  pre-selected and a save action that writes
  `InstitutionManager.manager_type`. Priority queue rows
  deep-link to it via `/admin/managers/{id}` (no stub routes
  before this exists per FE rejection R6).

**Naming/docs pass (one ticket):**

- Rename `anti_crowding_factor` to a "high-quality manager
  agreement factor" (SME #6 #3). Update §7.11 doc + dashboard
  tooltip + variable names.
- Architecture note in `CLAUDE.md`: "ORM upsert for idempotent
  rewrites; IntegrityError translation for exclusive-lock guards"
  so future contributors don't re-litigate (TL #1 #2 follow-up,
  TL #2 backlog #4).
- Record SME-vs-SME tier resolution for
  `PRE_2023_PRE_HISTORY_UNAVAILABLE` (kept at medium per SME #6
  reasoning) so the question isn't reopened at GA.

### A2. Oracle's Lens Milestone 3 — Quality and Valuation Reference Overlay

Source: `13f_oracles_lens_dashboard_product_plan.md §14 M3`.

- Owner earnings yield where available.
- Piotroski / ROTC / net margin / debt overlay (uses existing
  `metric_facts`).
- Selected valuation reference + discount-to-reference strip.
- Valuation reference type and confidence display.
- Caution flags panel in drilldown (already partly built; M3
  adds the valuation flags).
- "Unavailable" reason display.

Scope estimate: backend enrichment + frontend columns. Depends on
the Value Line / valuation overlay ingestion track being live.

### A3. Oracle's Lens Milestone 4 — Visual Radar

Source: `§14 M4`.

- Bubble chart or compact cluster visualization.
- Tooltip with holder actions.
- Responsive QA pass.

Scope estimate: frontend visualization only.

### A4. Oracle's Lens Milestone 5 — Historical Expansion

Source: `§14 M5`.

- EOD price backfill for 13F-linked stocks.
- Period timeline.
- Historical snapshot mode for available periods.

Scope estimate: data pipeline + API + frontend.

### A5. V1.1 / V2 additions (`§17`)

- Value Line quality overlay.
- Valuation reference.
- Expanded historical price context.

### A6. Deferred indefinitely (`§17`)

- Actual guru cost basis.
- AI moat score.
- Full historical time-machine replay.
- Real-time market behavior.

---

## Track B — 13F Automation Backend (PRD §17)

13F automation PRD §17 (MVP 1A → 3) is fully shipped. Remaining
items are edge-case backlog:

- **Pre-2023 historical backfill productionization** — gated on a
  PO demand signal ("does any investor data ask require >3 years
  of historical depth?"). The dry-run path works (MVP4-08
  confirmed); the question is whether to lift the production gate.
  Stays at "curated dry-run only" indefinitely unless the demand
  signal materializes.
- **PRD §20 open questions** still in carryover (especially V2
  amendment normalization rules). No active task.

---

## Track C — Admin Data Operations Dashboard (Admin Plan §20)

Admin MVP1A → MVP4 are COMPLETED. Two gaps remain in admin MVP5:

- **G1 — Email alerts.** Slack and Discord webhook alerts are
  shipped; email is not. Source: `admin plan §20 MVP5` +
  `§22 gap register G1`.
- **G9 — External ticket creation for engineering-only failures.**
  In-app admin tasks are shipped; external (PagerDuty / Linear /
  similar) ticket creation is not. Source: `§22 G9`.

Plus closing the MVP4-07b loop (see Track A1 manager-type editor
item — overlaps with the admin track since the editor lives on
the manager detail page).

---

## Track D — Non-13F Product Surfaces

These are filed PRDs with no active 13F-track owner.

- **Watchlist V1** — `docs/prd/watchlist/watchlist-v1.md`. Sidebar
  + main table + Margin of Safety column already specified; data
  model uses existing `stock_pools` / `pool_memberships` /
  `stock_prices` / `metric_facts`. Needs its own decision gate and
  task track; not blocked on 13F.
- **Value Line / valuation overlay ingestion** — `value-pilot-prd-v0.1.md`
  Appendix B (normalization layer) + the Value Line template
  parsing scope. Required for Track A2 (Oracle's Lens M3
  valuation reference); could land as a parallel ingestion track.
- **Piotroski F-Score** — `docs/plans/piotroski_f_score_calculation_plan.md`.
  Plan exists; needs PO decision on whether to formalize as a
  track or fold into Track A2 as one of the overlay columns.
- **Top-level ValuePilot v0.1 PRD foundations** — metric facts /
  normalization layer contracts that underpin Watchlist and the
  valuation overlay. Foundational, not user-facing on its own.

---

## Track E — Cross-Track Engineering Debt

Items that don't belong to any single feature track:

- `_HolderContribution` data-loading abstraction
  (`signal_weighted_score.py` → dedicated loader module). TL #2
  backlog #1. Reasonable trigger: the 4th scoring algorithm
  needing more than two new fields on the dataclass.
- Score-input sanity guards / data-integrity safety nets (e.g. a
  generic `min(weight, Decimal("1.0"))` clamp at calculation
  sites). Scope from observed corruption cases, not theoretical
  ones (replaces the rejected SME #5 #7 Kahn Brothers BLOCK).
- `admin_router.get("/oracles-lens")` `score_version` query param
  for shadow-compute reads — YAGNI for now; add when a shadow
  pipeline lands (TL #1 #1 alt-fix, rejected for current scope).

---

## Suggested Sequencing Decisions (open questions for the PO)

1. **PO demand signal on pre-2023 backfill** — answers whether
   Track B's only remaining item enters MVP5 or perpetually
   defers.
2. **MVP5 critical ordering** — wire behavior-derived manager_type
   path (Track A1 critical) vs Class B amendment exclusion (Track
   A1 critical). Both must land before GA; order matters for
   sprint planning.
3. **Watchlist parallelism** — open Track D Watchlist V1
   immediately after MVP5 opens (parallel to Track A2), or stack
   it after Oracle's Lens Milestone 3 lands? Frontend and backend
   work are largely independent.
4. **Track C admin gaps** — fold G1 email + G9 ticket creation
   into MVP5 scope or into a separate admin-hardening track?
