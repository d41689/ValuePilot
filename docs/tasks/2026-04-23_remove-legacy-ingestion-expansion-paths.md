# Task: Remove legacy ingestion expansion paths

## Goal / Acceptance Criteria
- Remove legacy time-series expansion helpers from `IngestionService` that no longer participate in the taxonomy v1 write path.
- Remove dead constants that only existed to support those legacy write paths.
- Leave the active write path as `page_json -> mapping_spec -> metric_facts`.
- Full backend test suite remains green.

## Scope
**In**
- `backend/app/services/ingestion_service.py`
- A narrow regression test asserting legacy expansion helpers are no longer exposed
- Task log updates

**Out**
- Parser changes
- Schema changes
- Further taxonomy changes

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> normalized queryable facts in `metric_facts`
- `AGENTS.md` -> Docker-only verification and task logging

## Files To Change
- `docs/tasks/2026-04-23_remove-legacy-ingestion-expansion-paths.md`
- `backend/app/services/ingestion_service.py`
- `backend/tests/unit/test_ingestion_service_legacy_paths.py`

## Execution Plan
1. Add a failing regression test asserting legacy expansion helpers are no longer part of `IngestionService`.
2. Remove dead legacy expansion helpers/constants and clean imports.
3. Run targeted tests and full backend tests in Docker.

## Contract Checks
- Do not change the active `mapping_spec` write path.
- Do not remove currently used helpers such as owners earnings derivation, precedence, or provenance logic.

## Rollback Strategy
- Restore removed helpers if a hidden call site appears during verification.

## Progress Log
- [x] Add failing regression test.
- [x] Remove legacy expansion helpers/constants.
- [x] Run targeted Docker verification.
- [x] Run full backend verification.

## Notes / Decisions / Gotchas
- The old helpers are currently dead code, not active behavior.
- Removed only helpers/constants that were no longer referenced anywhere in the active ingestion path.
- The active write path remains `page_json -> mapping_spec -> metric_facts`, with owners earnings derivation as a downstream derived layer.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_ingestion_service_legacy_paths.py`
- `docker compose exec api pytest -q`
- Results:
  - Legacy-path regression: `1 passed in 0.01s`
  - Full suite: `130 passed in 22.88s`
