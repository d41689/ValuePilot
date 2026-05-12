# 13F MVP3 End-to-End Verification

## Goal / Acceptance Criteria

Close the MVP 3 delivery track with a Docker-based verification pass across
the seven MVP3 sub-tasks (Dataroma cleanup, quality findings, value-unit
override, controlled reparse, batch reparse, corporate-action mapping,
validation-gated backfill), and capture the cross-task review verdicts
needed before the next milestone opens.

Acceptance criteria:
- Alembic migrations apply cleanly to head.
- Backend MVP3 targeted suites pass.
- Full backend unit suite passes or any warnings are documented as
  pre-existing / benign.
- Frontend lint and production build pass (MVP3 introduced no frontend
  changes; this confirms there is no incidental regression).
- D1–D6 decision-gate items are individually closed and the gate's
  Approval Checklist matches reality.
- Three cross-task reviews (Tech Lead, Product Owner, Domain SME) are
  recorded with verdicts and action items before the next milestone
  enters scope.
- MVP 3 PRD §17 scope is confirmed complete without leaking into MVP 4.

## Scope In

- Verification-only task log.
- Docker verification commands and results.
- Contract checklist for MVP3-01 through MVP3-07.
- Recorded verdicts from three cross-task reviewer roles.
- Minimal fixes only if verification exposes a regression.

## Scope Out

- New feature work.
- Schema changes unless verification finds a blocker.
- Admin UI dashboard pages for MVP3 actions (explicitly deferred across
  MVP3-05/06/07; routed to a future MVP3-08 or MVP4 task).
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §6 (parse runs, audit
  history), §7 (holdings, value units, NT, query contract), §8 (CUSIP
  temporal mapping), §10 (readiness / quality), §14 (indexes / locks),
  §17 (MVP 3 scope), §19 (default backfill), §20 (open questions).
- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D1–D6.

## Files Likely To Change

- `docs/tasks/2026-05-11_13f-mvp3-end-to-end-verification.md`
- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` (Approval Checklist
  closure + Progress Notes line for MVP3 completion).

If verification finds a blocker, affected code/test files will be added
here before fixes.

## Tests First

This is a verification gate, not a feature. Existing test suites are the
source of truth unless a failing gap is discovered.

## Docker Verification Commands

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_value_unit_override_schema.py tests/unit/test_13f_mvp3_controlled_reparse.py tests/unit/test_13f_mvp3_batch_reparse.py tests/unit/test_13f_mvp3_corporate_action_mapping.py tests/unit/test_13f_mvp3_historical_backfill.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`

## Review Gates

Three cross-task reviews requested in parallel. Verdicts will be
appended to this document as they arrive.

- **Tech Lead** — cross-task contract / infrastructure consistency:
  QualityFinding rule_code naming, JobRun lock_key conventions,
  IntegrityError-translator duplication, advisory-lock helper
  duplication, ImpactSummary dataclass scope, ValidationGate signature
  drift, test-fixture rollback warnings, cumulative scope-out tally.
- **Product Owner** — D1–D6 closure, cumulative scope-freeze tally,
  next-milestone gate (MVP3-08 admin UI vs MVP4 scope opening).
- **13F Domain SME** — financial-data correctness: audit history
  retention, PRD §7.3 query contract, value-unit boundary semantics
  (accepted_at vs report_quarter), corporate-action no-mutation
  guarantee, ownership-change recompute closure, backfill resumability,
  advisory-lock derivation parity, daily-sync / amendment-policy
  intersection, cumulative readiness impact.

## MVP 3 Contract Checklist

- [x] MVP3-00 decision gate D1–D6 approved.
- [x] MVP3-01 legacy Dataroma surface cleanup / non-authoritative
      naming clarification.
- [x] MVP3-02 persisted quality reports + findings as the validation
      source of truth.
- [x] MVP3-03 filing-level `value_unit_override` schema + audit
      contract; manager-level `value_unit_override=infer` column
      preserved.
- [x] MVP3-04 controlled single-filing reparse contract with
      before/after impact summary and validation-gated activation.
- [x] MVP3-05 batch reparse jobs by quarter / manager, fan-out over
      MVP3-04 controlled reparse with aggregate impact summary and
      partial-failure isolation.
- [x] MVP3-06 CUSIP corporate-action temporal mapping admin backend
      (preview + confirm) with manual-only confirmation, evidence /
      reason required, ownership-change invalidation via quality
      findings (no silent mutation).
- [x] MVP3-07 validation-gated historical backfill: default 2023-Q1,
      pre-2023 dry-run gate, no overwrite of existing parse runs,
      per-quarter validation gate, `HISTORICAL_BACKFILL_NEEDS_VALIDATION`
      findings audit trail.
- [x] No MVP 4 scope included.

## Verification Results

