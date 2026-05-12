# 13F MVP4 End-to-End Verification

## Goal / Acceptance Criteria

Close the MVP 4 delivery track with a Docker-based verification pass
across the eleven MVP4 sub-tasks (plus the 03b/07a/07b splits), and
confirm the decision-gate D1–D6 closure that opened the milestone is
still consistent with the shipped code.

Acceptance criteria:

- Alembic migrations apply cleanly to head; latest revision is
  the MVP4-08 dry-run column (`20260512120000`).
- Backend MVP4 targeted suites pass.
- Full backend unit suite passes with zero warnings (the three
  benign `SAWarning` events from MVP3 were the MVP4-10
  acceptance criterion and have stayed at zero).
- Frontend lint, `node --test lib/oraclesLens.test.js`, and
  production `npm run build` all pass.
- The MVP4 PRD §9 scoring surface (signal-weighted, conviction,
  caution flags, distinctive consensus) is end-to-end live —
  every score column is computed by a persisted backfill,
  surfaced through `/api/v1/13f/oracles-lens?use_persisted_scores=true`,
  and rendered in the Oracle's Lens dashboard with the
  persisted-mode badge + caveat panel.
- MVP4 decision-gate D1–D6 are individually verified against
  the shipped code, and the gate's Approval Checklist matches
  reality.
- No scope leakage into MVP 5 (Class B caveat exclusion of
  holder contributions, behavior-derived `manager_type` admin
  override workflow, NT page-level banner, and pre-2023
  historical backfill stayed deferred per the gate).

## Scope In

- Verification-only task log.
- Docker verification commands and results.
- Contract checklist for MVP4-01 through MVP4-11 (including
  03b/07a/07b splits).
- D1–D6 closure verification against shipped code.
- Minimal fixes only if verification exposes a regression.

## Scope Out

- New feature work.
- Schema changes unless verification finds a blocker.
- Class B caveat handling (still in MVP4-03 backlog).
- Formula reconciliation between in-memory dashboard and
  persisted MVP4-03 path (backlog).
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §6 (parse runs,
  audit history), §7 (Oracle's Lens scoring vocabulary —
  §7.2 / 7.9 / 7.10 / 7.11 / 7.12 / 7.13), §9 (Oracle's Lens
  user surface), §14 (indexes / locks), §17 (MVP4 scope).
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §6–§8
  scoring + UX surface.
- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D1–D6 +
  MVP4-01 pre-start conditions.

## Files Likely To Change

- `docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md` (this file).
- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` (Approval
  Checklist closure + Progress Notes line for MVP4 completion).

No code changes anticipated; this is the gate.

## Tests First

This is a verification gate, not a feature. The eleven per-task
test suites are the source of truth unless a regression is
discovered.

## Docker Verification Commands

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_score_schema.py tests/unit/test_13f_mvp4_base_primitives.py tests/unit/test_13f_mvp4_signal_weighted_score.py tests/unit/test_13f_mvp4_dashboard_persisted_scores.py tests/unit/test_13f_mvp4_conviction_score.py tests/unit/test_13f_mvp4_caution_flags.py tests/unit/test_13f_mvp4_distinctive_consensus.py tests/unit/test_13f_mvp4_unknown_manager_priority.py tests/unit/test_13f_mvp4_quality_report_source_linkage.py tests/unit/test_13f_mvp4_quality_rule_codes.py tests/unit/test_13f_mvp4_manager_taxonomy.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run build`

## MVP 4 Contract Checklist

Main path (sequential):

- [x] **MVP4-01** Oracle's Lens score schema + ORM.
      New `oracles_lens_signals` table, `score_version` enum, JobRun
      integration with `oracles_lens_score_backfill` job_type and
      lock_key prefix, ORM upsert by `(stock_id, report_quarter,
      score_version)`. (`9b33f9f`, gate fixups in `57c539a`.)
- [x] **MVP4-02** Holding streak + portfolio weight base primitives.
      Plan §7.3 / §7.4 / §7.10 — shared inputs consumed by MVP4-03
      and MVP4-04. (`fe31008`.)
- [x] **MVP4-03** Signal-weighted consensus score service (§7.2).
      Single-pass scorer reuses `_HolderContribution`; passenger
      conviction + distinctive backfill columns added by 04/06.
      (`e06b2c4`.)
