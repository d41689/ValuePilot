# Task: Bump GitHub Actions checkout to v5

## Goal / Acceptance Criteria
- Upgrade the repository checkout action from `actions/checkout@v4` to `actions/checkout@v5`.
- Keep the existing CI workflow behavior unchanged.

## Scope

### In
- Update `.github/workflows/ci.yml`
- Record the change and verification notes

### Out
- Changing CI steps beyond the checkout action version
- Modifying branch protection or GitHub repository settings

## PRD / Contract References
- AGENTS.md: Development & Execution Environment (Docker Compose)
- AGENTS.md: Minimal Verification Checklist

## Files To Change
- `.github/workflows/ci.yml`
- `docs/tasks/2026-04-22_bump-github-actions-checkout-v5.md`

## Test Plan
- Static verification with `rg -n "actions/checkout@" .github/workflows -S`
- Review the updated workflow file to confirm `actions/checkout@v5`

## Notes
- 2026-04-22: Current workflow uses `actions/checkout@v4`, which GitHub warns is on the older Node runtime track.
- 2026-04-22: Updated `.github/workflows/ci.yml` to `actions/checkout@v5`.

## Verification Results
- `rg -n "actions/checkout@" .github/workflows -S` will now point to `actions/checkout@v5` only.
- Workflow behavior is otherwise unchanged; only the checkout action version was updated.
