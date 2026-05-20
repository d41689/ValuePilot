# Review prompt — Session refresh-token flow (2026-05-20)

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-20_session-refresh-token-flow.md` and the diff on branch.

---

## Reviewer brief

You are reviewing an **authentication change** to ValuePilot. Auth code — review
it with security-grade scrutiny, not a glance. The change **activates the
existing-but-dormant refresh-token flow** so a logged-in user stays
authenticated for one week instead of being forced back to `/login` 30 minutes
after login.

### What changed and why

- Before: login issued a 30-min access token + a 7-day refresh token, but the
  frontend **never called `/auth/refresh`** — on any 401 it cleared the session
  and redirected to `/login`. Effective session = 30 minutes.
- After: the access token stays 30 minutes; the frontend silently refreshes it
  via `POST /auth/refresh` using the 7-day refresh token. Effective session =
  the 7-day refresh-token window, **rolling** (each refresh issues a fresh
  refresh token, so the week is an idle timeout, not a hard cap).
- No duration constant changed: `ACCESS_TOKEN_EXPIRE_MINUTES` is still 30,
  `REFRESH_TOKEN_EXPIRE_DAYS` is still 7. "One week" comes purely from wiring up
  the unused refresh token.

### Files in scope

- `backend/app/api/v1/endpoints/auth.py` — `/auth/refresh` takes a JSON body.
- `backend/app/schemas/users.py` — new `RefreshRequest`.
- `backend/tests/unit/test_auth_api.py` — refresh via `json=`; new rejection test.
- `frontend/lib/api/client.ts` — refresh-on-401 interceptor (single-flight + retry).
- `frontend/lib/authSession.js` — new `persistAuthSession`, `decodeJwtRole`,
  `shouldAttemptRefresh`, `AUTH_SESSION_MAX_AGE_SECONDS`.
- `frontend/lib/authSession.test.js` — tests for the new helpers.
- `frontend/app/(auth)/login/page.tsx` — persists tokens via `persistAuthSession`.

## Answer every question below with a verdict + file:line evidence

### A. Security

1. **Token never in a URL.** Confirm the refresh token travels only in the JSON
   request body — backend endpoint signature and the frontend `axios.post` call.
   A token in a query string leaks into access logs, history, and Referer.
2. **Client-side JWT decode is UX-only.** `decodeJwtRole` decodes the JWT
   *without verifying the signature*. Confirm its output (`role`) feeds only
   client-side route gating, and that the server independently enforces authz
   (`get_current_admin` in `deps.py`). A user who hand-edits the `vp_role`
   cookie must gain nothing — verify the API is the real boundary.
3. **Revocation blast radius.** JWTs are stateless; there is no revocation list.
   With a rolling 7-day refresh token: (a) confirm `/auth/refresh` re-checks
   `user.is_active` / user existence so a disabled account cannot keep
   refreshing; (b) state the residual risk — a stolen refresh token is usable
   for up to 7 days and there is **no refresh-token reuse detection / rotation
   blacklist**. Is that acceptable for v0.1, or should it be a follow-up?
4. **Storage exposure.** Tokens live in `localStorage` and in non-`HttpOnly`
   cookies (pre-existing design). The change does not worsen the storage model
   but it does extend the *effective* exposure window from 30 min to ~7 days.
   Explicitly accept or flag. Also check the cookies: `SameSite=Lax`, no
   `Secure` flag — confirm whether prod is HTTPS-only and whether `Secure`
   should be added while this code is being touched.

### B. Correctness — the interceptor (`client.ts`)

5. **Single-flight.** Trace a wave of 5 concurrent requests all getting 401.
   Exactly one `/auth/refresh` call should be made; all 5 originals should be
   retried. Confirm `refreshPromise` is created once and reset in `.finally`,
   and that a later 401 wave starts a fresh refresh.
6. **No infinite loop.** `_retry` is set on `error.config`. Confirm axios reuses
   the same config object when the request is retried via `apiClient(originalRequest)`,
   so a *second* 401 on the retried request has `_retry === true`, fails
   `shouldAttemptRefresh`, and terminates via `handleAuthFailure` (clear +
   redirect) instead of looping.
7. **No recursion.** The refresh call uses a **bare `axios`** instance (no
   interceptors). Confirm a failing `/auth/refresh` cannot re-enter the response
   interceptor. `NON_REFRESHABLE_PATHS` is defense-in-depth — confirm it.
8. **Refreshable vs terminal 401s.** Confirm a 401 from a normal authenticated
   endpoint (e.g. `/auth/me`, `/documents`) **does** trigger refresh, while a
   401 from `/auth/login` (wrong credentials) does **not** — and causes no
   redirect loop when already on `/login`.
9. **Substring matching.** `shouldAttemptRefresh` excludes paths via
   `url.includes(...)`. Could a legitimate endpoint path contain `/auth/login`,
   `/auth/register`, or `/auth/refresh` as a substring and be wrongly skipped?
   Assess whether `includes` should be a stricter match.
10. **SSR safety.** Confirm `typeof window === 'undefined'` guards mean none of
    the new code runs (or throws) during server rendering.
11. **Malformed refresh response.** `requestRefresh` does not check that
    `data.access_token` exists before persisting. Decide if a guard is needed.

### C. Token persistence consistency

12. **Single source of truth.** Login and refresh both persist via
    `persistAuthSession`. Confirm the cookie attributes (`max-age`, `SameSite`,
    `path`) and the localStorage keys are now written in exactly one place and
    cannot drift.
13. **Cookie / token lifetime alignment.** Every refresh re-stamps the
    `vp_access_token` / `vp_role` cookies with a fresh 7-day `max-age`. Confirm
    the Next.js middleware route guard (which only checks cookie *presence*)
    stays consistent — no window where the cookie outlives a dead refresh token
    in a way that strands the user, and no window where it expires while the
    session is still valid.

### D. Tests

14. **Interceptor is not unit-tested.** Only the pure helpers in `authSession.js`
    have tests; the single-flight / retry / recursion logic in `client.ts` has
    none (consistent with the repo — `client.ts` had no test before). Decide
    whether this is an acceptable gap or whether an interceptor-level test
    should be required before merge.
15. **Backend coverage.** Confirm `test_auth_api.py` exercises the JSON-body
    refresh happy path and the non-refresh-token rejection (an access token
    presented to `/auth/refresh` must 401).

### E. Behavioral regression

16. Confirm the terminal-failure path (no refresh token, or refresh itself
    fails) still clears the session and redirects to `/login` — identical to
    pre-change behavior for that case.

## Verification

Environment caveat: a prod stack may hold host ports 8101/3101, so
`docker compose up`/`exec` for dev `api`/`web` can fail to bind. Verify with
`docker compose run --rm --no-deps <service> <cmd>` (does not publish ports;
prod untouched). If dev-DB tests fail with `column ... does not exist`, run
`docker compose run --rm --no-deps api alembic upgrade head` first.

- Backend: `docker compose run --rm --no-deps api pytest -q` — expect all green.
- Frontend tests: `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`.
- Frontend lint: `docker compose run --rm --no-deps web npm run lint`.
- Frontend build: `docker compose run --rm --no-deps web npm run build`.

## Pass bar

Approve only if: A1–A4 carry no unaccepted security gap (A3/A4 residual risks
may be accepted explicitly, in writing); B5–B11 are all correct; C12–C13 hold;
D15 passes and the D14 gap is consciously accepted; E16 confirmed; all four
verification commands green.
