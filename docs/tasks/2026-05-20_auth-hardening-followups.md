# 2026-05-20 — Auth hardening follow-ups

Backlog opened from the review of the session refresh-token flow
(`docs/tasks/2026-05-20_session-refresh-token-flow.md`,
review result `..._session-refresh-token-flow-review-result.md`). These items
were accepted as **non-blocking** for that change but are recorded here so they
are not lost. None of them block the refresh-token-flow merge.

## 1. Refresh tokens have no revocation / reuse detection (review item A3)

**Risk.** Access and refresh tokens are stateless JWTs. `/auth/refresh`
re-checks token type, user existence, and `user.is_active` before issuing a new
pair, so a disabled or deleted account cannot keep refreshing. But there is:

- no server-side refresh-token store / `jti` tracking,
- no rotation **reuse detection** (a refresh token that was already exchanged
  stays valid until its own `exp`),
- no revocation list.

A **stolen refresh token is usable for up to 7 days** unless the account is
disabled. Activating the refresh flow makes this the effective session model,
so the window matters more than it did under the old 30-minute access token.

**Acceptable for v0.1** (single-tenant, small user base) **only as tracked debt.**
Address before broader rollout / multi-user GA — see
`docs/multi_user_migration_plan.md`.

**Options when picked up:**
- Persist refresh tokens (or their `jti`) server-side; rotate on every refresh
  and **invalidate the whole token family on reuse** of an already-spent token.
- Add a revocation list / `token_version` column on `users`, bumped on password
  change and on explicit logout, checked in `decode_token`'s callers.
- Keep refresh-token TTL at 7 days but shorten it for elevated/admin roles.

## 2. Interceptor-level tests for `frontend/lib/api/client.ts` (review item 14)

The response interceptor's single-flight / retry / recursion behaviour is not
unit-tested — only the pure helpers in `authSession.js` are. The repo had no
`client.ts` test before this change. For auth code this gap should be closed:
add a test (with an axios mock adapter) covering

- a wave of concurrent 401s triggering exactly one `/auth/refresh`,
- the retried request succeeding with the new token,
- a second 401 on the retried request terminating (no loop),
- a failed refresh clearing the session.

## Resolved in the refresh-token-flow change itself (not deferred)

- **Review A4 — `Secure` cookie flag.** `persistAuthSession` now adds `Secure`
  when the page is served over HTTPS (`window.location.protocol === 'https:'`).
- **Review item 9 — non-refreshable URL matching.** `shouldAttemptRefresh` now
  strips the query string and matches the path exactly or as a trailing
  segment, instead of a loose substring `includes`.
- **Review item 11 — refresh-response shape guard.** `requestRefresh` verifies
  `access_token` / `refresh_token` are present before persisting.
