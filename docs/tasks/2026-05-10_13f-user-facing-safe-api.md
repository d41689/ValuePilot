# 13F-1C1-02 User-Facing 13F API Safe Responses

## Goal / Acceptance Criteria

- Expose MVP 1 user-facing 13F APIs with safe snapshot behavior:
  - `GET /api/v1/13f/readiness`
  - `GET /api/v1/13f/managers`
  - `GET /api/v1/13f/managers/{manager_id}/quarters`
  - `GET /api/v1/13f/managers/{manager_id}/holdings`
  - `GET /api/v1/13f/managers/{manager_id}/holdings/changes`
- Holdings changes returns HTTP 200 with `status=unavailable` and structured reason; no HTTP 503 and no misleading empty array.
- Holdings query uses only active HR/HR-A filings joined to current `parse_runs`.
- NT manager context must not show empty holdings as "no positions"; response carries NT caveat metadata.
- Partial and confidential filings include caveat metadata.
- Options are separated from common holdings; options have `portfolio_weight_pct=null`.

## Scope In

- Backend consumer API endpoints and service layer response builders.
- Response-shape unit tests.
- Minimal schemas only if useful for contract clarity.

## Scope Out

- MVP 2 computed changes / ownership change analysis.
- Full `/stocks/{stock_id}/holders` aggregation.
- Frontend/UI.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7.3 holdings query contract.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2 Oracle's Lens signal scope and caveats.
- `docs/prd/13f_automation_and_resilience_prd.md` §13 Oracle's Lens APIs.
- `docs/prd/13f_automation_and_resilience_prd.md` §16 UX copy principles.
- `docs/prd/13f_automation_and_resilience_prd.md` §18 acceptance criteria.

## Files Likely To Change

- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/app/services/thirteenf_user_api.py` (new)
- `backend/tests/unit/test_13f_user_api.py` (new)
- `docs/tasks/2026-05-10_13f-user-facing-safe-api.md`

## Tests First

- Holdings changes returns HTTP 200 + `status=unavailable` with structured reason.
- NT manager holdings response returns `status=unavailable` with NT caveat, not empty "no positions".
- Partial/confidential active filings include caveat metadata.
- Options are in a separate `options` collection and use `portfolio_weight_pct=null`.
- Holdings endpoint excludes inactive filings and stale/non-current parse runs.

## Docker Verification Commands

- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py`
- `docker compose exec api pytest -q tests/unit/test_13f_readiness.py tests/unit/test_13f_nt_handler.py tests/unit/test_13f_parse_run_audit.py`
- `docker compose exec api pytest -q tests/unit`

## Review Gate

Tech Lead must review response shapes before frontend work starts (G4).

## Progress Notes

- 2026-05-10: Started after Tech Lead approved 13F-1C1-01 readiness contract. Git worktree was clean. Scope is backend API only; no frontend and no MVP 2 computed changes.
- 2026-05-10: Wrote failing user API tests first; initial Docker run failed with 5 endpoint 404s as expected.
- 2026-05-10: Added `thirteenf_user_api` service and consumer routes for managers, quarters, holdings, and holdings/changes. The holdings builder uses `active_hr_holdings_query()` so NT filings, inactive filings, and stale parse runs cannot enter user-facing holdings. Direct manager routes also hide inactive managers and managers without confirmed CIK.
- 2026-05-10: Verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_user_api.py` -> 7 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_user_api.py tests/unit/test_13f_readiness.py tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_nt_handler.py tests/unit/test_13f_parse_run_audit.py` -> 85 passed.
  - `docker compose exec api pytest -q tests/unit` -> 473 passed, 1 existing SQLAlchemy transaction warning.

## Contract Checklist

- PRD §7.3 preserved: user holdings query goes through active HR/HR-A + active filing + current parse run helper.
- NT manager context returns `status=unavailable` with `NOTICE_REPORTED_ELSEWHERE`, not empty holdings.
- MVP 2 holdings changes returns HTTP 200 + structured unavailable reason with `items=null`.
- Partial combination and confidential treatment caveats are carried in response metadata.
- Options are separated from common holdings and have null common portfolio weight.
- No frontend, PRD, migration, parser, or MVP 2 computed-changes implementation.
