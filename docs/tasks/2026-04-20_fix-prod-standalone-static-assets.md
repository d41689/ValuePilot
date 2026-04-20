# Task: Fix prod standalone static asset 404s

## Goal / Acceptance Criteria
- ValuePilot prod frontend serves `/_next/static/*` assets correctly when running with Next.js standalone output.
- `https://invest.richmom.vip/login` loads without 404s for CSS, JS chunks, or font assets.
- The prod frontend continues to proxy `/api/v1/*` requests to the prod API correctly.

## Scope
**In**
- Production frontend startup path for standalone output.
- Docker-based verification of prod asset serving and API proxy behavior.

**Out**
- Frontend feature changes.
- Backend/API contract changes.
- CDN or Cloudflare cache rule changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Docker-based runtime / deployment expectations

## Files To Change
- `docker-compose.prod.yml`
- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/lib/watchlistState.d.ts`
- `docs/tasks/2026-04-20_fix-prod-standalone-static-assets.md` (this file)

## Execution Plan (Assumed approved per direct fix request)
1. Reproduce the current prod failure for `/_next/static/*` assets.
2. Update the prod standalone startup command so static assets and `public/` are available under the standalone runtime directory.
3. Rebuild and restart the prod web container.
4. Verify:
   - `/_next/static/*` asset requests return `200`
   - `https://invest.richmom.vip/login` no longer serves the observed 404 asset URLs
   - `/api/v1/auth/login` still proxies to the prod API

## Contract Checks
- Verification is run through Docker Compose only.
- No schema, parser, screener, formula, or lineage behavior changes.
- No raw SQL or eval/exec changes are introduced.

## Rollback Strategy
- Restore the previous prod `web` startup command in `docker-compose.prod.yml`.
- Rebuild and restart the prod stack.

## Progress Log
- [x] Reproduce current static asset 404s on prod.
- [x] Update standalone startup path to include static assets.
- [x] Rebuild and verify prod web.

## Notes / Decisions / Gotchas
- Reproduction confirmed:
  - `GET /login` returns `200`
  - `GET /_next/static/chunks/main-app-ac982fbdfebce8f5.js` returns `404`
- Inspection inside the running prod container showed:
  - `.next/static/*` exists under `/app/.next/static`
  - `.next/standalone/.next/static` is missing
- Next standalone expects static assets to be available relative to the standalone runtime directory, so the current startup command is incomplete.
- During the first rebuild, prod `next build` exposed a separate frontend compatibility issue introduced earlier:
  - `useEffectEvent` is not exported by the current React version in this repo
  - `watchlistState.js` needed a `.d.ts` file so TypeScript could type the helper return values correctly in the watchlist page
- Fixed that prerequisite by:
  - replacing `useEffectEvent` with a `useRef`-backed mutation callback in `frontend/app/(dashboard)/watchlist/page.tsx`
  - adding `frontend/lib/watchlistState.d.ts`
- Updated prod standalone startup to:
  - build
  - copy `.next/static` into `.next/standalone/.next/static`
  - copy `public/` into `.next/standalone/public` when present
  - `cd .next/standalone && node server.js`

## Verification Results
- `docker compose -f docker-compose.prod.yml up -d --build web` -> pass
- `docker compose -f docker-compose.prod.yml logs --tail=120 web` -> build passes and standalone server reaches `✓ Ready`
- `python3` check against `http://localhost:3101/login` -> 19 referenced `/_next/static/*` assets all return `200`
- `curl -I https://invest.richmom.vip/login` -> `200`
- `curl -I https://invest.richmom.vip/_next/static/chunks/main-app-ac982fbdfebce8f5.js` -> `200`
- `curl -I https://invest.richmom.vip/_next/static/css/2fa77a11b13c5faf.css` -> `200`
- `curl -I https://invest.richmom.vip/_next/static/chunks/app/(auth)/login/page-9b8af39993f19778.js` -> `200`
- `curl -d '{}' https://invest.richmom.vip/api/v1/auth/login` -> `422` with missing `email` / `password`, confirming the frontend still proxies to the prod API
