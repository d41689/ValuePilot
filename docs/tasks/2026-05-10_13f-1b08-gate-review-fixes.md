# 13F-1B-08 Gate Review Fixes

## Goal / Acceptance Criteria

Validate implementation through `13F-1B-08` against `docs/prd/13f_automation_and_resilience_prd.md` and `docs/tasks/2026-05-09_13f-automation-development-plan.md`, then directly fix any confirmed gaps.

Acceptance criteria:
- `sync_manager_backfill` creates actionable ingestion stage payloads.
- Backfill preview does not silently convert SEC submission fetch failures into a misleading zero-filing preview.
- Backfill preview flags pre-2023-Q1 value-unit risk from the requested range, even when no matching filing is returned.
- Explicit backfill confirmation validates active manager/CIK and date range before enqueueing.
- Relevant Docker tests pass.

## Scope

In:
- 13F-1B-08 backfill preview and confirmed job behavior.
- Focused regression tests for identified gaps.
- Task log updates.

Out:
- PRD edits.
- Full MVP 3 historical backfill.
- Frontend UI.
- Parser or holdings persistence changes outside backfill orchestration.

## Files to Change

- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_backfill.py`
- `docs/tasks/2026-05-10_13f-1b08-gate-review-fixes.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_backfill.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-10: Started Tech Lead validation after implementation reached 13F-1B-08.
- 2026-05-10: Found 13F-1B-08 gaps: preview hid SEC submissions fetch failures as zero filings; pre-2023 value-unit warning depended on matched filings instead of requested range; sync_manager_backfill stage payload omitted manager_id/form_type/cik required by ingest_accession.
- 2026-05-10: Added failing tests for those gaps before implementation fixes.
- 2026-05-10: Fixed backfill preview validation and sync_manager_backfill stage payload; added compatibility CUSIP enrichment wrappers required by existing admin pipeline tests.
- 2026-05-10: Docker verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_backfill.py` -> 6 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_backfill.py tests/unit/test_13f_admin_dashboard.py` -> 56 passed.
  - Relevant 13F task suite through 13F-1B-08 -> 181 passed, 1 existing SQLAlchemy transaction warning.
  - `docker compose exec api pytest -q tests/unit` -> 457 passed, 1 existing SQLAlchemy transaction warning.
