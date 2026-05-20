# Review result - Session refresh-token flow (2026-05-20)

## Second-pass verdict (2026-05-20)

**Approved after remediation.** The original blocking A4 issue is resolved at the
code level: login and refresh now pass the live page protocol into
`persistAuthSession`, and that helper adds `Secure` whenever the app is served
over HTTPS. The prior substring-matching and malformed-refresh-response
follow-ups were also fixed. The stateless refresh-token residual risk and the
missing interceptor-level tests are explicitly recorded in
`docs/tasks/2026-05-20_auth-hardening-followups.md`; they remain accepted
non-blocking debt for v0.1.

Important deployment caveat: the repo still does not prove production is
HTTPS-only. The application now behaves correctly for HTTPS traffic, but if a
real production entrypoint is exposed over plain HTTP, tokens still travel over
cleartext. That is an ops/deployment security requirement outside this code
change, not a remaining blocker in the refresh-token flow implementation.

Second-pass verification, run with the prompt's `docker compose run --rm
--no-deps` form:

- `docker compose run --rm --no-deps api pytest -q`: **864 passed, 3 warnings**.
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`:
  **152 passed**.
- `docker compose run --rm --no-deps web npm run lint`: **passed, no ESLint
  warnings or errors**.
- `docker compose run --rm --no-deps web npm run build`: **passed**.

## Original verdict

**Not approved yet.** The implementation is mostly correct and all verification
commands are green, but one security condition remains unaccepted: auth cookies
are written without `Secure`, and I could not confirm from repo evidence that
production is HTTPS-only. Because this change extends the effective token
exposure window from 30 minutes to a rolling 7 days, the merge bar should require
either adding `Secure` for production cookies or documenting/confirming the HTTPS
termination model and why omitting `Secure` is acceptable.

Secondary non-blocking follow-ups: add interceptor-level tests for single-flight
and retry behavior, consider a stricter non-refreshable URL matcher, and add a
defensive refresh-response shape guard before persisting tokens.

## A. Security

1. **Token never in a URL - PASS.** Backend `/auth/refresh` takes `body:
   RefreshRequest`, not a query parameter, and decodes `body.refresh_token`
   (`backend/app/api/v1/endpoints/auth.py:58-62`). The schema has a body field
   `refresh_token` (`backend/app/schemas/users.py:25-28`). Frontend refresh uses
   `axios.post(..., { refresh_token: refreshToken })`, so the token is in the
   JSON request body (`frontend/lib/api/client.ts:55-60`).

2. **Client-side JWT decode is UX-only - PASS.** `decodeJwtRole` explicitly
   decodes without signature verification and returns only the `role` claim
   (`frontend/lib/authSession.js:27-40`). That decoded role is written into
   `vp_role` for route gating (`frontend/lib/authSession.js:53-57`), and
   middleware uses cookie presence/role only to redirect routes
   (`frontend/middleware.ts:4-14`, `frontend/lib/authRoutes.js:20-30`).
   Server authorization independently decodes/verifies bearer tokens in
   `get_current_user`, rejects non-access tokens, reloads the DB user, and checks
   `is_active` (`backend/app/api/deps.py:28-50`). Admin authorization is enforced
   by `get_current_admin` (`backend/app/api/deps.py:53-56`) and admin endpoints
   depend on `AdminUser` (`backend/app/api/v1/endpoints/admin.py:13-30`,
   `backend/app/api/v1/endpoints/users.py:14-43`).

3. **Revocation blast radius - ACCEPT WITH EXPLICIT RESIDUAL RISK.**
   `/auth/refresh` re-checks the token type, user existence, and `user.is_active`
   before issuing a new pair (`backend/app/api/v1/endpoints/auth.py:65-75`), so a
   disabled or deleted account cannot keep refreshing. Residual risk remains:
   refresh tokens are stateless JWTs with no reuse detection, no rotation
   blacklist, and no revocation list. A stolen refresh token can be used until
   its 7-day expiration unless the user is disabled. I consider this acceptable
   for v0.1 only if it is tracked as auth hardening before broader rollout.

