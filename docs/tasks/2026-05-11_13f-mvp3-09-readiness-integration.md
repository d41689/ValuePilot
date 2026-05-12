# 13F MVP3-09: Readiness Integration for Cross-Task Findings

## Status

**Stub.** Not started. Created during MVP3 end-to-end verification to capture
the Domain SME C2 finding so it is not lost between sessions. No code work
should begin under this task without an explicit Tech Lead + Product Owner
go-ahead — the readiness contract is user-facing.

## Goal / Acceptance Criteria

Close the readiness-integration gap identified in the MVP3 end-to-end review:
`build_readiness_summary` and the admin dashboard must consume the
`QualityFinding13F` rule_codes introduced in MVP3-06 and MVP3-07 so that
quarters with pending corporate-action recompute or pending backfill
validation are reflected as readiness warnings (not blockers).

Acceptance criteria (proposed, subject to Tech Lead + PO review before work
begins):
- `app/services/thirteenf_readiness.build_readiness_summary` queries open
  `QualityFinding13F` rows in
  `{OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION,
    HISTORICAL_BACKFILL_NEEDS_VALIDATION}` per quarter and emits warnings
  with stable codes (e.g. `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE`,
  `HISTORICAL_BACKFILL_NEEDS_VALIDATION`).
- Neither rule makes a quarter `unavailable` (SME explicitly: warnings only).
- `thirteenf_admin_dashboard._quarter_health` / `build_admin_tasks`
  surface the same findings, so a routine MVP3-02 `quality_check` run
  cannot mask MVP3-06/07 work by overwriting the latest visible
  `QualityReport13F.status`.
- Tests assert that opening one finding of each rule produces exactly one
  warning of the corresponding code, and that resolving the finding
  removes the warning.
- No mutation of existing finding rows from the readiness service (it is a
  read-only consumer of the audit trail).

## Scope Out

- New finding rule_codes (this task only consumes existing ones).
- Frontend readiness UI changes — keep that as a separate frontend task
  per dev-plan G4.
- Recompute pipeline implementation — invalidation is already complete
  from MVP3-06/07; recompute is a separate ownership-change consumer.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §10: readiness reflects
  current data reliability.
- `docs/tasks/2026-05-11_13f-mvp3-end-to-end-verification.md`: SME
  C2 entry that originated this task.
- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D4, D1: the two
  decisions whose findings need to be wired into readiness.

## Open Questions

- Should `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` cap a quarter's readiness at
  `usable_with_warning`, or is "ready with warning" too lenient when the
  ownership-change deltas are stale? PO call.
- Same question for `HISTORICAL_BACKFILL_NEEDS_VALIDATION`.
- Does the admin dashboard need a per-quarter "open findings by rule_code"
  breakdown, or is the count summary sufficient? Admin UX call.

## Test Plan (provisional)

- `docker compose exec api pytest -q tests/unit/test_13f_readiness.py`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
