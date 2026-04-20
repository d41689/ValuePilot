# Task: Fix watchlist frontend lint warnings

## Goal / Acceptance Criteria
- `frontend/app/(dashboard)/watchlist/page.tsx` no longer emits the existing React hooks lint warnings during `npm run lint`.
- Watchlist sorting and Fair Value edit synchronization behavior remain unchanged.
- The watchlist page still auto-refreshes prices once per active pool load.

## Scope
**In**
- Watchlist page React hook dependency cleanup.
- Small frontend helper extraction if needed to keep behavior testable and dependencies stable.
- Docker-based frontend verification.

**Out**
- Backend/API changes.
- Watchlist feature expansion or UI redesign.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Docker-based runtime / deployment expectations
- `docs/prd/value-pilot-prd-v0.1.md` -> UI & Query Semantics (V1)

## Files To Change
- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/lib/watchlistState.js` (new, if needed)
- `frontend/lib/watchlistState.d.ts` (new, if needed)
- `frontend/lib/watchlistState.test.js` (new, if needed)
- `docs/tasks/2026-04-20_fix-watchlist-frontend-lint-warnings.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Capture the watchlist-specific warning sources and extract any pure logic needed for testability.
2. Add a failing frontend unit test for the extracted watchlist state helpers.
3. Update the watchlist page to use stable derived values / effect wiring so the lint warnings disappear without changing behavior.
4. Verify in Docker:
   - `docker compose up -d --build web`
   - `docker compose exec web node --test lib/watchlistState.test.js`
   - `docker compose exec web npm run lint`

## Contract Checks
- Verification is run through Docker Compose only.
- No schema, parser, screener, formula, or lineage behavior changes.
- No raw SQL or eval/exec changes are introduced.

## Rollback Strategy
- Revert the watchlist page hook changes and any extracted helper/test files.
- Rebuild the `web` service and confirm the previous behavior returns.

## Progress Log
- [x] Inspect current warning sources in the watchlist page.
- [x] Add failing unit tests for extracted watchlist helpers.
- [x] Update watchlist page hook wiring and helper usage.
- [x] Re-run Docker verification.

## Notes / Decisions / Gotchas
- Current warnings are limited to `frontend/app/(dashboard)/watchlist/page.tsx`.
- Root causes observed so far:
  - `poolsQuery.data ?? []` and `membersQuery.data ?? []` create fresh array references on each render.
  - The auto-refresh effect references the refresh mutation without stable effect wiring.
- Added `frontend/lib/watchlistState.js` to isolate the pure watchlist state logic:
  - member sorting
  - fair-value edit map generation
  - fair-value edit diffing
- Added `frontend/lib/watchlistState.d.ts` so the TypeScript watchlist page consumes the JS helper with correct `Record<number, string>` typing during prod builds.
- Added `frontend/lib/watchlistState.test.js` first and confirmed the red phase:
  - initial Docker test run failed with `Cannot find module './watchlistState'`
- `docker compose up -d --build web` collided with the prod API port already in use on this machine, so verification was performed with one-off Docker commands instead:
  - `docker compose run --rm --no-deps web node --test ...`
  - `docker compose run --rm --no-deps web npm run lint`
- Follow-up compatibility adjustment:
  - Replaced `useEffectEvent` with a `useRef`-backed callback because the current React version in this repo does not export `useEffectEvent` during prod builds.
- Cleaned up the temporary dev containers with `docker compose down` after verification.

## Verification Results
- `docker compose run --rm --no-deps web node --test lib/watchlistState.test.js` -> fail first (`Cannot find module './watchlistState'`), then pass after implementation
- `docker compose run --rm --no-deps web npm run lint` -> pass with `✔ No ESLint warnings or errors`
- `docker compose down` -> pass (temporary dev containers removed)
