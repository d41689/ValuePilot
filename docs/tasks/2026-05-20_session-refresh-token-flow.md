# 2026-05-20 — Wire up refresh-token flow so sessions last one week

## Goal / Acceptance Criteria

- A logged-in user stays authenticated for **one week** instead of being forced
  back to `/login` 30 minutes after login.
- Achieved by **activating the existing refresh-token flow** (not by widening the
  access-token TTL): the 30-minute access token is silently renewed via
  `POST /auth/refresh` using the 7-day refresh token.
- Effective session = the 7-day refresh-token window. Each refresh issues a fresh
  refresh token, so the week is a **rolling idle window**: active users never get
  logged out; 7 days of inactivity forces a re-login.
- Acceptance:
  - Frontend `apiClient` intercepts a `401`, calls `/auth/refresh`, persists the
    new tokens, and transparently retries the original request.
  - Concurrent `401`s share a single in-flight refresh call (single-flight).
  - A failed refresh (expired/missing refresh token) clears the session and
    redirects to `/login` — preserving today's behaviour for that terminal case.
  - Canonical CI commands green in containers.

## Background — current state (confirmed by reading the code)

- `login` issues an access token (`ACCESS_TOKEN_EXPIRE_MINUTES = 30`) and a
  refresh token (`REFRESH_TOKEN_EXPIRE_DAYS = 7`).
- `backend/app/api/deps.py` enforces the access token's `exp` on every request.
- `frontend/lib/api/client.ts` **never calls `/auth/refresh`** — on any `401` it
  clears the session and redirects to `/login`.
- Net effect: the effective session is **30 minutes**; the 7-day refresh token and
  the 7-day `vp_access_token` cookie `max-age` were dead weight.
- `REFRESH_TOKEN_EXPIRE_DAYS` is **already 7** — no duration constant needs
  changing. "One week" comes from activating the unused refresh token.

## Scope

In:
- Frontend response interceptor: refresh-on-401 + retry + single-flight.
- Pure, testable auth-session helpers (`persistAuthSession`, `decodeJwtRole`,
  `shouldAttemptRefresh`) in `frontend/lib/authSession.js`.
- Refactor the login page to persist tokens via the shared helper (single source
  of truth for cookie `max-age` / `SameSite`).
- Backend `/auth/refresh`: accept the refresh token in a **JSON body** instead of
  a query parameter (tokens in URLs leak into access logs). First real consumer
  is being added now, so this is the moment to fix it properly (no band-aid).

Out:
- No change to `ACCESS_TOKEN_EXPIRE_MINUTES` (stays 30 — short access token +
  silent refresh is the whole point of this approach).
- No change to `REFRESH_TOKEN_EXPIRE_DAYS` (already 7).
- No server-side session store / token revocation list.

## Files to change

- `frontend/lib/authSession.js` — add `persistAuthSession`, `decodeJwtRole`,
  `shouldAttemptRefresh`, `AUTH_SESSION_MAX_AGE_SECONDS`.
- `frontend/lib/authSession.test.js` — tests for the three new helpers.
- `frontend/lib/api/client.ts` — refresh-on-401 interceptor with single-flight.
- `frontend/app/(auth)/login/page.tsx` — use `persistAuthSession`.
- `backend/app/schemas/users.py` — add `RefreshRequest`.
- `backend/app/api/v1/endpoints/auth.py` — `/auth/refresh` takes a JSON body.
- `backend/tests/unit/test_auth_api.py` — refresh via `json=`; add a
  non-refresh-token rejection test.

## Test plan (Docker)

NOTE: the prod stack holds ports 8101/3101 on this host, so `docker compose up`
for dev `api`/`web` cannot bind. Verification uses `docker compose run --rm`
(no published ports → no conflict, prod untouched). The dev `db` is already up.

- Backend: `docker compose run --rm --no-deps api pytest -q`
- Frontend tests: `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`
- Frontend lint: `docker compose run --rm --no-deps web npm run lint`
- Frontend build: `docker compose run --rm --no-deps web npm run build`