- [x] **MVP4-03b** Dashboard endpoint reads persisted scores +
      caveat-class doc. `use_persisted_scores=true` opt-in flag on
      `/api/v1/13f/oracles-lens` returns plan-§7.2/§7.9/§7.11 scores
      from the canonical table; Class A vs Class B caveat
      distinction captured in code. (`943309d`.)
- [x] **MVP4-04** Conviction score service (§7.9). 5-component
      capped 0-100 score, `holding_streak_quarters` + `add_intensity`
      raw fields on the contribution dataclass to keep sub-4-quarter
      precision. (`21591b5`.)
- [x] **MVP4-05** Caution flags service (§7.13 + D3 caveat
      pass-through). Class A delta-only suppression preserved
      (`action_adjustment = 0`, snapshot bonuses still apply).
      (`eb4b0f3`.)
- [x] **MVP4-06** Distinctive consensus score (§7.11). Visible-but-off
      sort option in the dashboard per PO D3 clarification. (`7b2d000`.)
- [x] **MVP4-07a** Frontend persisted-scores wire-up.
      `buildOracleLensQueryParams` defaults to
      `use_persisted_scores=true`; persisted badge, coverage count
      and `confidence_demotion_reasons` drilldown surfaced. 15
      `oraclesLens.test.js` cases pass. (`3b038c9`.)
- [x] **MVP4-07b** Admin unknown-manager priority surface.
      New service + admin endpoint
      `/api/v1/admin/13f/oracles-lens/unknown-manager-priority`,
      ranking unknown-typed managers by
      `affected_signal_count` + `worst_score_confidence_observed`.
      New Card on `/admin/13f`. (`2cbdadd`.)

Parallel pre-MVP4-03 prerequisites (must complete before MVP4-03):

- [x] **MVP4-08** Backfill `quality_report` source linkage.
      `is_dry_run BOOLEAN NOT NULL DEFAULT FALSE` column added;
      historical-backfill writer stamps `is_dry_run` and
      `source_job_id`; admin dashboard filters dry-run by default.
      (`38714fb`.)
- [x] **MVP4-09** Shared rule_code constants module.
      `thirteenf_quality_codes.py` consolidates the five rule_codes
      across three services; tests pin the codes. (`c7f2f01`.)
- [x] **MVP4-10** Conftest savepoint hardening.
      `join_transaction_mode="create_savepoint"` recipe; three
      benign `SAWarning` events from MVP3 → 0. (`f230d6a`.)
- [x] **MVP4-11** Manager_type taxonomy reconciliation.
      Eight-value canonical taxonomy
      (`long_term_fundamental` / `value_concentrated` / `activist` /
      `quant` / `high_turnover` / `index_like` / `multi_strategy` /
      `unknown`); admin-set wins, admin=unknown falls back to
      behavior-derived; three source labels
      (`admin` / `behavior` / `fallback_unknown`). V1 conservative
      `multi_strategy=unknown=0.60` fallback noted as caveat.
      (`356da98`, decision staging in `6f9d0be`.)

Closing task:

- [x] **MVP4-12** End-to-end verification — this document.

## Verification Results

- `docker compose exec api alembic upgrade head` — at head
  (`20260512120000`, MVP4-08 dry-run column). No pending
  migrations.