4. **Storage exposure - FLAG.** Tokens remain in `localStorage` and non-HttpOnly
   cookies via `persistAuthSession` (`frontend/lib/authSession.js:43-57`). This
   storage model existed before, but activating refresh extends effective
   exposure from a 30-minute access-token session to a rolling 7-day session.
   Cookies use `SameSite=Lax` and `path=/`, but no `Secure`
   (`frontend/lib/authSession.js:14-16`, `frontend/lib/authSession.js:53-57`;
   tests confirm the exact cookie strings at
   `frontend/lib/authSession.test.js:85-89`). I could not confirm HTTPS-only
   production from repo evidence: prod compose exposes HTTP service ports
   (`docker-compose.prod.yml:12-16`, `docker-compose.prod.yml:42-45`) and the
   deploy smoke checks use `http://127.0.0.1` (`scripts/deploy_prod_from_main.sh:53-54`).
   Before merge, either add a production `Secure` cookie path or document the
   HTTPS termination model and explicitly accept this risk.

## B. Correctness - interceptor

5. **Single-flight - PASS.** `refreshPromise` is module-scoped and created only
   when null (`frontend/lib/api/client.ts:33-45`). Concurrent 401s await the same
   promise through `runRefresh`, and `.finally` resets it to null so a later wave
   can start a fresh refresh (`frontend/lib/api/client.ts:38-44`). After a
   successful refresh each original request retries via `apiClient(originalRequest)`
   (`frontend/lib/api/client.ts:94-103`).

6. **No infinite loop - PASS.** The interceptor marks the original config
   `_retry = true` before retrying it (`frontend/lib/api/client.ts:94-103`).
   `shouldAttemptRefresh` refuses configs with `_retry`
   (`frontend/lib/authSession.js:64-71`), so a second 401 on the retried request
   falls into `handleAuthFailure` and rejects (`frontend/lib/api/client.ts:87-91`).

7. **No recursion - PASS.** Refresh uses the top-level `axios.post`, not
   `apiClient`, so it does not use the response interceptor
   (`frontend/lib/api/client.ts:55-60`). `NON_REFRESHABLE_PATHS` also excludes
   `/auth/refresh` as defense-in-depth (`frontend/lib/authSession.js:10-12`,
   `frontend/lib/authSession.js:69-71`).

8. **Refreshable vs terminal 401s - PASS.** A normal endpoint such as
   `/documents` returns true from `shouldAttemptRefresh`, covered by test
   evidence (`frontend/lib/authSession.test.js:92-97`). Auth endpoint 401s for
   `/auth/login`, `/auth/register`, and `/auth/refresh` return false
   (`frontend/lib/authSession.js:10-12`, `frontend/lib/authSession.js:69-71`;
   tested at `frontend/lib/authSession.test.js:109-117`). `handleAuthFailure`
   avoids redirecting when already on `/login`
   (`frontend/lib/api/client.ts:72-79`).

9. **Substring matching - ACCEPT WITH LOW-RISK FOLLOW-UP.**
   `shouldAttemptRefresh` uses `url.includes(path)` for non-refreshable paths
   (`frontend/lib/authSession.js:69-71`). A future legitimate path containing
   `/auth/login`, `/auth/register`, or `/auth/refresh` as a substring could be
   wrongly skipped. Existing API paths do not show such a case. This is not a
   blocker for the current route set, but a stricter pathname match would be
   safer.

10. **SSR safety - PASS.** Browser-only storage/header reads are guarded by
    `typeof window !== 'undefined'` in the request interceptor
    (`frontend/lib/api/client.ts:18-31`), refresh exits early on SSR
    (`frontend/lib/api/client.ts:47-50`), and auth failure handling exits early
    on SSR (`frontend/lib/api/client.ts:72-75`). The login page is a client
    component and also guards URL reads in `useEffect`
    (`frontend/app/(auth)/login/page.tsx:1`, `frontend/app/(auth)/login/page.tsx:34-40`).

11. **Malformed refresh response - ACCEPT WITH DEFENSIVE FOLLOW-UP.**
    `requestRefresh` persists `data.access_token` / `data.refresh_token` without
    checking shape (`frontend/lib/api/client.ts:55-66`). Backend `TokenResponse`
    requires both fields (`backend/app/schemas/users.py:59-62`), so normal server
    behavior is safe. If `access_token` is missing, the returned value is falsy
    and the caller clears the session (`frontend/lib/api/client.ts:94-99`), but
    a malformed partial response could briefly write inconsistent state before
    clearing. Add a guard before `persistAuthSession` as hardening, not as a
    current merge blocker.