- `docker compose exec api alembic upgrade head` — passed (no pending
  migrations; MVP3 introduced one schema migration in MVP3-03, already
  at head).
- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_value_unit_override_schema.py tests/unit/test_13f_mvp3_controlled_reparse.py tests/unit/test_13f_mvp3_batch_reparse.py tests/unit/test_13f_mvp3_corporate_action_mapping.py tests/unit/test_13f_mvp3_historical_backfill.py` — passed, 61 tests (MVP3-03 schema + MVP3-04 controlled reparse + MVP3-05 batch + MVP3-06 corporate-action + MVP3-07 backfill).
- `docker compose exec api pytest -q` — passed, 614 tests. Three benign
  `SAWarning: transaction already deassociated from connection` events
  during teardown of:
    - `tests/unit/test_13f_holdings_parser.py::test_duplicate_fingerprint_within_same_parse_run_raises` (pre-existing from MVP1B)
    - `tests/unit/test_13f_mvp3_batch_reparse.py::test_enqueue_translates_unique_index_race_into_scope_error` (deliberate rollback inside MVP3-05 IntegrityError translator)
    - `tests/unit/test_13f_mvp3_historical_backfill.py::test_enqueue_translates_unique_index_race` (same pattern, MVP3-07)
- `docker compose exec web npm run lint` — passed, no ESLint warnings
  or errors. (MVP3 introduced no frontend changes; this confirms no
  incidental regression.)
- `docker compose exec web npm run build` — passed.

Cumulative test growth across MVP3 (from the per-task verification
logs):
- MVP3-04 baseline: 574 passed.
- After MVP3-04 hardening: 574 passed.
- After MVP3-05 contract: 586 passed (+12).
- After MVP3-05 post-review: 588 passed (+2).
- After MVP3-06: 598 passed (+10).
- After MVP3-06 followup: 599 passed (+1).
- After MVP3-07: 614 passed (+15).

## Review Verdicts

Pending receipt. Verdicts will be appended in this section as the
Tech Lead, Product Owner, and Domain SME reviewers respond.

### Tech Lead (cross-task architecture)

_Pending._

### Product Owner (D1–D6 closure + next milestone)

_Pending._

### 13F Domain SME (financial-data correctness)

_Pending._

## Residual Risk / Follow-up

Carried forward from per-task reviews, to be triaged once the three
verdicts above land:

- **Shared advisory-lock helper** — `_cusip_lock_id` is duplicated
  between `app/services/cusip_enrichment.py` (MVP1B) and
  `app/services/thirteenf_corporate_action_mapping.py` (MVP3-06).
  MVP3-06 review accepted "defer until third caller adopts the
  pattern." Cross-task review may revisit this now that MVP3 is
  complete.
- **Shared `IntegrityError → typed-error` helper** — duplicated
  between `thirteenf_batch_reparse.py` and
  `thirteenf_historical_backfill.py`. Same defer-until-third-caller
  recommendation.
- **Shared rule_code constants** — three different MVP3 paths write
  `QualityFinding13F` rows with distinct rule_codes
  (`OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`,
  `HISTORICAL_BACKFILL_NEEDS_VALIDATION`, plus MVP3-02 rule codes).
  Consider a `thirteenf_quality_codes.py` constants module so the
  admin findings dashboard (future) can import a single source of
  truth.
- **Signed `holdings_rows_net_delta`** — MVP3-05 review deferred
  introducing a signed delta alongside the existing `abs`-value
  `holdings_row_count_delta`. Revisit when MVP3-08 admin UI surfaces
  the impact summary.
- **`'corporate_action'` `QualityReport13F.status` vocabulary value** —
  MVP3-06 review deferred adding a new status enum until a concrete
  filtering use case emerges. Same revisit window.
- **Cumulative admin-UI deferral** — three MVP3 tasks each deferred
  their admin UI surface (batch reparse trigger / corporate-action
  preview+confirm / backfill preview+confirm + needs_validation
  surface). Product Owner verdict will decide whether to scope
  MVP3-08 admin UI or open MVP4 with backend-API-only admin tools.
- **Test-fixture rollback warnings** — three `SAWarning` events
  during test teardown, all from deliberate-rollback paths in
  IntegrityError translators. Not a regression but a `conftest.py`
  hygiene item; could be silenced with a savepoint-style fixture
  wrapper if Tech Lead considers it noise.
- **Pre-2023 boundary semantics** — MVP3-07 uses
  `_PRE_2023_BOUNDARY=(2023, 1)` keyed on `report_quarter`. PRD §7.2
  describes the value-unit transition in terms of filing `accepted_at
  >= 2023-01-03`. Domain SME review should confirm the
  report-quarter approximation is acceptable for the dry-run gate
  (it is conservative: it triggers for Q4 2022 even when that filing
  was actually submitted after 2023-01-03 and would parse as
  dollars).
