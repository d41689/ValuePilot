# Review result — Refresh-token revocation & rotation reuse detection

Date: 2026-05-21
Branch reviewed: `claude/refresh-token-revocation`
Baseline: `git diff main...HEAD`
Prompt: `docs/tasks/2026-05-21_refresh-token-revocation-review-prompts.md`

## Overall verdict

PASS. I did not find a blocker against auto-deploy. The implementation gives
refresh tokens a server-side lifecycle keyed by `jti`, rotation spends the
presented token, reuse burns the whole family including the currently-live
successor, logout revokes server-side, and the endpoint transaction boundaries
persist the security-relevant writes.

Accepted residual risks:
- `POST /auth/logout` authenticates with the refresh token alone. Anyone holding
  that token can revoke the session, but cannot gain privilege by doing so; this
  is acceptable and avoids blocking sign-out when the access token is expired.
- Access tokens remain stateless. Logout/revocation does not invalidate an
  already-issued access token; the post-logout/stolen-access-token window is one
  access-token lifetime, currently 30 minutes by design.

## Prompt checklist

### A. Security / threat model

1. PASS. Replaying an already-revoked refresh token calls `revoke_family()` with
   `reuse_detected`; `revoke_family()` updates only rows whose `revoked_at` is
   still NULL, so the live successor is burned while already-spent rows keep
   their original `revoked_reason` such as `rotated`. Evidence:
   `backend/app/core/refresh_tokens.py:65-79`,
   `backend/app/core/refresh_tokens.py:111-116`,
   `backend/tests/unit/test_auth_api.py:140-162`.
2. PASS. `rotate_refresh_token()` locks the presented token row with
   `SELECT ... FOR UPDATE`. Two concurrent refreshes using the same token
   serialize on that row; after the first commits `revoked_at='rotated'`, the
   second sees `revoked_at` and runs reuse detection instead of minting a second
   successor. The family-wide update only touches still-live rows, not the
   locked spent row, so I do not see a deadlock cycle in the intended path.
   Evidence: `backend/app/core/refresh_tokens.py:102-116`.
3. PASS, accepted residual. `/auth/logout` has no `CurrentUser` dependency and
   takes only `RefreshRequest`; this is deliberate so an expired access token
   cannot block sign-out. Residual: a party holding the refresh token can revoke
   the family. That is acceptable for v0.1 because revocation is destructive
   only. Evidence: `backend/app/api/v1/endpoints/auth.py:80-89`,
   `docs/tasks/2026-05-21_refresh-token-revocation.md:42-44`.
4. PASS. Missing `jti` and unknown `jti` are rejected with 401. This covers
   pre-deploy refresh tokens minted before `jti` existed, forcing existing
   sessions to re-login once. I found no other intended behavior change for
   existing users. Evidence: `backend/app/core/refresh_tokens.py:97-109`,
   `backend/app/api/v1/endpoints/auth.py:64-77`,
   `backend/tests/unit/test_auth_api.py:164-173`.
5. PASS, accepted residual. `get_current_user()` is unchanged and does not look
   up access tokens in the refresh-token store. Revoking/logout therefore leaves
   already-issued access tokens usable until expiry, which is the intended
   stateless-access-token bar. Evidence: `backend/app/api/deps.py:28-50`,
   `backend/app/core/security.py:29-32`,
   `docs/tasks/2026-05-21_refresh-token-revocation.md:46-47`.
6. PASS. `/auth/logout` reuses `RefreshRequest`; the token is supplied in JSON
   body as `refresh_token`, not in the URL. Evidence:
   `backend/app/schemas/users.py:25-28`,
   `backend/app/api/v1/endpoints/auth.py:80-89`,
   `frontend/components/layout/AppShell.tsx:49-52`.

### B. Correctness — transactions & lifecycle

7. PASS. The `/refresh` `RefreshTokenError` path commits before raising 401.
   That is required because a reuse replay mutates the family inside
   `rotate_refresh_token()`; ordinary invalid tokens have no pending writes, so
   the commit is harmless. I found no reuse path where revocation is computed
   and then abandoned. Evidence: `backend/app/core/refresh_tokens.py:111-116`,
   `backend/app/api/v1/endpoints/auth.py:66-73`.
8. PASS. Endpoint-owned transactions are consistent: login calls
   `issue_refresh_token()` then commits; refresh success rotates + inserts a
   successor then commits; refresh error commits reuse revocation or no-op
   invalid attempts; logout calls `revoke_refresh_token()` then commits.
   Helpers add/update rows but do not commit. Evidence:
   `backend/app/core/refresh_tokens.py:42-63`,
   `backend/app/core/refresh_tokens.py:65-79`,
   `backend/app/api/v1/endpoints/auth.py:47-61`,
   `backend/app/api/v1/endpoints/auth.py:64-89`.
