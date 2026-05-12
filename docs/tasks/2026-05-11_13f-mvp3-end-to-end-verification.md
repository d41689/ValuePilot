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
- [x] MVP3-08 consolidated admin UI for batch reparse, corporate-action,
      and historical backfill (preview + confirm + needs-validation
      surface). Approved by Tech Lead and Product Owner during this
      end-to-end review.
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
- After MVP3-08 admin UI: 633 passed (+19).
- After end-to-end review followups (SME C1 regression test): 634 passed (+1).

## Review Verdicts

All three cross-task reviews complete. Action items applied or filed as
follow-ups below.

### Tech Lead (cross-task architecture)

**Verdict:** approved after one pre-merge fix.

One pre-merge action item (applied this session):
- **TL1 — rule_code casing normalization in `edgar_quality.py`.** The
  MVP3-02 `"value_unit_sanity"` literal was the only lowercase rule_code
  introduced in MVP3 scope (MVP3-06 and MVP3-07 both use UPPER_SNAKE
  module constants). Renamed to `"VALUE_UNIT_SANITY"`, extracted as
  module-level `VALUE_UNIT_SANITY_RULE_CODE` constant, both `report.add(...)`
  call sites updated, and the matching assertion in
  `tests/unit/test_13f_admin_dashboard.py:1536` updated. A future admin
  findings dashboard can now filter `quality_findings_13f.rule_code`
  without per-source casing logic. Pre-merge because renaming after
  prod rows accumulate would require a backfill migration.

All other cross-task surfaces — JobRun lock_key conventions, the
`IntegrityError → typed-error` translator pattern, advisory-lock helper
duplication, `ImpactSummary` vs plain-dict aggregation, `ValidationGate`
per-filing vs per-quarter signatures, the three benign `SAWarning` test
events — accepted as consistent / intentionally different / correctly
deferred per the Tech Lead's prior guidance. Cumulative scope-out
deferral was resolved by MVP3-08 shipping the consolidated admin UI.

### Product Owner (D1–D6 closure + next milestone)

**Verdict:** D1–D6 all CLOSED, MVP3-08 approved, recommend opening MVP4.

| Decision | Status | Key evidence |
| -------- | ------ | ------------ |
| D1 Historical backfill strategy | CLOSED | `DEFAULT_BACKFILL_START_QUARTER=2023-Q1`; pre-2023 without `dry_run` → 400; delegates to MVP1B ingestion; skips existing active filings; `HISTORICAL_BACKFILL_NEEDS_VALIDATION` findings stay open until gate passes. |
| D2 Dataroma legacy surface | CLOSED | All CUSIP enrichment call sites use `enrich_cusips_from_openfigi`; `enrich_from_dataroma` is a deprecated alias; MVP3-06 hardcodes `source='manual'`. |
| D3 Controlled + batch reparse | CLOSED | MVP3-04 shipped before MVP3-05; explicit `validation_gate` required; quarter-first sequencing recorded as inline supersede note in the decision gate; MVP3-08 disables the manager-scope UI panel per the supersede note. |
| D4 Corporate-action manual confirmation | CLOSED | `source='manual'` + `confidence='manual'` hardcoded; evidence + reason dual-guarded (Pydantic `min_length` + service `.strip()`); ownership_changes not mutated, only QualityFinding rows written. |
| D5 Filing-level value-unit override | CLOSED | MVP3-03 migration adds `filing_value_unit_overrides` + `filings_13f` pointer; `controlled_reparse_accession` is the only path that can flip override status to `applied`. |
| D6 Data integrity validation jobs | CLOSED | `quality_findings_13f` is the source of truth; alerts are notification surfaces only; at least one validation candidate (value-unit sanity) implemented. |

Cumulative scope-freeze tally is **zeroed**: MVP3-08 delivered the
backend HTTP endpoints + minimum-viable admin UI for batch reparse,
corporate-action mapping, and historical backfill — the three UI debts
opened during MVP3-05/06/07. No pre-2023 historical backfill needed
ahead of MVP4 unless an investor-data ask requires it; MVP4 PRD should
explicitly revisit D1 if so.