## C. Token persistence consistency

12. **Single source of truth - PASS.** Login persists through
    `persistAuthSession` (`frontend/app/(auth)/login/page.tsx:51-56`), and
    refresh persists through the same helper (`frontend/lib/api/client.ts:61-65`).
    The helper owns localStorage keys and cookie attributes in one place
    (`frontend/lib/authSession.js:1-8`, `frontend/lib/authSession.js:43-57`), and
    tests assert the max-age and `SameSite` strings
    (`frontend/lib/authSession.test.js:71-89`).

13. **Cookie / token lifetime alignment - PASS WITH KNOWN UX TRADEOFF.** Every
    login/refresh re-stamps both `vp_access_token` and `vp_role` cookies with
    `max-age=604800` (`frontend/lib/authSession.js:5-8`,
    `frontend/lib/authSession.js:53-57`). Next middleware only checks cookie
    presence/role for route redirects (`frontend/middleware.ts:4-14`,
    `frontend/lib/authRoutes.js:20-30`). If cookies outlive an expired or revoked
    token, the API 401 path clears session and redirects (`frontend/lib/api/client.ts:87-99`);
    that may allow one protected page shell load before API failure, but it does
    not strand the user permanently.

## D. Tests

14. **Interceptor is not unit-tested - ACCEPT AS A CONSCIOUS GAP.** The added
    tests cover pure helpers (`frontend/lib/authSession.test.js:47-126`) but not
    the `client.ts` interceptor's single-flight/retry/recursion behavior. Given
    the repo had no `client.ts` tests before, this can be accepted for v0.1 only
    with a follow-up. For auth code, I would prefer adding an interceptor test
    before or soon after merge.

15. **Backend coverage - PASS.** The happy path posts refresh using `json=`
    (`backend/tests/unit/test_auth_api.py:25-33`). The rejection test sends an
    access token to `/auth/refresh` and expects a 401 with `"Token is not a
    refresh token"` (`backend/tests/unit/test_auth_api.py:35-52`).

## E. Behavioral regression

16. **Terminal failure path - PASS.** No refresh token returns null from
    `requestRefresh` (`frontend/lib/api/client.ts:47-54`), refresh failure is
    caught and returns null (`frontend/lib/api/client.ts:55-69`), and the caller
    clears session plus redirects on null (`frontend/lib/api/client.ts:94-99`).
    Non-refreshable 401s also call `handleAuthFailure`, which clears storage and
    cookies and redirects unless already on `/login`
    (`frontend/lib/api/client.ts:72-79`, `frontend/lib/api/client.ts:87-91`).

## Verification

All required commands passed on 2026-05-20:

- `docker compose run --rm --no-deps api pytest -q`: **864 passed, 3 warnings**.
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`:
  **150 passed**.
- `docker compose run --rm --no-deps web npm run lint`: **passed, no ESLint
  warnings or errors**.
- `docker compose run --rm --no-deps web npm run build`: **passed**.

## Required before approval

1. ~~Resolve A4: add `Secure` for production auth cookies, or document the
   HTTPS-only production termination model and explicitly accept the no-`Secure`
   risk for v0.1.~~ Resolved in second pass: `persistAuthSession` adds `Secure`
   when called from an HTTPS page, and both login/refresh pass
   `window.location.protocol === 'https:'`.
2. ~~Record A3 residual risk as a follow-up: stateless rolling refresh tokens
   have no reuse detection or rotation blacklist.~~ Resolved in second pass:
   recorded in `docs/tasks/2026-05-20_auth-hardening-followups.md`.

Recommended follow-ups: interceptor-level tests for `client.ts`, stricter
non-refreshable URL matching, and a refresh-response shape guard before token
persistence.

Second-pass update: stricter non-refreshable URL matching and the refresh
response shape guard are now implemented. Interceptor-level tests remain a
tracked non-blocking follow-up.
