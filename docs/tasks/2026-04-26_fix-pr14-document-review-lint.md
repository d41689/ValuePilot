# Task: Fix PR 14 document review lint failure

## Goal / Acceptance Criteria
- Fix the frontend lint error reported by PR #14.
- Keep the existing document review total return behavior unchanged.
- Push the fix to the existing PR branch.

## Scope
**In**
- Minimal lint-only fix in document review frontend helper code.
- Docker verification for frontend lint and relevant frontend tests.

**Out**
- Parser changes.
- Backend API behavior changes.
- F-Score plan document changes.

## Files To Change
- `docs/tasks/2026-04-26_fix-pr14-document-review-lint.md`
- `frontend/lib/documentReview.js`

## Test Plan
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/documentReview.test.js`

## Progress Log
- [x] Inspect PR #14 failed CI job.
- [x] Identify lint error.
- [x] Apply minimal lint fix.
- [x] Run Docker verification.
- [x] Push fix to PR branch.

## Notes / Decisions / Gotchas
- CI failed on `@typescript-eslint/no-unused-vars` for a destructured `sortKey` discard variable.
- Leave the untracked F-Score plan document out of this PR fix.

## Verification Results
- `docker compose exec web npm run lint` passed with no ESLint warnings or errors.
- `docker compose exec web node --test lib/documentReview.test.js` passed: 18 tests passed.
