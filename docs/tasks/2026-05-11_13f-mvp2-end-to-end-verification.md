# 13F MVP2 End-to-End Verification

## Goal / Acceptance Criteria

Close the MVP 2 delivery track with a Docker-based verification pass across schema, computation, user APIs, and Oracle's Lens UI.

Acceptance criteria:
- Alembic migrations apply cleanly to head.
- Backend 13F MVP2 schema, computation, holder aggregation, and manager changes API tests pass.
- Full backend unit suite passes or any failures are documented as pre-existing / unrelated.
- Frontend Oracle's Lens normalizer tests, lint, and production build pass.
- MVP 2 PRD §17 scope is confirmed complete without entering MVP 3.

## Scope In

- Verification-only task log.
- Docker verification commands and results.
- Contract checklist for MVP2-01 through MVP2-05.
- Minimal fixes only if verification exposes a regression.

## Scope Out

- New feature work.
- Schema changes unless verification finds a blocker.
- MVP 3 features: Dataroma, batch reparse, corporate action UI, cross-manager 13F-NT consolidation.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7.4: change analysis semantics.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2: Oracle's Lens signals, exclusion rules, and stock holder aggregation.
- `docs/prd/13f_automation_and_resilience_prd.md` §13: user-facing 13F API routes.
- `docs/prd/13f_automation_and_resilience_prd.md` §17: MVP 2 delivery scope.
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2: testable acceptance criteria.
- `docs/tasks/2026-05-10_13f-mvp2-decision-gate.md` D1-D6.

## Files Likely To Change

- `docs/tasks/2026-05-11_13f-mvp2-end-to-end-verification.md`

If verification finds a blocker, affected code/test files will be added here before fixes.

## Tests First

This is a verification gate, not a feature. Existing test suites are the source of truth unless a failing gap is discovered.

## Docker Verification Commands

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp2_ownership_changes_schema.py tests/unit/test_13f_ownership_changes_compute.py tests/unit/test_13f_user_api.py`
- `docker compose exec api pytest -q`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web node --test lib`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`

## Review Gate

Tech Lead should review:
- MVP2 §17 checklist completion.
- Verification results and any residual risk.
- Scope guard: no MVP 3 work introduced.

## Progress Notes

- 2026-05-11: Started after Tech Lead approved MVP2-05 and authorized MVP2 end-to-end verification.
- 2026-05-11: Ran Docker verification across migrations, MVP2 backend suites, full backend unit suite, Oracle's Lens frontend helpers, frontend lib tests, lint, and production build.

## MVP 2 Contract Checklist

- [x] MVP2-00 decision gate D1-D6 approved and implemented as downstream constraints.
- [x] MVP2-01 `ownership_changes` schema and ORM contract present.
- [x] MVP2-02 consecutive-quarter change analysis reads/writes precomputed rows safely.
- [x] MVP2-03 `/stocks/{stock_id}/holders` aggregation implemented with PRD §9.2.2 exclusions.
- [x] MVP2-04 Oracle's Lens UI displays holder aggregation and caveats without investment-advice language.
- [x] MVP2-05 manager holdings changes endpoint reads precomputed rows and preserves unavailable semantics.
- [x] No MVP 3 scope included.

## Verification Results

- `docker compose exec api alembic upgrade head` - passed.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp2_ownership_changes_schema.py tests/unit/test_13f_ownership_changes_compute.py tests/unit/test_13f_user_api.py` - passed, 45 tests.
- `docker compose exec api pytest -q` - passed, 551 tests; one pre-existing SQLAlchemy rollback warning from `tests/unit/test_13f_holdings_parser.py::test_duplicate_fingerprint_within_same_parse_run_raises`.
- `docker compose exec web node --test lib/oraclesLens.test.js` - passed, 13 tests.
- `docker compose exec web node --test lib` - passed, 114 tests.
- `docker compose exec web npm run lint` - passed with no warnings or errors.
- `docker compose exec web npm run build` - passed.

## Residual Risk / Follow-up

- No blocking residual risk found in this verification pass.
- The full backend suite still emits the known SQLAlchemy rollback warning noted above; it did not fail the suite and is outside MVP 2 scope.
- MVP 3 decision gate should clarify `/stocks/{stock_id}/holders` count labels: current `direct_holder_count` is intentionally the direct consensus count after manager-type exclusions; consider adding `all_direct_holder_count` or renaming the current field before a public contract freeze.
- MVP 3 planning should explicitly decide whether to remove/refactor legacy Dataroma client/stub surfaces now that MVP 2 uses OpenFIGI-backed CUSIP mapping and Dataroma remains excluded as a CUSIP source.