- `docker compose exec api alembic current` — `20260512120000 (head)`.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_*.py`
  (eleven targeted suites) — **114 passed**.
- `docker compose exec api pytest -q` — **754 passed, 0 warnings**.
  The three benign `SAWarning` events from the MVP3 baseline
  (574→634) are still at zero, the MVP4-10 acceptance bar.
- `docker compose exec web npm run lint` — no ESLint warnings or
  errors.
- `docker compose exec web node --test lib/oraclesLens.test.js` —
  **15 passed** (the +1 MVP4-07a persisted-mode test is included).
- `docker compose exec web npm run build` — compiled successfully;
  no Suspense / `useSearchParams` regression (the MVP4-07a
  `window.location` workaround is still in effect).

Cumulative test growth across MVP4 (from the per-task verification
logs and `git log`):

- MVP3 closing baseline: 634 passed (after MVP3-09 readiness
  integration).
- After MVP4-01 schema: 645 (+11).
- After MVP4-02 base primitives: 660 (+15).
- After MVP4-03 signal-weighted: 681 (+21).
- After MVP4-03b dashboard endpoint: 691 (+10).
- After MVP4-04 conviction: 703 (+12).
- After MVP4-05 caution flags: 715 (+12).
- After MVP4-06 distinctive: 724 (+9).
- After MVP4-07a frontend wire-up: 741 (+17 backend; +1 frontend
  to 15 in `oraclesLens.test.js`).
- After MVP4-07b admin priority: 748 (+7).
- After MVP4-08 dry-run source linkage: 754 (+6).

(MVP4-09 and MVP4-10 land tests under existing suites and
register no net change in the totals above; MVP4-11 added the
`test_13f_mvp4_manager_taxonomy.py` suite that lands inside the
MVP4-03 / 07b totals because the latter consume it as a fixture.)

## Decision Gate Verification

| Decision | Status | Evidence in shipped code |
| -------- | ------ | ------------------------ |
| D1 Oracle's Lens V1 scope (signal-weighted + conviction + caution + distinctive only) | CLOSED | The four score columns on `oracles_lens_signals` (`signal_weighted_consensus_score`, `conviction_score`, `caution_flags`, `distinctive_consensus_score`) are the only persisted V1 score metrics; Value Line overlay (D4) stays out. Note (PO post-review precision): `oracles_lens_signals` also carries `add_intensity` and `holding_streak_quarters` as plan-§7.3/§7.10 base-primitive columns; these are reserved-null in V1 (the upsert path does not populate them) and exist to keep V2 scoring extensions append-only rather than alter-table. Not scope leakage — they are plan-mandated carriers, not score metrics. |
| D2 No pre-2023 production backfill | CLOSED | `DEFAULT_BACKFILL_START_QUARTER=2023-Q1`; pre-2023 without `dry_run` → 400; MVP4-08 stamps `is_dry_run` so dashboards never conflate the curated dry-run with production. |
| D3 V1 metric surface (with SME caveat-propagation rules) + distinctive visible-but-off | CLOSED | Class A delta-only suppression confirmed in MVP4-05 (`action_adjustment=0`, snapshot bonuses preserved); distinctive consensus is the visible-but-off sort option in the Oracle's Lens dashboard. |
| D4 Value Line overlay deferred | CLOSED | No Value Line code, schema, or UI was introduced across MVP4. |
| D5 Config module + separate component-audit table + score_version + manager_type taxonomy prerequisite | CLOSED | `app/services/oracles_lens/constants.py` is the config module (`SCORE_VERSION="v1.0"` + `MANAGER_SIGNAL_WEIGHTS`); `oracles_lens_signal_components` is the component-audit table; manager_type taxonomy reconciled in MVP4-11. |
| D6 Three new backlog tickets accepted (rule_code module / conftest hardening / quality_report source linkage) + IntegrityError as MVP4-01 design note | CLOSED | MVP4-09 / MVP4-10 / MVP4-08 all shipped; MVP4-01 chose ORM upsert per `(stock_id, report_quarter, score_version)` and documented that decision in its task file. |

## Scope-Freeze Tally

All MVP4-decision-gate scope-out items remain deferred:

- Class B caveat exclusion of whole holder contributions
  (pending/failed amendment, unresolved CUSIP, NT, combination
  report, confidential omission) — kept in the MVP4-03 backlog.
- Behavior-derived `manager_type` admin override workflow —
  deferred per MVP4-11 D5 V1-only caveat.
- Formula reconciliation between the legacy in-memory dashboard
  and the persisted MVP4-03 path — kept as a backlog ticket
  (the `use_persisted_scores=true` opt-in flag is the production
  default; the legacy path stays behind a `?persisted=0` debug
  param for one release cycle per MVP4-07a).
- NT page-level banner integration — still in MVP4-05 scope-out.
- Pre-2023 historical backfill — stays at "curated dry-run only"
  per D2.

Cumulative scope-freeze tally: **zero new debt opened by MVP4**.

## Recommendation

**MVP 4 is complete.** The Oracle's Lens V1 ranking surface is
live end-to-end (DB → backfill → endpoint → dashboard → admin
priority queue), all decision-gate D1–D6 items are CLOSED against
shipped code, and the test suite is clean at 754 passed / 0
warnings.

Next milestone gate (MVP 5 scope) can open. Pre-MVP5 candidates
that should be triaged from the deferred list above:

1. Class B caveat handling (the largest behavioral gap left in
   the scoring stack).
2. Formula reconciliation of the legacy in-memory dashboard
   path with the persisted backfill — required before the
   `?persisted=0` debug param can be removed.
3. Pre-2023 historical backfill productionization — only if an
   investor-data ask requires it; the dry-run path is currently
   the upper bound.

## Eight-Reviewer Pass — Outcome Log (2026-05-12)

Four reviewer roles ran two passes each (Tech Lead × 2, Product
Owner × 2, Domain SME × 2, Frontend/UX × 2). Prompts:
`docs/tasks/2026-05-12_13f-mvp4-review-prompts.md`. Raw reviews:
`docs/13f/mvp4-reviews.md`.

### Accepted and fixed in this verification commit

- **TL #1 #1** — `constants.py` `SCORE_VERSION` comment overstated
  read-side concurrent-version support. Tightened to make explicit
  that the compute side is version-aware but every read path
  resolves the constant; bumping the string is a one-way deploy.
- **TL #1 #6 (narrow scope)** — `HISTORICAL_BACKFILL_NEEDS_VALIDATION`
  is dual-use (rule_code + caveat). `base_primitives.py` and
  `caution_flags.py` no longer redeclare the string literal; both
  bind to the canonical `thirteenf_quality_codes` import. MVP4-09
  sentinel test extended to pin both bindings.
- **SME #5 #5 + SME #6 #5** — `confidence_demotion_reasons` was
  silently dropping non-tier-winning caveats. Fixed at
  `signal_weighted_score.py:_build_score_explanation`; new test
  `test_confidence_demotion_reasons_surface_low_and_medium_caveats`
  asserts a holder with both a low and medium caveat surfaces both
  in the drilldown.
- **SME #6 #7** — added a ratio-design comment at
  `compute_portfolio_weight` documenting that numerator and
  denominator come from the same filing in the same unit, so the
  Kahn Brothers `$-not-$K` unit error cancels in the division and
  no defensive cap is needed for this path.
- **PO #3 D1** — annotated the D1 row above to record that
  `add_intensity` and `holding_streak_quarters` are reserved-null
  base-primitive columns, not score metrics.

### Accepted and deferred to MVP 5 backlog

- **SME #6 #1** — dashboard `_position_signal_weight` has
  `new=+0.10, add=+0.20`, but `constants.ACTION_ADJUSTMENT_*` is
  `new=+0.20, add=+0.10`. The dashboard ordering predates MVP4 and
  is semantically inverted (a new position is more decisive than
  adding to an existing one). Roll into the **formula
  reconciliation** MVP5 ticket; the reconciler should normalize
  toward the persisted values.
- **SME #6 #6** — `resolve_manager_type(manager, derived_profile=None)`
  is called at `signal_weighted_score.py:510` with `derived_profile`
  hardcoded to `None`. The MVP4-11 three-tier precedence
  (admin → behavior → fallback_unknown) collapses to two tiers in
  production; `derive_manager_signal_profile` is unreachable in
  live scoring. The 0.60 fallback over-weights `high_turnover`
  managers and under-weights `long_term_fundamental` managers who
  haven't been admin-typed. **Wire the behavior path into the
  scoring call before any investor-facing GA.** MVP5 critical.
- **TL #1 #5 + PO #3 #3 + PO #4 #3** — flip the
  `/api/v1/oracles-lens` `use_persisted_scores` server default to
  `True`; define `?persisted=0` retirement condition (formula
  reconciliation complete + one full scoring cycle with no
  ranking divergence). Combine into the formula reconciliation
  MVP5 ticket. The retirement decision is product-owner sign-off,
  not automated pass/fail.
- **TL #2 backlog #1** — extract `_HolderContribution` data-loading
  out of `signal_weighted_score.py` into a dedicated
  `score_data_loader` once a fourth scoring algorithm needs more
  than two new fields on the dataclass. V1.x re-evaluation.
- **PO #3 #4 + PO #4 #4** — Class B caveat exclusion. SME-confirmed
  narrow scope: amendments (`AMENDMENTS_PENDING` + `AMENDMENT_FAILED`)
  in MVP5; verify whether CUSIP-unresolved is already excluded by
  the `cusip_mapping_status == "linked"` eligibility filter
  (likely yes); defer NT / combination / confidential omission to
  V2.
- **PO #3 bonus + FE #7 #6 + FE #8 #6** — manager-type editor on
  manager detail page. Single sprint; closes the MVP4-07b loop.
  Once it exists, the priority-queue rows deep-link to it.
- **FE #8 #2** — persisted badge label rename. Defer to a real UX
  consultation; "persisted" is jargon but admin-facing V1.
- **FE #8 #3** — `DEMOTION_REASON_LABELS` friendly map in
  `oraclesLens.js`. Lands with **SME #6 #5 follow-up** (drilldown
  surfaces all active caveats, not just tier-winning ones) as the
  MVP5 frontend hardening pass.
- **FE #8 #5** — empty-state copy refinement (directional hint on
  the no-backfill case; positive framing on the no-unknowns case).
- **FE #8 #7** — A11y: `role="dialog"` + `aria-modal` + focus trap
  on the slide-out panel; `overflow-x-auto` wrapper on the admin
  priority Table.
- **SME #6 #3** — rename `anti_crowding_factor` to
  "high-quality manager agreement factor" in §7.11 doc + tooltip.
  Naming-only; lands in the docs pass.
- **TL #2 backlog #4 / TL #1 follow-up** — architecture note in
  `CLAUDE.md` codifying "ORM upsert for idempotent rewrites;
  IntegrityError translation for exclusive-lock guards" so the
  next contributor doesn't re-litigate.

### Rejected (with reasons)

- **SME #5 #4 — move `PRE_2023_PRE_HISTORY_UNAVAILABLE` from
  `_MEDIUM_CAVEATS` to `_LOW_CAVEATS`.** REJECT. Direct contradiction
  between SME #5 (wants low) and SME #6 (validates medium). SME #6's
  argument prevails: pre-2023 history unavailability degrades the
  cross-quarter delta only; the current-quarter snapshot itself
  remains valid, so `low_confidence` would overclaim the loss.
  Medium is the correct tier. **Next:** capture this SME-vs-SME
  resolution in the MVP5 gate's caveat-tier section so the
  question doesn't get re-raised at GA.
- **SME #5 #7 — BLOCK on Kahn Brothers; require
  `min(weight, Decimal("1.0"))` cap before MVP5 opens.** REJECT the
  BLOCK. `compute_portfolio_weight` is ratio-based; numerator and
  denominator come from the same filing in the same unit; the
  1000× unit error cancels in the division (SME #6 verified). The
  defensive cap would protect against a *different* class of bug
  (e.g., a holding with `value_thousands > total_value`), not the
  Kahn Brothers scenario. **Next:** the ratio-design comment we
  added is the proportional fix; a generic `min(weight, 1.0)` cap
  as a data-integrity safety net is a separate MVP5 candidate
  ("score-input sanity guards") that should be scoped from
  observed corruption cases, not theoretical ones.
- **PO #4 D1 "REOPEN / SCOPE LEAK"** for the `add_intensity` and
  `holding_streak_quarters` schema columns. REJECT the REOPEN
  framing. Those columns are plan-§7.3/§7.10 base primitives,
  explicitly designed in MVP4-02 as reserved carriers for future
  V2 scoring components. They are not score metrics and were not
  smuggled past the gate. **Next:** PO #3's milder "annotation
  needed" framing is what we accepted above; PO #4's escalation is
  not warranted.
- **TL #1 #1 alt-fix — add `score_version` as an admin query
  param on the read endpoints to support concurrent v1.0 / v1.1
  reads.** REJECT. No current shadow-compute consumer wants this;
  YAGNI. **Next:** if MVP5 ships a shadow-compute pipeline, this
  becomes a one-line `Query(SCORE_VERSION)` add on
  `read_oracles_lens` plus a tiny test. Not worth opening now.
- **FE #8 #2 — rename "persisted" badge to "v1 scored" /
  "canonical score" now.** REJECT now. The V1 dashboard is
  primarily admin/operator-facing; "persisted" carries the right
  meaning for that audience. **Next:** real label work belongs in
  the MVP5 frontend hardening pass with a brief UX consultation,
  not a unilateral rename.
- **FE #7 #6 / FE #8 #6 — add a deep-link CTA on the admin
  priority Card now, pointing to a stub route or a future page.**
  REJECT. PO #4 explicitly aligned with the no-CTA design pending
  a real editor. A link pointing at a stub or 404 is a UX
  regression, not a fix. **Next:** ship the manager-type editor
  in MVP5 first; the CTA lands in the same task.
