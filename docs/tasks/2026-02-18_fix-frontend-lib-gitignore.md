# Fix frontend/lib missing after clone

## Goal / Acceptance Criteria
- Fix `Module not found: Can't resolve '@/lib/utils'` on fresh clone.
- Ensure `frontend/lib` files are tracked by git and available on other machines.
- Verify `docker compose up -d --build` + frontend compile works.

## Scope
- In:
  - `.gitignore` adjustment for `frontend/lib`
  - Add minimal required files under `frontend/lib`
  - Docker verification via `web` service
- Out:
  - No unrelated frontend refactor
  - No backend behavior changes

## Files to change
- `.gitignore`
- `frontend/lib/utils.ts`
- `frontend/lib/api/client.ts`
- `frontend/lib/api/server-client.ts`
- `frontend/lib/api/endpoints/ingestion.ts`
- `frontend/lib/api/endpoints/stocks.ts`
- `frontend/lib/stockRoutes.js`
- `frontend/lib/stockRoutes.d.ts`
- `frontend/lib/dcfMath.js`
- `frontend/lib/dcfMath.d.ts`
- `frontend/lib/dcfInputsSeries.js`
- `frontend/lib/dcfInputsSeries.d.ts`
- `frontend/lib/store/userStore.ts`

## Test plan (Docker)
- `docker compose up -d --build`
- `docker compose exec web npm run lint`
- `docker compose logs web --tail=200` (confirm no `@/lib/utils` module-not-found)

## Progress log
- [x] Root cause identified: `.gitignore` contains `lib/`, causing `frontend/lib` to be absent in clone.
- [x] Apply minimal file tracking fix
- [x] Run docker verification

## Notes / Decisions / Gotchas
- Root cause is repository packaging, not runtime config:
  - `.gitignore` had `lib/`, which ignored `frontend/lib/*`.
  - Existing dev machine had local files, but fresh clones did not.
- Minimal fix:
  - Change `.gitignore` from `lib/` and `lib64/` to `/lib/` and `/lib64/` so only repository root paths are ignored.
  - Keep `frontend/lib` available for tracking.

## Verification results (Docker)
- `docker compose up -d --build` ✅
- `docker compose logs --tail=200 web` ✅ no `Can't resolve '@/lib/utils'` error
- `docker compose exec web npm run lint` ✅ passes (warnings only, no errors)
