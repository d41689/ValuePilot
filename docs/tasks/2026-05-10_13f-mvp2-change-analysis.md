# 13F MVP2-02 Consecutive-Quarter Change Analysis

## Goal / Acceptance Criteria

Implement the backend computation contract that compares a manager's active current-quarter 13F-HR/HR-A holdings against the immediately prior quarter and writes precomputed rows to `ownership_changes`.

Acceptance criteria:
- Current/prior holdings are compared by stable security identity, preferring `stock_id` and preserving `ssh_prnamt_type` plus `position_type` separation.
- `cusip_changed` is emitted when both quarters map to the same `stock_id` but the CUSIP changed; it must not produce `exited_position` plus `new_position`.
- 13F-NT, missing prior data, partial/combination coverage, and unresolved attribution do not create strong labels from unknown data.
- Put and call option rows for the same stock can coexist and remain isolated.
- Re-running the computation for the same manager/quarter is idempotent.

## Scope In

- Backend service for MVP 2 ownership change precomputation.
- Unit tests for change statuses, CUSIP_CHANGED, 13F-NT prior-quarter behavior, option isolation, and idempotent recomputation.
- Task log updates with Docker verification results.

## Scope Out

- User-facing API activation for `/holdings/changes`.
- `/stocks/{stock_id}/holders` aggregation.
- Oracle's Lens UI.
- External corporate action data source.
- MVP 3 cross-manager 13F-NT consolidation.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7.4: change-status rules, CUSIP_CHANGED, no_prior_data.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.2: exclusion rules and direct attribution.
- `docs/prd/13f_automation_and_resilience_prd.md` §17: MVP 2 change analysis and precomputed `ownership_changes`.
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2: 13F-NT prior quarter must produce `no_prior_data`, not `new_position`.
- `docs/tasks/2026-05-10_13f-mvp2-decision-gate.md` D1-D6.

## Files Likely To Change

- `backend/app/services/thirteenf_ownership_changes.py`
- `backend/tests/unit/test_13f_ownership_changes_compute.py`
- `docs/tasks/2026-05-10_13f-mvp2-change-analysis.md`

## Tests First

Write failing tests before implementation:
- Compare complete current/prior HR filings and classify `increased`, `new_position`, `exited_position`, and `cusip_changed`.
- Prior quarter 13F-NT yields `no_prior_data`, not `new_position`.
- Put and call options for the same `stock_id` remain separate rows.
- Re-running computation does not duplicate rows.

## Docker Verification Commands

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_ownership_changes_compute.py`
- `docker compose exec api pytest -q`

## Review Gate

Tech Lead should review:
- Change-status truth table against PRD §7.4 and D6.
- Whether missing/NT/partial data is represented as unavailable/no_prior_data instead of strong labels.
- Option/common isolation and idempotency.
- Scope guard: no API/UI/MVP3 implementation.

## Progress Notes

- 2026-05-10: Started MVP2-02 after MVP2-00 gate approval and MVP2-01 schema review follow-up.
- 2026-05-10: Added TDD coverage for strong label classification, `cusip_changed`, prior 13F-NT, put/call isolation, CUSIP mapping threshold caps, and idempotent recomputation.
- 2026-05-10: Implemented `compute_ownership_changes_for_manager_quarter` as a backend-only precompute service. It replaces rows for a manager/quarter, uses active HR/HR-A current parse-run direct holdings, preserves option/common identity, and writes unavailable/low-confidence rows rather than strong labels when data quality gates fail.
- 2026-05-10: Review follow-up accepted BF-1 and NF-1. Added two-pass matching so holdings that gain `stock_id` between quarters still match by CUSIP fallback instead of producing false exit+new signals. Added filing-caveat confidence adjustment so confidential, combination, and pending amendment caveats cannot remain primary high-confidence signals.
- 2026-05-10: Post-approval polish: tightened repeated-iteration helper signatures to `Sequence[Holding13F]` and added dedicated combination-report and pending-amendment caveat downgrade tests.

## Verification Results

- `docker compose exec api alembic upgrade head` — passed.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp2_ownership_changes_schema.py tests/unit/test_13f_ownership_changes_compute.py` — 28 passed after review follow-up.
- `docker compose exec api pytest -q` — 537 passed, 1 pre-existing SQLAlchemy rollback warning in `test_duplicate_fingerprint_within_same_parse_run_raises`.
- `docker compose exec api pytest -q` — 541 passed after review follow-up, 1 pre-existing SQLAlchemy rollback warning in `test_duplicate_fingerprint_within_same_parse_run_raises`.
- `docker compose exec api alembic upgrade head` — passed after post-approval polish.
- `docker compose exec api pytest -q tests/unit/test_13f_mvp2_ownership_changes_schema.py tests/unit/test_13f_ownership_changes_compute.py` — 30 passed after post-approval polish.
- `docker compose exec api pytest -q` — 543 passed after post-approval polish, 1 pre-existing SQLAlchemy rollback warning in `test_duplicate_fingerprint_within_same_parse_run_raises`.

## Final Notes

- Scope stayed backend-only: no API route activation, no stock holder aggregation, no UI, no PRD edits.
- The service currently computes per manager/quarter. A later orchestration task can call it across managers/quarters once MVP2 API/aggregation tasks are ready.
