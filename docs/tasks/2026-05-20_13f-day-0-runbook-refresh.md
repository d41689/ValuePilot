# 13F Day-0 Runbook Refresh

## Goal / Acceptance Criteria

- Update PR #42 so it is not merged as a stale one-section runbook patch.
- Keep the useful "Admin Tasks panel vs retry controls" guidance.
- Refresh the Day-0 operator path to match the shipped automatic pipeline:
  `THIRTEENF_START_QUARTER` -> boot reconcile -> `quarterly_pipeline` -> Oracle's Lens scoring -> `/watchlist`.

## Scope

- In: `docs/tasks/2026-05-19_13f-day-0-operator-runbook.md`.
- Out: backend/frontend behavior changes.

## PRD References

- 13F automation PRD: "configure a start date and walk away" target state.
- PR #56 hardening: reconcile remains data-state driven and signals are the terminal output.

## Files To Change

- `docs/tasks/2026-05-19_13f-day-0-operator-runbook.md`

## Test Plan

- Markdown-only change.
- Visual sanity-check in diff/GitHub.