9. PASS. Migration revision is `20260521120000` and down-revision is current
   head `20260513140000`. `refresh_tokens.id` and `user_id` are `Integer`,
   matching `users.id`; upgrade creates table plus two indexes, and downgrade
   drops those indexes and the table. Evidence:
   `backend/alembic/versions/20260521120000-add_refresh_tokens_table.py:20-57`,
   `backend/app/models/users.py:16`.

### C. The store model

10. PASS. `RefreshToken` has a FK to `users.id` and no ORM relationship/backref.
    That is adequate because the code queries tokens directly and only needs
    `user_id`; the model is imported in `models/__init__.py`, so mapper
    registration is covered. Evidence:
    `backend/app/models/auth_tokens.py:19-42`,
    `backend/app/models/__init__.py:8-15`.
11. PASS. `revoked_reason` is free text but writes are centralized and limited
    to `rotated`, `logout`, and `reuse_detected`, each from the expected path.
    Evidence: `backend/app/core/refresh_tokens.py:115`,
    `backend/app/core/refresh_tokens.py:123-125`,
    `backend/app/core/refresh_tokens.py:148`.

### D. Frontend

12. PASS. `handleSignOut()` is async, awaits a best-effort `/auth/logout`, and
    swallows failures before always clearing local session state and navigating
    to `/login`. An async click handler is acceptable here; failed revocation
    cannot prevent local sign-out. Evidence:
    `frontend/components/layout/AppShell.tsx:41-61`,
    `frontend/components/layout/AppShell.tsx:107-110`.
13. PASS. The logout call uses `apiClient`, so it may include an Authorization
    header, but the backend ignores it because `/auth/logout` has no auth
    dependency. With a syntactically valid body, invalid/expired/unknown refresh
    tokens are swallowed and the endpoint returns 204, so it does not re-enter
    the 401 refresh interceptor. Evidence:
    `frontend/lib/api/client.ts:18-31`,
    `frontend/lib/api/client.ts:88-110`,
    `backend/app/core/refresh_tokens.py:129-148`,
    `backend/app/api/v1/endpoints/auth.py:80-89`.

### E. Tests

14. PASS with coverage notes. The new tests cover logout revocation, idempotent
    logout, rotation invalidating the old token, reuse burning the whole family,
    and unknown `jti` rejection. `test_reuse_detection_burns_the_whole_family`
    proves the live successor dies by building A -> B -> C, replaying A, then
    asserting C can no longer refresh. Gaps: the `FOR UPDATE` concurrent refresh
    race and inactive-user-on-refresh branch are not unit-tested. I do not think
    either gap blocks merge: the concurrency guarantee is directly expressed in
    the SQLAlchemy query and hard to test reliably in the current unit harness;
    inactive user returns 401 and does not add a new capability. Evidence:
    `backend/tests/unit/test_auth_api.py:83-173`,
    `backend/app/core/refresh_tokens.py:102-120`.
15. PASS. Existing auth flow and non-refresh-token rejection contracts remain
    intact. An access token sent to `/auth/refresh` still returns 401 with
    `"Token is not a refresh token"`. Evidence:
    `backend/tests/unit/test_auth_api.py:1-52`,
    `backend/app/core/refresh_tokens.py:94-95`.

### F. Scope / deferred work

16. PASS. The resolved backlog item is replaced with a low-severity purge
    follow-up including concrete purge SQL and an `expires_at` index suggestion.
    `users.token_version` for password-change-wide revocation remains out of
    scope because there is no password-change endpoint yet. The cross-tab
    concurrent-refresh self-race trade-off is documented and accepted for v0.1.
    Evidence: `docs/BACKLOG.md:41-50`,
    `docs/tasks/2026-05-21_refresh-token-revocation.md:51-53`,
    `docs/tasks/2026-05-21_refresh-token-revocation.md:65-68`.

## Verification performed

- Read the review prompt and task log.
- Inspected `git diff main...HEAD` scope.
- Reviewed the refresh-token model, migration, security helpers, auth endpoints,
  auth dependency, frontend sign-out wiring, API interceptor behavior, tests,
  backlog, and task-doc deferrals.
- Grepped for refresh-token creation, reason values, backlog entries, and
  migration head context.

I did not run the Docker canonical CI commands in this review pass.
