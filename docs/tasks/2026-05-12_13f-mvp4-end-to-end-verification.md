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
| D1 Oracle's Lens V1 scope (signal-weighted + conviction + caution + distinctive only) | CLOSED | The four score columns on `oracles_lens_signals` (`signal_weighted_consensus_score`, `conviction_score`, `caution_flags`, `distinctive_consensus_score`) are the only persisted metrics; Value Line overlay (D4) stays out. |
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
