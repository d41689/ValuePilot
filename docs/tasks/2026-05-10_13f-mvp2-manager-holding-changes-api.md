# 13F MVP2-05 Manager Holding Changes API

## Goal / Acceptance Criteria

Enable `GET /api/v1/13f/managers/{manager_id}/holdings/changes` for MVP 2 by reading the precomputed `ownership_changes` table.

Acceptance criteria:
- Endpoint returns HTTP 200 with `status=available` or `available_with_caveat` and `items[]` when precomputed rows exist.
- Endpoint returns HTTP 200 with `status=unavailable`, structured `reason`, and `items=null` when no computed changes exist.
- Endpoint does not recompute ownership changes inline; it only reads `OwnershipChange13F`.
- Response exposes change status, confidence, caveats, current/previous values and shares, and stock identity.
- 13F-NT / missing prior / low-confidence rows remain explicit through `change_status`, `confidence_level`, `caveat_codes`, and `unavailable_reason`.

## Scope In

- Backend user API service read model for manager holding changes.
- Consumer route quarter validation.
- Unit tests for available and unavailable manager holding changes responses.
- Task log updates with Docker verification results.

## Scope Out

- Ownership-change computation logic.
- Schema or migration changes.
- Stock-holder aggregation changes.
- Frontend changes.
- MVP 3 cross-manager 13F-NT consolidation.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7.4: change status semantics.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.1: Oracle's Lens change signals.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.2: exclusion and caveat rules.
- `docs/prd/13f_automation_and_resilience_prd.md` §13: holdings changes endpoint.
- `docs/prd/13f_automation_and_resilience_prd.md` §17: MVP 2 holdings changes endpoint activation.
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2: unavailable response when one quarter is available.

## Files Likely To Change

- `backend/app/services/thirteenf_user_api.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_user_api.py`
- `docs/tasks/2026-05-10_13f-mvp2-manager-holding-changes-api.md`

## Tests First

Write/update backend tests before implementation:
- Existing MVP 1 unavailable placeholder test should become no-computed-changes unavailable.
- Add available response test backed by `OwnershipChange13F` rows.
- Verify caveat/unavailable metadata is preserved in item payloads.

## Docker Verification Commands

- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py`
- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py tests/unit/test_13f_ownership_changes_compute.py tests/unit/test_13f_mvp2_ownership_changes_schema.py`

## Review Gate

Tech Lead should review:
- Endpoint reads precomputed rows only.
- No misleading empty arrays for unavailable changes.
- Change status/confidence/caveat semantics are preserved.
- Scope guard: no schema, computation, frontend, MVP 3, or PRD changes.

## Progress Notes

- 2026-05-10: Started after MVP2-04 approval. Current endpoint still returned `MVP2_NOT_IMPLEMENTED`; PRD §17 requires MVP 2 activation.
- 2026-05-10: Added red tests for no-computed-changes unavailable response and available precomputed `OwnershipChange13F` rows with explicit `no_prior_data` caveats.
- 2026-05-10: Implemented a thin manager changes read model backed only by `ownership_changes`; no inline change recomputation added.
- 2026-05-10: Added quarter query validation to the consumer holdings changes route.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py` - passed, 12 tests.
- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py tests/unit/test_13f_ownership_changes_compute.py tests/unit/test_13f_mvp2_ownership_changes_schema.py` - passed, 42 tests.
