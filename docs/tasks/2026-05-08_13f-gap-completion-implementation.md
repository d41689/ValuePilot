# 13F Gap Completion Implementation

## Goal / Acceptance Criteria

Implement the non-deferred gaps from the reconciled 13F Admin product plan:

- G7 revoked CIK impact on quarter health/readiness.
- G5 typed JobRun summary contracts.
- G4 quarter detail pagination/filtering.
- G6 configurable readiness thresholds.
- G2 EDGAR rate-limit quota visibility.
- G3 per-manager edited-name CIK retry.

Email alerts, Smart Retry settings UI, and external ticket integration are explicitly deferred in the product plan and are out of scope for this implementation batch.

## Scope

In:

- Backend services, API endpoints, schemas/helpers, tests.
- Frontend helper normalization and focused Admin UI changes needed to expose new behavior.
- Docker-based verification.

Out:

- Schema migrations unless unavoidable.
- Email alerts.
- Runtime Smart Retry toggle UI.
- External ticketing integration.

## Files To Inspect / Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/services/thirteenf_job_worker.py`
- `backend/app/services/edgar_ingestion.py`
- `backend/app/edgar/client.py`
- `backend/app/core/config.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `docs/tasks/2026-05-08_13f-gap-completion-implementation.md`

## Execution Plan

1. Inspect current service/API/UI boundaries and write targeted tests first.
2. Implement data correctness and contract safety:
   - revoked CIK quarter/readiness impact;
   - summary contract helpers;
   - quarter filings pagination/filtering.
3. Implement operational controls:
   - readiness thresholds from settings;
   - EDGAR rate-limit/quota read model;
   - per-manager edited-name CIK retry.
4. Update the Admin UI only where needed to surface the new backend capabilities.
5. Run Docker verification:
   - relevant backend pytest during iteration;
   - full backend pytest when stable;
   - frontend `node --test lib`, lint, and build.

## Contract Checks

- Candidate CIKs and edited-name retries must not auto-confirm low-confidence matches.
- Revoked CIK repair state must not delete or mutate historical holdings; it should surface review/repair state.
- Job summary schema helpers must preserve existing summary JSON compatibility.
- Pagination must not remove summary counts or retry target fidelity.
- EDGAR quota visibility must not bypass existing request delay/backoff settings.

## Progress Notes

- 2026-05-08: Created implementation task log before code changes.
- 2026-05-08: Added tests for revoked CIK quarter/readiness impact, paged quarter filing rows, summary schema fields, configurable readiness thresholds, EDGAR rate-limit status, and edited-name CIK retry.
- 2026-05-08: Implemented backend support for:
  - unresolved revoked-CIK repair scope in quarter health/readiness;
  - quarter detail filing pagination and status filters;
  - settings-backed readiness thresholds;
  - EDGAR rolling-window request budget endpoint;
  - per-manager edited-name CIK retry with audit event;
  - pipeline/stage summary schema markers.
- 2026-05-08: Updated Admin UI with EDGAR budget panel, quarter filing pager/status filter, revoked-CIK quarter warning, and Retry CIK Search dialog.
- 2026-05-08: Updated product plan to move G2-G7 into closed/implemented state and leave only G1/G8/G9 deferred.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` — passed, 46 tests.
- `docker compose exec web node --test lib/thirteenfAdmin.test.js` — passed, 20 tests.
- `docker compose exec web npm run lint` — passed.
- `docker compose exec web node --test lib` — passed, 105 tests.
- `docker compose exec web npm run build` — passed.
- `docker compose exec api pytest -q` — passed, 285 tests.
