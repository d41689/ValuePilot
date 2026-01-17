# Task: Documents Reparse Toasts

## Goal / Acceptance Criteria
- Show a toast on reparse success.
- Show a toast on reparse error.
- Toast is visible regardless of page scroll/overflow (rendered in a top-level overlay).

## Scope
- In scope: frontend toast state in Documents page.
- Out of scope: backend changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md`
- `AGENTS.md`

## Files to change
- `frontend/app/(dashboard)/documents/page.tsx`

## Plan
1. Render toast in a top-level overlay (portal) with auto-dismiss timer.
2. Hook reparse success/error handlers to trigger toasts.

## Rollback Strategy
- Revert toast state if UI regressions occur.

## Test Plan (Docker)
- Manual verification in browser.

## Verification
- Manual: click Reparse and confirm success/error toast appears and auto-dismisses.
