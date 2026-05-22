# Review prompt — Refresh-token revocation & rotation reuse detection

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-21_refresh-token-revocation.md` and the diff on branch.

---

## Reviewer brief

You are reviewing an **authentication change** to ValuePilot. This is auth code —
review it with security-grade scrutiny, not a glance. It resolves the
`docs/BACKLOG.md` item *"Refresh tokens have no revocation / reuse detection"*
(medium, opened from PR #64).

### What changed and why

- Before: access + refresh tokens were stateless JWTs. `/auth/refresh` rotated
  the pair, but the **old refresh token stayed valid until its 7-day `exp`** —
  no logout, no revocation, no detection of a replayed token. A stolen refresh
  token was good for up to a week.
- After: every refresh token is mirrored by a row in a new `refresh_tokens`
  table, keyed by a JWT `jti` claim. Rows sharing a `family_id` form one
  rotation lineage (login starts a family; each refresh appends a successor).
  - **Logout** (`POST /auth/logout`, new) revokes the presented token's whole
    family immediately.
  - **Reuse detection** — presenting an already-spent token is a replay; the
    whole family, the live successor included, is burned.
- Access tokens are unchanged: stateless 30-minute JWTs. The store governs
  refresh tokens only.

### Files in scope

- `backend/app/models/auth_tokens.py` — new `RefreshToken` model.
- `backend/app/models/__init__.py` — registers the model.
- `backend/alembic/versions/20260521120000-add_refresh_tokens_table.py` — new table.
- `backend/app/core/security.py` — `create_refresh_token` now takes a `jti`.
- `backend/app/core/refresh_tokens.py` — new: issue / rotate / revoke / reuse logic.
- `backend/app/api/v1/endpoints/auth.py` — login/refresh rewired; new `/logout`.
- `backend/tests/unit/test_auth_api.py` — revocation + reuse-detection tests.
- `frontend/components/layout/AppShell.tsx` — "Sign out" calls `/auth/logout`.
- `docs/BACKLOG.md`, `docs/tasks/2026-05-21_refresh-token-revocation.md`.

### Baseline

`git diff main...HEAD` on branch `claude/refresh-token-revocation`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + file:line evidence

### A. Security / threat model — MANDATORY

1. **Reuse burns the family.** `rotate_refresh_token`, on a presented token whose
   row is already `revoked_at != NULL`, calls `revoke_family(..., "reuse_detected")`.
   `revoke_family` updates only rows with `revoked_at IS NULL`. Confirm this
   genuinely kills the **currently-live successor** (the one still-NULL row) so a
   stolen-then-rotated token cannot survive, and that already-revoked rows keep
   their original `revoked_reason` (audit accuracy).
2. **Concurrent-refresh race.** The `jti` lookup in `rotate_refresh_token` uses
   `SELECT ... FOR UPDATE`. Trace two concurrent `/auth/refresh` calls carrying
   the *same* token: confirm the row lock serializes them, so the second
   transaction sees the first's `revoked_at` and is caught as reuse — rather than
   both reading `NULL` and both minting a successor (which would defeat
   single-use). Confirm the row lock plus `revoke_family`'s family-wide `UPDATE`
   cannot deadlock (the locked row is the spent token; `revoke_family` only
   touches the *other*, still-NULL rows).
3. **Logout takes no access token.** `POST /auth/logout` authenticates with the
   refresh token in the body alone — no `CurrentUser` dependency. Confirm this is
   deliberate (an expired access token must not block sign-out) and state the
   residual: anyone holding the refresh token can revoke the session. Is that
   acceptable, or should logout also require a valid access token?
4. **Unknown / missing `jti`.** A validly-signed refresh token whose `jti` is
   absent, or not present in `refresh_tokens`, is rejected 401. Confirm this
   covers tokens minted **before this change shipped** (no `jti` claim) — i.e.
   every currently-live session is forced to re-login exactly once on deploy —
   and that this one-time forced re-login is the only behavior change for
   existing users.
5. **Access tokens stay stateless.** Confirm `deps.get_current_user` is
   unchanged and access tokens are **not** checked against the store. State the
   consequence explicitly: revoking/logging-out does not invalidate an
   already-issued access token — the stolen-credential window after a logout is
   one access-token lifetime (≤30 min), not zero. Is that the intended bar?
6. **Token never in a URL.** `/auth/logout` reuses `RefreshRequest` — the refresh
   token travels only in the JSON body. Confirm.

### B. Correctness — transactions & lifecycle — MANDATORY

7. **The `/refresh` error path commits.** On `RefreshTokenError`, the endpoint
   does `db.commit()` *before* raising 401. Confirm this is required — a reuse
   replay performs the family revocation inside `rotate_refresh_token` and it
   must persist — and that it is a harmless no-op for an ordinary invalid token
   (no pending writes). Confirm there is **no** path where a reuse revocation is
   computed but never committed.
8. **Who commits.** `issue_refresh_token` and `revoke_family` add to the session
   but never commit; the endpoint owns the transaction. Walk all four endpoint
   paths — login, refresh success, refresh error, logout — and confirm each
   commits exactly the writes it makes and none leaves a dangling write.
9. **Migration.** `revision = 20260521120000`, `down_revision = 20260513140000`
   (the current head). `refresh_tokens.id` and `user_id` are `Integer`, matching
   `users.id`. Confirm the migration applies cleanly, the FK type matches, and
   `upgrade`/`downgrade` are symmetric (two indexes + table).

### C. The store model

10. **No ORM relationship.** `RefreshToken` has a FK to `users.id` but no
    `relationship()`, and `User` gets no back-ref. Confirm that raises no mapper
    resolution error (the model is imported in `models/__init__.py`) and is a
    deliberate, adequate choice.
11. **`revoked_reason` values.** It is a free `String(32)`. Confirm the only
    values written are `rotated`, `logout`, `reuse_detected`, and that each is
    actually produced by exactly the path its name implies.

### D. Frontend

12. **Sign-out is best-effort.** `handleSignOut` is now `async`: it POSTs
    `/auth/logout`, swallows any error, and clears the local session +
    redirects regardless. Confirm sign-out can never hang or fail on a network
    error, and that an `async` handler on `onClick` is correct.
13. **No interceptor loop.** The logout call goes through `apiClient`, whose
    request interceptor attaches an `Authorization` header and whose response
    interceptor refreshes on 401. Confirm the backend ignores that header for
    logout, logout cannot return 401, and the call therefore cannot re-enter the
    refresh interceptor.

### E. Tests

14. **New backend tests are genuine.** Five were added — logout revokes the
    token, rotation invalidates the old token, reuse burns the whole family,
    logout is idempotent, an unknown `jti` is rejected. Confirm
    `test_reuse_detection_burns_the_whole_family` proves the *live* successor
    (token C) dies, not just the replayed one. Note coverage gaps — e.g. the
    `FOR UPDATE` concurrency path and the inactive-user-on-refresh branch are
    not unit-tested; decide whether either must be covered before merge.
15. **No regression.** Confirm the pre-existing `test_register_login_me_refresh_flow`
    and `test_refresh_rejects_a_non_refresh_token` still pass and their contract
    is intact (an access token presented to `/auth/refresh` still 401s with
    detail `"Token is not a refresh token"`).

### F. Scope / deferred work

16. Confirm the deferral hygiene: the resolved BACKLOG entry is removed; a new
    **low** entry covers the unbounded growth of `refresh_tokens` (no purge job
    — one row per refresh) with a concrete purge SQL + index suggestion; and
    `users.token_version` for password-change-wide revocation is correctly out
    of scope (no password-change endpoint exists yet). The cross-tab
    concurrent-refresh trade-off (a self-race burns the family) is documented in
    the task doc — confirm it is an acceptable v0.1 stance.

## Verification

Environment caveat: a prod stack may hold host ports 8101/3101, so a dev
`docker compose up` can fail to bind. If so, run the commands below via
`docker compose run --rm --no-deps <service> <cmd>` (publishes no ports; prod
untouched). If dev-DB tests fail with `column/table ... does not exist`, run
`alembic upgrade head` first.

Canonical CI commands (run verbatim, full suites):

- `docker compose up -d --build`
- `docker compose exec -T api alembic upgrade head`
- `docker compose exec -T api pytest -q` — expect all green (~901).
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
- `docker compose exec -T web npm run lint`
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

## Pass bar

Approve only if: **A1–A6** carry no unaccepted security gap (A3/A5 residual
risks may be accepted explicitly, in writing); **B7–B9** are all correct — no
uncommitted reuse revocation, no dangling write, migration sound; **C/D/E/F**
findings are recorded and E14/E15 pass. The bar is: "a stolen or replayed
refresh token is now detectably dead, logout revokes server-side, and the change
is safe to auto-deploy to prod — accepting only a one-time forced re-login for
existing sessions and a ≤30-min post-logout access-token window."
