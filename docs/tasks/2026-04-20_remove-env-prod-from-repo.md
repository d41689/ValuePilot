# Task: Remove .env.prod from repo tracking

## Goal / Acceptance Criteria
- `.env.prod` is no longer tracked by git.
- Local `.env.prod` remains available on disk for runtime use.
- A safe template file exists for collaborators to copy from.
- `.gitignore` prevents `.env.prod` from being re-added accidentally.

## Scope
**In**
- Root `.gitignore`
- Root `.env.prod.example`
- Git index cleanup for `.env.prod`

**Out**
- Git history rewriting
- Secret rotation
- Runtime config changes beyond preserving the current local file

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Docker-based runtime / deployment expectations

## Files To Change
- `.gitignore`
- `.env.prod.example` (new)
- `docs/tasks/2026-04-20_remove-env-prod-from-repo.md` (this file)

## Execution Plan (Assumed approved per direct request)
1. Add `.env.prod` to `.gitignore`.
2. Create `.env.prod.example` with safe template values.
3. Remove `.env.prod` from git tracking while keeping the local file on disk.
4. Verify `.env.prod` is ignored and `.env.prod.example` is tracked.

## Contract Checks
- No application code, schema, parser, screener, formula, or lineage behavior changes.
- Local runtime config file remains present after the git index cleanup.

## Rollback Strategy
- Re-add `.env.prod` to git tracking if explicitly requested.
- Remove `.env.prod.example` and revert `.gitignore` changes.

## Progress Log
- [x] Add ignore rule and example file.
- [x] Remove `.env.prod` from git tracking.
- [x] Verify local file remains and is ignored.

## Notes / Decisions / Gotchas
- Current tracked `.env.prod` contains only local/default prod connection values, but it should still be removed from version control.

## Verification Results
- `git rm --cached .env.prod` -> removed from git index while leaving local file on disk
- `ls -la .env.prod .env.prod.example` -> both files present locally
- `git check-ignore -v .env.prod` -> `.env.prod` is ignored by `.gitignore`
- `git ls-files .env.prod` -> no output (no longer tracked)
- `git ls-files .env.prod.example` -> pending add in working tree, ready to be tracked on next commit
