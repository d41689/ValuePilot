# Rate Guard singleton enforcement

## Goal

Ensure every live ValuePilot SEC request from development and production reaches
one central Rate Guard process and therefore one shared `edgar` rate-limit bucket.

## Acceptance criteria

- Rate Guard exposes an authenticated, persistent instance identity.
- Live clients fail closed when the configured Rate Guard identity is missing,
  unreachable, malformed, or different from the expected identity.
- Production uses the central container's internal URL; development uses the
  authenticated public URL that is verified to terminate at that same process.
- The production deploy compares internal and public identities before starting
  the production API and injects the verified identity without storing it as a
  secret.
- 13F and SEC financial ingestion continue to use `upstream="edgar"`; a source
  guard prevents introducing direct SEC HTTP calls in business code.
- When merged to `main`, CI and the self-hosted production deployment succeed;
  post-deploy evidence proves the development and production entry points expose
  the same instance identity.

## Scope

### In

- Rate Guard identity lifecycle and endpoint.
- Backend identity verification and live-mode startup gate.
- Development/production Compose topology and deployment verification.
- Tests, runbook updates, and local development cutover after production deploy.

### Out

- Changing SEC parsing, financial publication, or 13F semantics.
- Changing the global EDGAR request rate.
- Calling SEC as part of deployment verification.

## References

- `rate-guard/README.md`
- `docs/architecture/rate-guard-public-exposure.md`
- `docs/architecture/coverage-source-policy.md`

## Files expected to change

- `rate-guard/app/`
- `rate-guard/tests/`
- `backend/app/core/config.py`
- `backend/app/rate_guard/client.py`
- `backend/app/main.py`
- `backend/tests/`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `scripts/deploy_prod_from_main.sh`
- Rate Guard documentation and examples

## Test plan

- Targeted backend and Rate Guard tests first.
- `docker compose up -d --build`
- `docker compose exec -T api alembic upgrade head`
- `docker compose exec -T api pytest -q`
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec -T web npm run lint`
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
- Rate Guard full test suite as executed by CI.
- After merge: verify GitHub deployment success and compare authenticated
  `/v1/identity` responses through the production internal and development
  public entry points without contacting SEC.

## Sign-off trail

- 2026-08-29: Current development internal endpoint and public endpoint returned
  different in-memory EDGAR metrics, confirming two running Rate Guard instances.
- 2026-08-29: User approved central-singleton implementation and main-triggered
  production deployment.
- 2026-08-29: Added persistent identity, authenticated identity endpoint,
  fail-closed API startup verification, fixed dev/prod ingress ownership,
  deployment identity comparison, and a direct-SEC source guard.
- 2026-08-29: Closing gate passed: isolated-schema Alembic upgrade, 1,512
  backend tests, 216 frontend tests, frontend lint/build, 39 Rate Guard tests,
  topology guard, shell syntax checks, and `git diff --check`. The temporary
  migration schema was deleted after verification; existing development data
  was not changed. The ordinary shared-schema migration command is unavailable
  from `main` because the shared database already contains PR #128's unmerged
  revision `20260828500000`.