Recommendation: **open MVP4.**

### 13F Domain SME (financial-data correctness)

**Verdict:** mostly clean — two real concerns and one documentation
drift to address before declaring the audit-semantic surface complete.

Applied this session:
- **C1 — Amendment activation leak in controlled reparse (real bug).**
  `_do_ingest_holdings` activates a RESTATEMENT amendment and demotes
  the prior active filing as a side-effect of successful parse, and
  commits before `controlled_reparse_accession` runs the validation
  gate. Without intervention, a failed-validation amendment stays
  active. Fixed in `thirteenf_controlled_reparse._snapshot()` (now
  captures `filing_is_active_for_manager_period` and the prior
  active filing id for amendment candidates) and a new
  `_restore_active_filing` helper invoked on validation failure
  (demote-then-promote ordering to respect
  `uq_active_filing_per_manager_period`). New regression test:
  `test_controlled_reparse_validation_failure_restores_active_filing_for_amendment`.
  Containment held — only MVP3-04 single-filing reparse with a
  pending-amendment accession was exposed; MVP3-05 batch candidates
  require `is_active_for_manager_period=True` so the leak was not
  reachable via batch.
- **C3 — `_PRE_2023_BOUNDARY` naming drift (documentation).** Renamed
  to `_PRE_DOLLARS_BOUNDARY_REPORT_QUARTER` in
  `thirteenf_historical_backfill.py` with a multi-line comment
  explaining the report-quarter proxy is conservative versus PRD
  §7.2's canonical `accepted_at >= 2023-01-03` rule (the parser at
  `app/edgar/parsers/value_units.py` enforces the accepted_at form
  correctly; the proxy only governs the backfill-preview risk flag).
  No semantic change.

Deferred to a separate task:
- **C2 — Readiness service does not consume new MVP3-06/07 rule_codes.**
  `build_readiness_summary` ignores `QualityFinding13F` entirely;
  `_quarter_health` reads only the latest `QualityReport13F.status`,
  so a routine MVP3-02 `quality_check` can mask open MVP3-06/07
  warnings. Fix touches the user-facing readiness contract and the
  admin dashboard; it deserves its own review gate. Filed as
  `docs/tasks/2026-05-11_13f-mvp3-09-readiness-integration.md` (stub
  — not started; awaiting Tech Lead + PO go-ahead).

Minor observations recorded but not acted on this session: dry-run
quality reports conflate with real runs in dashboards (consider
`source_job_id` linkage); `_finalize_impact` shallow-copies the batch
aggregate dict; `confirm_corporate_action_mapping` commits inside the
service (consistent with siblings, currently fine).

## Residual Risk / Follow-up

Triaged with the three verdicts above:

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
- **Cumulative admin-UI deferral** — **RESOLVED** by MVP3-08; the
  three deferred surfaces (batch reparse trigger, corporate-action
  preview+confirm, backfill preview+confirm + needs_validation queue)
  now ship in the consolidated admin panel.
- **Test-fixture rollback warnings** — accepted by Tech Lead as
  structurally benign; not a merge blocker. Backlog item: restructure
  `conftest.py` to use `connection.begin_nested()` (savepoints) so
  service-level rollbacks don't reach the outer connection
  transaction. Touches all ~634 tests; defer to a focused conftest
  hardening task in the MVP4 backlog.
- **Pre-2023 boundary semantics** — **RESOLVED** as SME C3. The
  constant has been renamed `_PRE_DOLLARS_BOUNDARY_REPORT_QUARTER`
  with an explanatory comment that it is a conservative
  report-quarter proxy for PRD §7.2's canonical
  `accepted_at >= 2023-01-03` rule (the parser at
  `app/edgar/parsers/value_units.py` enforces the accepted_at form
  correctly).
- **Readiness service does not consume new MVP3-06/07 finding
  rule_codes** — SME C2. Filed as
  `docs/tasks/2026-05-11_13f-mvp3-09-readiness-integration.md` (stub).
  Touches the user-facing readiness contract and `_quarter_health`;
  needs its own Tech Lead + PO review before implementation begins.
