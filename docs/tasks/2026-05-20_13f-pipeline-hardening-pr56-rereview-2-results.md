# 13F Pipeline Hardening PR #56 Re-Review 2 Results

Reviewed worktree: `.claude/worktrees/optimistic-hofstadter-630d85`

Reviewed commits:

- `26591b6 Address external review of PRs #45-#55: pipeline txn boundaries + safety`
- `b03f0c0 PR #56 re-review P1: don't treat a succeeded scoring job as coverage`

## Summary

The prior P1 is fixed. `_has_meaningful_coverage()` is now anchored strictly on `oracles_lens_signals` row existence and no longer treats a succeeded `oracles_lens_score_backfill` job as coverage. The updated tests assert both sides of that contract:

- A succeeded scoring job with zero signal rows is **not** coverage.
- A quarter with at least one signal row **is** coverage.

I do not see a remaining code blocker from this incremental fix.

## Findings

### P3 - Remediation task log still has stale old-description lines

File: `.claude/worktrees/optimistic-hofstadter-630d85/docs/tasks/2026-05-20_13f-review-remediation.md:22`

The later "PR #56 re-review" section correctly says the scoring-job shortcut was removed. But the earlier disposition table still says `_has_meaningful_coverage` "also accepts a succeeded scoring job", and the files-to-change note still mentions the "scoring-job branch". That is now stale and can confuse the paper trail.

Recommendation: update those two lines before merge, or leave as a harmless doc nit if the PR description clearly states the final behavior.

## Confirmed

- `backend/app/services/thirteenf_start_quarter.py:105` returns true only when an `OraclesLensSignal` row exists for the quarter.
- The `JobRun` import was removed from `thirteenf_start_quarter.py`.
- `backend/tests/unit/test_thirteenf_start_quarter.py:72` covers the rejected shortcut directly.
- `latest_scoreable_quarter()` still excludes in-progress quarters, so the revert to signal-row-only should not spin on structurally unavailable current-quarter data.

## Recommendation

PR #56 is acceptable to merge after CI is green. I would ask for the small stale-doc cleanup if convenient, but I would not block the code merge on it.

The remaining follow-ups from the prior review are still valid:

- Phase 3 rollback can drop failed-parse audit rows.
- Phase 4 solo activation bypasses shared active-filing policy.
- Stale routing warnings/errors are not cleared on clean reroute.
- Scoring internal commit split-brain window.
- Storage should move out of the CI workspace.
- Full transaction/amendment regression tests.

