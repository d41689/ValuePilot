# Next.js security upgrade

## Goal

Upgrade the frontend from the vulnerable Next.js 15.1.7 release to a patched,
compatible release, without mixing this dependency fix with product work.

This protects the reliability of every ValuePilot user workflow rather than
adding a new investment capability.

## Acceptance criteria

- `next` and `eslint-config-next` use the same patched release.
- The selected release addresses the official Next.js CVE-2025-66478 advisory.
- No known high or critical production dependency advisory remains.
- Frontend unit tests, lint, and production build pass in Docker.
- The canonical repository closing gate passes before merge.

## Scope

In scope: the Next.js security update, its lockfile changes, verification, and
this audit record.

Out of scope: feature changes, framework migrations unrelated to the security
fix, backend changes, and SEC/13F ingestion.

## References

- Official advisory: https://nextjs.org/blog/CVE-2025-66478
- Product contract: `AGENTS.md`

## Files to change

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/next-env.d.ts`
- `frontend/tsconfig.json`
- `frontend/.eslintrc.json` (removed)
- `frontend/eslint.config.mjs`
- `frontend/middleware.ts` (renamed)
- `frontend/proxy.ts`
- `docs/tasks/2026-09-03_nextjs-security-upgrade.md`

## Test plan

- Compare production dependency audit results before and after the update.
- `docker compose up -d --build`
- `docker compose exec -T api alembic upgrade head`
- `docker compose exec -T api pytest -q`
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec -T web npm run lint`
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

## Sign-off trail

- 2026-09-03: Work authorized; isolated branch created from `origin/main`.
- 2026-09-03: Registry audit showed that 15.1.9 and later 15.x releases still
  retained known vulnerabilities. Selected Next.js 16.3.4, upgraded Axios and
  PostCSS within their existing major versions, migrated lint to the ESLint
  CLI/flat config, and renamed the request boundary from `middleware` to the
  Next.js 16 `proxy` convention.
- 2026-09-03: Clean `npm ci` completed with zero vulnerabilities; all 216
  frontend unit tests, ESLint, TypeScript compilation, and the production
  Turbopack build passed in the Node 20 Docker image. The pull-request CI is the
  canonical full-stack closing gate.
