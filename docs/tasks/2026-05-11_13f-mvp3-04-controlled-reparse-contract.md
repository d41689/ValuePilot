# 13F MVP3-04: Controlled Reparse Contract and Before/After Impact Summary

## Goal / Acceptance Criteria

Define and implement the controlled single-filing reparse contract that future batch reparse jobs must use, including an auditable before/after impact summary.

Acceptance criteria:
- Controlled reparse works on an explicit accession / filing scope, not broad quarter or manager batches.
- Reparse creates a new `parse_run` and preserves old parse runs / holdings for audit.
- Current parse-run pointer is not switched unless the new parse succeeds and validation/readiness gates pass.
- The contract produces a structured before/after impact summary covering:
  - filings affected
  - parse runs created
  - active current pointers changed
  - holdings rows changed
  - ownership changes invalidated / recomputed scope
  - readiness-level impact
  - quality finding deltas when available
- Filing-level value-unit override events can be linked to the resulting parse run only after controlled reparse succeeds.
- MVP3-03 deferred decisions are handled or explicitly carried forward:
  - `status='applied'` partial unique index remains deferred until workflow transition rules are finalized.
  - `created_by_user_id` remains deferred unless this task introduces request / approval separation.
  - `(filing_id, status)` index remains deferred unless this task adds a hot query requiring it.
- Relevant tests pass in Docker.

## Scope In

- Single-filing controlled reparse service / contract.
- Before/after impact summary data structure.
- Tests for success/failure pointer semantics and override result-link semantics.
- Task-file progress and verification notes.

## Scope Out

- Batch reparse by quarter / manager.
- Admin API / UI for reparse.
- Historical backfill.
- Corporate action temporal mapping UI.
- Parser feature changes beyond invoking existing parser paths.
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D3: controlled reparse contract and impact summary before batch reparse.
- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D5: filing-level value-unit overrides take effect only through controlled reparse and validation.
- `docs/prd/13f_automation_and_resilience_prd.md` §6.3: parse runs preserve audit history and product queries use `is_current=true`.
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2: reparse creates a new current parse run and old holdings remain.

## Files Expected To Change

- A focused backend service module or existing 13F parse service module.
- Focused backend unit tests.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_controlled_reparse.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Started after MVP3-03 review follow-up and approval to continue. Scope limited to controlled single-filing reparse contract / impact summary, not batch reparse.
- 2026-05-11: Added TDD coverage first for controlled reparse success and validation-failure paths. Initial red result was expected missing `app.services.thirteenf_controlled_reparse`.
- 2026-05-11: Added `thirteenf_controlled_reparse` service wrapping the existing audit-preserving `reparse_accession` path. The wrapper records before/after impact, restores the old current parse-run pointer on validation failure, and applies filing-level value-unit overrides only after validation-gated reparse success.
- 2026-05-11: Tightened the contract so callers must pass an explicit `validation_gate`; the controlled path refuses to run if validation/readiness checks are not wired.
- 2026-05-11: Impact summary includes filings affected, parse runs created, final current-pointer change, current holdings before/after, candidate holdings rows created, ownership-change recompute scope, parse-status impact, and quality-finding deltas.
- 2026-05-11: MVP3-03 carryovers handled: `status='applied'` partial unique index remains deferred until batch/control workflow transition rules are finalized; `created_by_user_id` remains deferred because this task does not introduce request/approval separation; `(filing_id, status)` index remains deferred because this task does not add a pending-override query path.
- 2026-05-11: Scope guard: no batch reparse, admin API/UI, historical backfill, corporate-action UI, parser feature change, or PRD edit.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_controlled_reparse.py` -> 3 passed.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_controlled_reparse.py tests/unit/test_13f_parse_run_audit.py tests/unit/test_13f_mvp3_value_unit_override_schema.py` -> 25 passed.
- `docker compose exec api pytest -q` -> 570 passed, 1 pre-existing SQLAlchemy rollback warning in `test_duplicate_fingerprint_within_same_parse_run_raises`.
