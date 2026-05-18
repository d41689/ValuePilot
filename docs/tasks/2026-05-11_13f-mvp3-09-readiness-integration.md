# 13F MVP3-09: Readiness Integration for Cross-Task Findings

## Status

Active. Started after MVP3 end-to-end review approved the parallel-track
closure of SME C2: the readiness service does not currently consume the
`QualityFinding13F` rule_codes introduced in MVP3-06 and MVP3-07, so a
quarter with pending corporate-action recompute or pending backfill
validation can still be reported as `ready` by `/api/v1/13f/readiness`
and as healthy by the admin dashboard. This closes that gap.

## Goal / Acceptance Criteria

`build_readiness_summary` and the admin per-quarter summary must reflect
open `QualityFinding13F` rows with the two MVP3 rule_codes as warnings
(not blockers).

Acceptance criteria:
- `build_readiness_summary` queries `QualityFinding13F` rows where
  `status='open'` and `rule_code` is one of
  `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION` or
  `HISTORICAL_BACKFILL_NEEDS_VALIDATION`.
- Each rule emits a stable readiness warning code when any open finding
  exists:
  - `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` — corporate-action mapping
    changes are pending recompute; ownership-change deltas may be stale.
  - `HISTORICAL_BACKFILL_NEEDS_VALIDATION` — backfilled filings awaiting
    validation gate.
- Neither rule moves a quarter to `unavailable`. They surface as
  warnings only, per SME guidance.
- The `quarter_lists` payload gains two new keys:
  - `ownership_changes_needs_recompute_quarters`
  - `historical_backfill_needs_validation_quarters`
- The admin per-quarter summary (`thirteenf_admin_dashboard._quarter_summary`)
  exposes open finding counts (`open_recompute_finding_count`,
  `open_backfill_validation_finding_count`) so a later passing
  MVP3-02 `quality_check` run cannot mask MVP3-06/07 work by
  overwriting `QualityReport13F.status`.
- `_quarter_health` returns `needs_review` when either open finding
  count is non-zero, independent of the latest `QualityReport13F`
  status.
- Resolving a finding (status → `resolved`) removes the warning and
  drops the count, with no service-level mutation of the finding row
  itself.
- Relevant tests pass in Docker.

## Scope In

- `app/services/thirteenf_readiness.py`:
  - new internal helper to query quarters with open findings by rule_code,
  - new entries in `_quarter_lists`,
  - new `_message(...)` warning emissions in `build_readiness_summary`.
- `app/services/thirteenf_admin_dashboard.py`:
  - extend `_quarter_summary` to query open finding counts,
  - extend `_quarter_health` signature + logic to consider those counts.
- New test file
  `backend/tests/unit/test_13f_mvp3_readiness_integration.py`.

## Scope Out

- New finding rule_codes (this task only consumes existing ones).
- Frontend readiness UI changes — kept as a separate frontend task per
  dev-plan G4.
- Recompute pipeline implementation — invalidation is already complete
  from MVP3-06 / MVP3-07; recompute is a separate ownership-change
  consumer.
- Migration. Open findings are queried directly; no schema changes.
- PRD edits.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §10: readiness
  reflects current data reliability.
- `docs/tasks/2026-05-11_13f-mvp3-end-to-end-verification.md`: SME C2
  entry that originated this task.
- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D4 (corporate
  action) and D1 (historical backfill): the two decisions whose
  findings need to be wired into readiness.

## Files Expected To Change

- `backend/app/services/thirteenf_readiness.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_mvp3_readiness_integration.py`
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_readiness_integration.py`
- `docker compose exec api pytest -q tests/unit/test_13f_readiness.py`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-11: Promoted from stub. Scope locked to read-only consumption
  of existing findings; no new rule_codes, no migration, no UI.
- 2026-05-11: Wrote TDD coverage first under
  `tests/unit/test_13f_mvp3_readiness_integration.py` (6 tests):
  open corporate-action finding → recompute warning; open backfill
  finding → backfill-validation warning; both quarter_lists keys
  populated correctly; resolved findings ignored (readiness back to
  `ready`); even many open findings never collapse readiness to
  `unavailable`; admin per-quarter summary surfaces
  `open_recompute_finding_count` /
  `open_backfill_validation_finding_count` and forces
  `quarter_health=needs_review` even when the latest
  `QualityReport13F.status` is `passed`; resolving the findings clears
  both counts.
- 2026-05-11: Implemented `thirteenf_readiness`:
  - Added `_quarters_with_open_finding(session, rule_code)` helper.
  - Extended `_quarter_lists` with
    `ownership_changes_needs_recompute_quarters` and
    `historical_backfill_needs_validation_quarters`.
  - `build_readiness_summary` emits two new warnings (never blockers)
    when either list is non-empty:
    - `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE`
    - `HISTORICAL_BACKFILL_NEEDS_VALIDATION`
  - The rule_codes themselves are imported as private module
    constants so the readiness service and the dashboard service do
    not drift apart.
- 2026-05-11: Implemented `thirteenf_admin_dashboard`:
  - Added `_open_finding_count(session, quarter, rule_code)` helper.
  - `_quarter_summary` now exposes
    `open_recompute_finding_count` and
    `open_backfill_validation_finding_count` independently of
    `quality_status`.
  - `_quarter_health` accepts
    `open_cross_task_finding_count=open_recompute + open_backfill`
    and returns `needs_review` when either is non-zero, before the
    `quality_status` check, so a later passing `quality_check` cannot
    mask the open findings.
- 2026-05-11: Scope guard — no schema migration, no parser changes,
  no frontend changes, no PRD edits. Both the recompute and
  validation rule codes are consumed read-only.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp3_readiness_integration.py` -> 6 passed.
- `docker compose exec api pytest -q` -> 640 passed (was 634; +6), 3 pre-existing SQLAlchemy rollback warnings (same as MVP3 end-to-end baseline).