## Notes / decisions

- 2026-05-20: User (acting senior engineer) chose Option B — activate refresh
  flow — over Option A (bump access-token TTL to 7 days). Rationale: short access
  token keeps the revocation blast-radius small; the refresh token already
  encodes the 7-day policy.
- Single-flight refresh: a module-level promise dedupes concurrent `401`s so only
  one `/auth/refresh` call is made per wave.
- Refresh uses a bare `axios` call (no interceptors) so a failed refresh cannot
  recurse into itself.
- `_retry` flag on the request config prevents an infinite refresh/retry loop.

## Sign-off (2026-05-20)

Implemented and verified.

- Backend `/auth/refresh` now takes a JSON body (`RefreshRequest`); added a test
  that an access token is rejected where a refresh token is required.
- Frontend `apiClient` refreshes on 401, single-flight, retries the original
  request; terminal failure clears the session and redirects to `/login`.
- Login page persists tokens via the shared `persistAuthSession` helper.

Verification (run via `docker compose run --rm --no-deps` — the prod stack holds
ports 8101/3101, so `docker compose up` for dev `api`/`web` cannot bind):

- Backend `pytest -q` (full): **864 passed**.
- Frontend `node --test lib/*.test.js`: **150 passed**.
- Frontend `npm run lint`: clean.
- Frontend `npm run build`: succeeded.

Gotcha encountered: the dev DB (`valuepilot-dev-db-1`) was behind the checked-in
migrations (the dev `api` container never started due to the port conflict, so
its startup migrations never ran). `alembic upgrade head` applied 17 pending
migrations to bring it to schema; the full suite was green afterwards.

## Review remediation (2026-05-20)

External review (`2026-05-20_session-refresh-token-flow-review-result.md`)
verdict was **not approved yet** — one blocking security item plus a few
non-blocking follow-ups. Addressed:

### A4 (BLOCKER) — `Secure` cookie flag

Investigated the production TLS model: the repo has **no in-repo TLS terminator**
(no nginx/caddy/traefik config); `docker-compose.prod.yml` serves plain HTTP on
`:3101`/`:8101`, and no canonical HTTPS `BASE_URL` is recorded in `.env`/`.env.prod`.
TLS termination, if any, is external to this repo — so the repo genuinely cannot
assert HTTPS-only prod.

Fix: `persistAuthSession` now adds the `Secure` cookie attribute **adaptively**,
gated on the live page protocol (`window.location.protocol === 'https:'`, passed
in by both callers). This adds `Secure` exactly when the connection is HTTPS —
where it both matters and works — and never breaks `http://localhost` dev or a
plain-HTTP deployment (a `Secure` cookie is silently dropped over plain HTTP).
No need to hard-code or guess the deployment's TLS model.

### A3 — refresh-token revocation gap

Recorded as tracked debt in `docs/tasks/2026-05-20_auth-hardening-followups.md`
(stateless refresh tokens, no reuse detection / rotation blacklist / revocation
list). Accepted for v0.1; to be addressed before broader rollout.

### Non-blocking review items also fixed now (cheap, same files)

- Item 9: `shouldAttemptRefresh` strips the query string and matches the path
  exactly or as a trailing segment (was a loose substring `includes`).
- Item 11: `requestRefresh` guards that `access_token` / `refresh_token` are
  present before persisting.
- Item 14 (interceptor-level tests): recorded as a follow-up in
  `2026-05-20_auth-hardening-followups.md` — accepted by the reviewer as a
  conscious gap.

Re-verification after remediation (frontend only — no backend file changed):

- Frontend `node --test lib/*.test.js`: **152 passed** (2 new cookie/URL tests).
- Frontend `npm run lint`: clean.
- Frontend `npm run build`: succeeded.
- Backend suite unchanged from the 864-passed run (no backend file touched).
