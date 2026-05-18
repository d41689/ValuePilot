# 13F-1C2-03 MVP 1 End-to-End Verification and Contract Gate

## Goal / Acceptance Criteria

- Verify MVP 1A / 1B / 1C-1 / 1C-2 behavior end to end.
- Produce a final contract checklist for the MVP 1 13F automation scope.
- Confirm all relevant Docker-based backend and frontend verification passes.
- Confirm PRD §18 MVP 1 acceptance criteria are either satisfied or explicitly recorded as deferred with human approval.

## Scope In

- Docker Compose rebuild/start.
- Alembic upgrade to head.
- Full backend unit test suite.
- Frontend lint and production build.
- Fixture-backed ingestion, readiness, caveat, value-unit, deadline, and admin UI contracts as covered by existing tests.
- Final verification notes in this task log.

## Scope Out

- New feature work.
- MVP 2 / MVP 3 behavior.
- PRD changes.
- Opportunistic refactors.
- New schema migrations.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §18 Acceptance Criteria.
- `docs/prd/13f_automation_and_resilience_prd.md` §19 Product Decisions.
- All MVP 1 sections referenced by the execution plan.

## Files Likely to Change

- `docs/tasks/2026-05-10_13f-mvp1-end-to-end-verification.md`

## Tests First

- No new tests are expected for this contract-gate task unless verification exposes a gap.
- Existing backend and frontend tests are the source of truth for this verification pass.

## Docker Verification Commands

- `docker compose up -d --build`
- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`

## Contract Checklist

- [x] 13F-NT never means no holdings.
- [x] Holdings queries use active HR/HR-A filings and current parse runs.
- [x] Value units are normalized to dollars.
- [x] Parse audit is retained.
- [x] Official filing deadline is used for filing-window logic.
- [x] CUSIP temporal mapping uses effective quarter windows.
- [x] Missing / unavailable data is not displayed as zero.
- [x] No PRD, schema, MVP 2, or MVP 3 scope changes.

## Review Gate

- Tech Lead final MVP 1 contract review before merge/release.

## Progress Notes

- 2026-05-10: Confirmed next task after 13F-1C2-02 is `13F-1C2-03: MVP 1 End-to-End Verification and Contract Gate`.
- 2026-05-10: Worktree was clean before starting this verification task.
- 2026-05-10: Docker verification:
  - `docker compose up -d --build` -> passed; `api`, `web`, and `db` services started.
  - `docker compose exec api alembic upgrade head` -> passed.
  - `docker compose exec api pytest -q` -> 513 passed, 1 existing SQLAlchemy rollback warning in `tests/unit/test_13f_holdings_parser.py::test_duplicate_fingerprint_within_same_parse_run_raises`.
  - `docker compose exec web npm run lint` -> passed with no warnings.
  - `docker compose exec web npm run build` -> passed.
- 2026-05-10: Contract gate notes:
  - PRD §18.1 / §18.2 behavior is covered by existing backend parser, ingestion, readiness, alert, user API, admin API, and frontend normalizer/build tests.
  - 13F-NT is preserved as `notice_reported_elsewhere` and user/admin UI caveat behavior, not "no holdings."
  - User-facing holdings contract uses active HR/HR-A filings through current parse runs; MVP 2 changes endpoint remains unavailable.
  - Value-unit rule tests cover pre-2023 thousands, 2023+ dollars, Q4 2022 accepted after the transition, and unknown schema fallback.
  - No PRD, schema, parser, backend feature, frontend feature, MVP 2, or MVP 3 changes were made in this verification task.
