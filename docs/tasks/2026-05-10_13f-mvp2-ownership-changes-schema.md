# MVP2-01 Ownership Changes Schema / Precompute Contract

## Goal / Acceptance Criteria

- Add the MVP 2 `ownership_changes` precompute schema and ORM contract.
- Encode the decision gate constraints from `2026-05-10_13f-mvp2-decision-gate.md`, especially D5/D6.
- Support future change computation without implementing the computation itself.
- Preserve MVP 1 safety rules: no 13F-NT direct holdings inference, no missing-data-to-zero interpretation, no MVP 3 scope.

## Scope In

- Alembic migration for `ownership_changes`.
- SQLAlchemy model and application-level enum validation.
- Indexes/uniqueness needed for manager/stock/quarter query paths and idempotent precompute writes.
- Unit tests for schema columns, indexes, enum values, and uniqueness.

## Scope Out

- Consecutive-quarter computation implementation.
- `/api/v1/13f/managers/{manager_id}/holdings/changes` activation.
- `/api/v1/13f/stocks/{stock_id}/holders` aggregation.
- Oracle's Lens investor signal UI.
- Corporate action source integration.
- Cross-manager 13F-NT consolidation.
- PRD changes.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7.4 holdings change calculation.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2 Oracle's Lens investor signals.
- `docs/prd/13f_automation_and_resilience_prd.md` §13 API contracts.
- `docs/prd/13f_automation_and_resilience_prd.md` §17 MVP 2 delivery plan.
- `docs/tasks/2026-05-10_13f-mvp2-decision-gate.md` D1-D6.

## Files Likely to Change

- `backend/alembic/versions/20260510120000-13f_mvp2_ownership_changes.py`
- `backend/app/models/institutions.py`
- `backend/tests/unit/test_13f_mvp2_ownership_changes_schema.py`
- `docs/tasks/2026-05-10_13f-mvp2-ownership-changes-schema.md`

## Tests First

- Add failing unit tests that assert:
  - `ownership_changes` table columns and indexes exist.
  - `change_status` accepts MVP 2 statuses including `cusip_changed` and rejects invalid values.
  - `confidence_level` accepts D5 tiers and rejects invalid values.
  - idempotency uniqueness prevents duplicate current manager/quarter/security/option rows.

## Docker Verification Commands

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp2_ownership_changes_schema.py`
- `docker compose exec api pytest -q tests/unit`

## Review Gate

- Tech Lead migration/schema review before MVP2-02 computation starts.

## Progress Notes

- 2026-05-10: Started after human approval to proceed beyond MVP2-00.
- 2026-05-10: Scope intentionally limited to schema/model contract. No computation, API activation, UI, PRD, or MVP 3 work.
- 2026-05-10: Wrote schema-first tests for `ownership_changes` columns/indexes, change status enum, confidence tier enum, and idempotent manager/quarter/security uniqueness.
- 2026-05-10: Added Alembic migration `20260510120000-13f_mvp2_ownership_changes.py` and `OwnershipChange13F` ORM model.
- 2026-05-10: Docker verification:
  - `docker compose exec api alembic downgrade 20260509140000` -> passed during migration replay after key refinement.
  - `docker compose exec api alembic upgrade head` -> passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_mvp2_ownership_changes_schema.py` -> 15 passed.
  - `docker compose exec api pytest -q tests/unit` -> 509 passed, 1 existing SQLAlchemy rollback warning.
  - `docker compose exec api pytest -q` -> 528 passed, 1 existing SQLAlchemy rollback warning.
- 2026-05-10: Review follow-up verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_mvp2_ownership_changes_schema.py` -> 18 passed.
  - `docker compose exec api pytest -q` -> 531 passed, 1 existing SQLAlchemy rollback warning.
- 2026-05-10: Contract notes:
  - The schema stores/derives D5/D6 outputs through `change_status`, `confidence_level`, `is_primary_signal_eligible`, `caveat_codes`, and `unavailable_reason`.
  - `CUSIP_CHANGED` is represented by `change_status='cusip_changed'` with previous/current CUSIP columns.
  - Idempotency uniqueness includes `ssh_prnamt_type` and `position_type`, matching the PRD §7.4 security matching rule that separates share/unit type and options.
  - `position_type` is constrained to `common`, `put_option`, and `call_option`; generic `option` is intentionally invalid so Put/Call rows cannot collide.
  - `caveat_codes` is a JSON list of string codes, e.g. `["possible_split_or_merger", "combination_partial"]`. Structured/free-text caveat details should be carried by API serializers or future review fields, not mixed into this list.
  - No computation service, API response activation, frontend UI, PRD edit, cross-manager NT consolidation, or external corporate action source was added.
