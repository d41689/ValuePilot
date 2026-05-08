# 13F Final Review Cleanup

## Goal / Acceptance Criteria

Clean up the non-blocking findings from the `6e38073` verification report, then run verification and browser QA:

- Remove the now-unused `_filing_status()` helper.
- Move EDGAR pause-state `global` declarations to the conventional function-top location.
- Add a regression test for the 429/503 pause write path.
- Verify the Admin page in the in-app browser.

## Scope

In:

- Backend cleanup and tests.
- Docker verification.
- In-app browser smoke QA for `/admin/13f`.

Out:

- New product functionality.
- Schema changes.
- Alert/ticketing integrations.

## Files To Change

- `backend/app/edgar/client.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `docs/tasks/2026-05-08_13f-final-review-cleanup.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q`
- `docker compose exec api pytest -q`
- `docker compose exec web node --test lib`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`
- Browser smoke check: `/admin/13f` renders core sections and no runtime error.

## Progress Notes

- 2026-05-08: Created task log before code changes.
- 2026-05-08: Removed unused `_filing_status()`, moved EDGAR pause globals to the top of `_request()`, and added a 429 pause regression test.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` — passed, 50 tests.
- `docker compose exec api pytest -q` — passed, 289 tests.
- `docker compose exec web node --test lib` — passed, 105 tests.
- `docker compose exec web npm run lint` — passed.
- `docker compose exec web npm run build` — passed.
- Browser smoke check — passed after restarting the stale Next dev server:
  - unauthenticated `/admin/13f` redirected to `/login`;
  - admin login succeeded through the normal login UI;
  - `/admin/13f` rendered `13F Operations`, `Data Readiness & Operations Health`, `EDGAR Rate Limit`, `Worker Heartbeat`, `Quarters`, and `Managers`;
  - quarter detail drawer opened for `2025-Q4` and showed `Filing Rows`, status filter, and `Prev`/`Next`;
  - `Retry CIK Search` dialog opened with search-name and note fields;
  - no application/runtime error banners were present.
