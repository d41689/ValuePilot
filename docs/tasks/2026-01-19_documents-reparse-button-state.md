# Task: Documents Reparse Button State

## Goal / Acceptance Criteria
- Clicking Reparse on one document only disables that row's button, not all rows.
- Once the reparse request completes or fails, the button re-enables.

## Scope
- In scope: frontend state management in Documents page.
- Out of scope: backend changes, API behavior changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md`
- `AGENTS.md`

## Files to change
- `frontend/app/(dashboard)/documents/page.tsx`

## Plan
1. Track the active reparse document ID in state.
2. Disable only the matching row while mutation is pending.
3. Clear the active ID on success or error.

## Rollback Strategy
- Revert state changes if UI behavior regresses.

## Test Plan (Docker)
- Manual verification in browser.
