# 13F MVP3-03: Filing-Level Value Unit Override Schema / Audit Contract

## Goal / Acceptance Criteria

Add the schema and ORM audit contract for filing-level value-unit overrides without implementing the override workflow or reparse behavior.

Acceptance criteria:
- `filings_13f` stores the current effective filing-level override summary / pointer.
- A separate immutable-style audit table records every override event with filing scope, accession, prior parser rule, new override value, reason/evidence, reviewer, review timestamp, reparse result pointer, and status.
- Filing-level override contract does not modify or replace existing manager-level `value_unit_override=infer`.
- Overrides are schema-ready for controlled reparse but do not take effect in parser/product data in this task.
- Relevant tests and migrations pass in Docker.

## Scope In

- Alembic migration for filing-level override pointer columns and audit table.
- SQLAlchemy model and validators.
- Focused schema/model tests.
- Task-file progress and verification notes.

## Scope Out

- Parser behavior changes.
- Controlled reparse implementation.
- Batch reparse jobs.
- Admin API/UI for creating or resolving overrides.
- Validation jobs beyond existing MVP3-02 foundation.
- Historical backfill.
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D5: use both a filing-level effective override pointer and separate audit table.
- `docs/prd/13f_automation_and_resilience_prd.md` §20: filing-level `value_unit_override` is MVP 3 pre-implementation decision.

## Files Expected To Change

- `backend/alembic/versions/*-13f_mvp3_value_unit_overrides.py`
- `backend/app/models/institutions.py`
- Focused backend unit test file.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_value_unit_override_schema.py`
- `docker compose exec api alembic upgrade head`
- `docker compose exec api alembic downgrade 20260511120000`
- `docker compose exec api alembic upgrade head`

## Progress Notes

- 2026-05-11: Started after MVP3-02 completion. Scope limited to schema and ORM audit contract.
- 2026-05-11: Added failing schema/model tests first. Initial red result was the expected missing `FILING_VALUE_UNIT_OVERRIDE_STATUSES` / `FilingValueUnitOverride13F` import.
- 2026-05-11: Added Alembic revision `20260511130000` with `filing_value_unit_overrides` plus `filings_13f.effective_value_unit_override(_id)`.
- 2026-05-11: Added ORM contract and validators. Filing-level override uses the same `infer` / `thousands` / `dollars` value set as existing manager-level override, but does not replace or mutate `InstitutionManager.value_unit_override`.
- 2026-05-11: Scope guard: no parser behavior, reparse execution, admin route/UI, validation job, backfill, or PRD changes were made.
- 2026-05-11: Review follow-up accepted and fixed: reviewer is now required, `baseline_parse_run_id` names the pre-override reference run, `result_parse_run_id` records the reparse run that applies the override, `old_parse_rule` is required, Filing ORM relationships are traversable, and tests cover the filings index plus mutual-FK cascade delete.
- 2026-05-11: Review follow-up accepted and fixed after deeper review: added DB/ORM check constraint so explicit `thousands` / `dollars` filing overrides require an audit pointer while still allowing default `infer`; split audit event override values so `new_override_value` accepts only explicit `thousands` / `dollars`, not `infer`.
- 2026-05-11: Review follow-up deferred by design: no partial unique `status='applied'` index yet because effective pointer defines current state and MVP3-04 will finalize lifecycle transition rules; no `created_by_user_id` yet because MVP3-03 records the approving reviewer and leaves request/approval separation to the admin workflow task; no compound `(filing_id, status)` index until MVP3-04 query paths are known.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_value_unit_override_schema.py` -> 14 passed after review follow-up.
- `docker compose exec api alembic downgrade 20260511120000` -> passed.
- `docker compose exec api alembic upgrade head` -> passed.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_value_unit_override_schema.py tests/unit/test_13f_schema_foundation.py` -> 54 passed after review follow-up.
- `docker compose exec api pytest -q` -> 567 passed, 1 pre-existing SQLAlchemy rollback warning in `test_duplicate_fingerprint_within_same_parse_run_raises`.
