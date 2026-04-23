# Task: Fix prod deploy failure from DCF page type mismatch

## Goal / Acceptance Criteria
- Fix the frontend TypeScript type error blocking prod `next build`.
- Add a CI step that runs the frontend production build so deploy-only failures are caught earlier.
- Verify the frontend builds successfully in Docker.

## Scope
**In**
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `.github/workflows/ci.yml`
- `frontend/components/ui/toast.tsx`
- `frontend/components/ui/use-toast.ts`
- `frontend/pages/_document.tsx`
- `frontend/pages/_error.tsx`
- `frontend/pages/404.tsx`
- Task log updates

**Out**
- Backend changes
- Deployment workflow changes beyond CI verification

## PRD References
- `AGENTS.md` -> Docker-only verification, task logging

## Files To Change
- `docs/tasks/2026-04-23_fix-prod-deploy-next-build-dcf-types.md`
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `.github/workflows/ci.yml`

## Execution Plan
1. Fix the DCF page payload typing so `dcf_inputs` / `dcf_inputs_series` match the actual response contract.
2. Keep the DCF page provenance label typing compatible with TypeScript's strict inference.
3. Mark toast modules as client components so they are safe in production builds.
4. Add `next build` to CI and force `NODE_ENV=production` so CI matches deploy.
5. Verify with Dockerized frontend production build and lint.

## Contract Checks
- Keep the DCF page payload contract aligned with `frontend/lib/dcfInputsSeries.d.ts`.
- CI should validate the same production build path used by deploy.

## Rollback Strategy
- Revert the typing and CI changes if they introduce unrelated build regressions.

## Progress Log
- [x] Fix DCF payload typing.
- [x] Add missing `string[]` annotation for provenance label assembly.
- [x] Mark toast modules as client components.
- [x] Add frontend production build to CI with `NODE_ENV=production`.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Deploy was failing in prod because CI never exercised `next build`.
- The GitHub deploy log only showed the DCF type error. Additional `/404` build failures reproduced locally only when `next build` was run inside the dev container with `NODE_ENV=development`, which is not representative of prod.
- The existing `pages/_document.tsx`, `pages/_error.tsx`, and `pages/404.tsx` were restored; prod build succeeds with them present.

## Verification Results
- `gh run view 24853398068 --log | grep -nE "dcf_inputs|dcf_inputs_series|Type '\\{\\} \\| null'"` confirms the deploy failure was the DCF payload type mismatch.
- `docker compose exec -T web npm run lint` ✅
- `docker compose exec -T web sh -lc 'cd /app && NODE_ENV=production npm run build'` ✅
