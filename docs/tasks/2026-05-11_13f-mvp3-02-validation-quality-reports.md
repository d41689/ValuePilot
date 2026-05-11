# 13F MVP3-02: Data Integrity Validation Jobs and Persisted Quality Reports

## Goal / Acceptance Criteria

Make MVP 3 data-integrity validation findings durable at finding level, with quality reports as the source of truth and alerts as optional notification surfaces.

Acceptance criteria:
- Persist validation findings with `validation_run_id` / report linkage, `rule_code`, `severity`, entity context, quarter, manager, accession, status, first/last seen timestamps, and optional resolution metadata.
- Existing aggregate `quality_reports_13f` behavior remains compatible.
- `quality_check` jobs persist both aggregate reports and finding rows.
- Add at least one MVP3 D6 validation candidate for filing value-unit sanity checks.
- No historical backfill, batch reparse, value-unit override workflow, corporate-action UI, or Dataroma changes.
- Relevant tests pass in Docker.

## Scope In

- Alembic migration for persisted finding rows.
- SQLAlchemy model for finding rows.
- `edgar_quality` persistence updates.
- Focused validation rule for suspicious filing value-unit anomalies.
- Unit tests covering finding persistence and value-unit sanity checks.
- Task-file progress / verification notes.

## Scope Out

- Admin UI for resolving findings.
- Automated repair behavior.
- Alert routing changes.
- Historical backfill.
- Batch reparse.
- Filing-level value-unit override implementation.
- Corporate-action temporal mapping UI.
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D6: persisted quality reports are the source of truth.
- D6 initial candidates: value-unit sanity checks, ownership-change drift, current parse-run drift, overlapping CUSIP ranges, and test-infrastructure debt.

## Files Expected To Change

- `backend/alembic/versions/*-13f_mvp3_quality_findings.py`
- `backend/app/models/institutions.py`
- `backend/app/services/edgar_quality.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `docs/tasks/2026-05-11_13f-mvp3-02-validation-quality-reports.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api alembic upgrade head`

## Progress Notes

- 2026-05-11: Started after MVP3-01 approval and completion. Scope limited to persisted quality findings and validation-rule persistence.
- 2026-05-11: Added `quality_findings_13f` as finding-level source of truth linked to aggregate `quality_reports_13f`, with cascade cleanup for existing report deletion paths.
- 2026-05-11: Extended `persist_quality_report` to upsert open finding rows and added `value_unit_sanity` warning for suspicious 1000x filing-level reported value jumps.

## Verification Results

- `docker compose exec api alembic upgrade head` → applied `20260511120000`.
- `docker compose exec api alembic downgrade 20260510120000` → succeeded.
- `docker compose exec api alembic upgrade head` → reapplied `20260511120000`.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` → 52 passed.
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_admin_read_models.py tests/unit/test_13f_manager_admin_backend.py tests/unit/test_13f_daily_index_sync.py` → 72 passed.
