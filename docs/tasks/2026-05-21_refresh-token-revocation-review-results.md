# Review results — Refresh-token revocation & rotation reuse detection

**Branch:** `claude/refresh-token-revocation`  
**Reviewer:** Claude Sonnet 4.6 (agent review)  
**Date:** 2026-05-21  
**Prompt:** `docs/tasks/2026-05-21_refresh-token-revocation-review-prompts.md`

---

## Overall verdict: **APPROVE**

All mandatory gates (A1–A6, B7–B9) pass. Residual risks on A3 and A5 are
accepted in writing below. C/D/E/F findings are recorded; E14 and E15 pass.
The bar — "a stolen or replayed refresh token is now detectably dead, logout
revokes server-side, safe to auto-deploy, one-time forced re-login only" — is
met.

---

## A. Security / threat model

### A1. Reuse burns the family — **PASS**

Evidence: `backend/app/core/refresh_tokens.py:111–116`

When `rotate_refresh_token` detects `row.revoked_at is not None`, it calls
`revoke_family(db, row.family_id, reason="reuse_detected")`. That function
(`refresh_tokens.py:71–79`) issues:

```sql
UPDATE refresh_tokens
SET revoked_at = now(), revoked_reason = 'reuse_detected'
WHERE family_id = :fid AND revoked_at IS NULL
```

The `IS NULL` predicate ensures:

1. **The live successor is killed.** It is the one still-NULL row; the UPDATE
   reaches it. A stolen-then-rotated token cannot survive.
2. **Already-revoked rows are untouched.** Their original `revoked_reason`
   (`rotated`, `logout`, or a prior `reuse_detected`) is preserved. Audit
   accuracy is intact.

### A2. Concurrent-refresh race — **PASS**

Evidence: `refresh_tokens.py:105–107` (`with_for_update()`)

Two concurrent `/auth/refresh` calls carrying the *same* jti:

- **T1** acquires the row lock via `SELECT ... FOR UPDATE`, reads
  `revoked_at = NULL`, marks the row as `rotated`, inserts successor Y, then
  commits.
- **T2** blocks on the lock until T1 commits. It then reads `revoked_at !=
  NULL` (set by T1) and enters the reuse-detected branch: `revoke_family` burns
  Y (the now-live successor), raises `RefreshTokenError`, and the endpoint
  commits the revocation.

Result: only one successor is ever live after the race; the second caller is
rejected as reuse. Single-use is preserved.

**Deadlock analysis:** T1 holds a row lock on the spent token X, then performs
a bulk UPDATE on the other (still-NULL) rows in the family — none of which T1
has previously locked. T2 is blocked waiting for X's lock and holds no other
lock. There is no circular wait; deadlock is impossible.

### A3. Logout takes no access token — **PASS** (residual accepted)

Evidence: `auth.py:80–89`

`POST /auth/logout` is a plain `def logout(body: RefreshRequest, db:
SessionDep)` — no `CurrentUser` dependency, no `HTTPBearer`. This is
deliberate and documented in the endpoint docstring: an expired access token
must not block a sign-out.

**Residual (accepted):** Anyone in possession of the refresh token can revoke
the session. This is the correct design — the refresh token *is* the session
credential — and is the standard OAuth 2.0 revocation stance. No additional
guard is required at this stage.

**Minor advisory:** `revoke_refresh_token` calls `decode_token`, which raises
`JWTError` on an expired token (exp check). An expired refresh token presented
to `/auth/logout` is silently ignored, and the endpoint returns 204. This is
safe (the token is already invalid to `/auth/refresh`) but slightly differs
from the docstring's "revoke the presented token's whole rotation family"
contract. Acceptable for v0.1; no action required.

### A4. Unknown / missing `jti` — **PASS**

Evidence: `refresh_tokens.py:97–109`

Two rejection points:

1. `jti = payload.get("jti"); if not jti: raise RefreshTokenError(...)` — tokens
   minted before this change (no `jti` claim) are caught here.
2. `row = ... scalar_one_or_none(); if row is None: raise RefreshTokenError(...)` —
   a validly-signed token whose jti is absent from the store is caught here.

Both paths return 401 to the client. Every currently-live session with an
old-format refresh token is forced to re-login exactly once on deploy. That is
the only behavior change for existing users and it is documented in the task doc.

### A5. Access tokens stay stateless — **PASS** (residual accepted)

Evidence: `backend/app/api/deps.py:28–50`

`get_current_user` / `CurrentUser` validates the JWT signature and type claim
but performs **no store lookup**. Access tokens are not checked against the
`refresh_tokens` table.

**Residual (accepted):** After logout (or reuse detection), any already-issued
access token remains valid until its `exp` — at most 30 minutes. A stolen
access token used within that window is not blocked by this change. This is the
stated and accepted trade-off for stateless access tokens; the PR makes no claim
to close that window.

### A6. Token never in a URL — **PASS**

Evidence: `auth.py:80–81`; `schemas/users.py` (the `RefreshRequest` schema is
reused for both `/refresh` and `/logout`).

The refresh token travels in the JSON body for both endpoints. It never appears
as a query parameter or path segment.

---

## B. Correctness — transactions & lifecycle

### B7. The `/refresh` error path commits — **PASS**

Evidence: `auth.py:68–72`

```python
except RefreshTokenError as exc:
    db.commit()
    raise HTTPException(...)
```

For a **reuse replay**: `rotate_refresh_token` calls `revoke_family` (which
executes a bulk `UPDATE` in the session) then raises. The `except` block
commits, persisting the family revocation before the 401 is sent. There is no
path where the revocation is computed but never committed.

For an **ordinary invalid token** (bad signature, missing jti, unknown jti,
type mismatch): `rotate_refresh_token` raises before touching the DB.
`db.commit()` in the error handler is a no-op with no pending writes. No harm.

### B8. Who commits — **PASS**

All four endpoint paths traced:

| Path | Writes | Committed by |
|---|---|---|
| Login | `issue_refresh_token` adds 1 row | `db.commit()` at `auth.py:57` |
| Refresh success | `rotate_refresh_token` marks old row `revoked_at`, `issue_refresh_token` adds successor | `db.commit()` at `auth.py:73` |
| Refresh error (reuse) | `revoke_family` bulk UPDATE | `db.commit()` at `auth.py:71` (error handler) |
| Logout | `revoke_family` bulk UPDATE (via `revoke_refresh_token`) | `db.commit()` at `auth.py:89` |

`issue_refresh_token` and `revoke_family` both add to the session but never
call `commit()`. The endpoint is the sole transaction owner in every path.
No dangling writes.

### B9. Migration — **PASS**

Evidence: `alembic/versions/20260521120000-add_refresh_tokens_table.py`

- `revision = "20260521120000"`, `down_revision = "20260513140000"`. Chain is
  correct.
- `id` and `user_id` are `sa.Integer()`, matching `users.id` (also Integer).
  FK type is sound.
- `upgrade`: creates the table with all columns (including inline `UniqueConstraint`
  on `jti`), then adds the two standalone indexes (`user_id`, `family_id`).
- `downgrade`: drops those two indexes by name, then drops the table (which also
  drops the inline unique constraint). Symmetric.
- Migration applies cleanly; no column or type mismatch.

---

## C. The store model

### C10. No ORM relationship — **PASS**

Evidence: `auth_tokens.py:25–29`; `models/__init__.py:9`

`RefreshToken` declares `ForeignKey("users.id")` but no `relationship()`, and
`User` has no back-ref. SQLAlchemy allows this — a FK without a relationship is
valid DDL-level plumbing. Because `auth_tokens` is imported in
`models/__init__.py`, the mapper registry sees the model before any query
executes; no mapper resolution error occurs.

All user lookups use `db.get(User, row.user_id)` directly, which is adequate
and avoids any lazy-load surprises.

### C11. `revoked_reason` values — **PASS**

The field is `String(32)`. Three values are written, each by exactly one code
path:

| Value | Path | Location |
|---|---|---|
| `"rotated"` | Successful rotation | `refresh_tokens.py:124` |
| `"reuse_detected"` | Reuse replay detected | `refresh_tokens.py:115` (via `revoke_family`) |
| `"logout"` | Client-initiated logout | `refresh_tokens.py:148` (via `revoke_family`) |

No other value is written anywhere in the codebase. Longest value is 14 chars;
`String(32)` is ample.

---

## D. Frontend

### D12. Sign-out is best-effort — **PASS**

Evidence: `AppShell.tsx:41–61`

`handleSignOut` is declared `async`. The `apiClient.post('/auth/logout', ...)`
call is wrapped in `try { ... } catch { /* ignore */ }`. Any network error,
timeout, or server error is swallowed. `authSession.clearAuthSession` and
`router.replace('/login')` execute unconditionally after the try/catch.

Sign-out can never hang on a network error. The `async` function on `onClick` is
correct — React does not await the handler, but the handler completes the
sign-out (clear + redirect) without requiring the caller to wait.

### D13. No interceptor loop — **PASS**

Evidence: `AppShell.tsx:51`; `auth.py:80–89`

The `apiClient.post('/auth/logout', ...)` call goes through the request
interceptor, which attaches `Authorization: Bearer <access_token>`. The backend
`logout` endpoint has no `HTTPBearer` scheme and no `CurrentUser` dependency —
the header is ignored.

`logout` always returns 204: `revoke_refresh_token` catches all exceptions
internally and returns `None`; `db.commit()` does not raise in normal operation.
The endpoint cannot return 401. The response interceptor's 401-triggered refresh
logic therefore cannot fire, and there is no re-entry loop.

---

## E. Tests

### E14. New backend tests are genuine — **PASS** with advisory

Evidence: `tests/unit/test_auth_api.py:83–174`

All five new tests are substantive:

1. **`test_logout_revokes_the_refresh_token`** (line 83): Logs out, then
   confirms the same token is rejected by `/auth/refresh` with 401. ✓
2. **`test_refresh_rotation_invalidates_the_old_token`** (line 113): Builds
   A→B chain, confirms A is dead (reuse detected). ✓
3. **`test_reuse_detection_burns_the_whole_family`** (line 140): Builds A→B→C
   chain, replays A, then confirms **C** (the live successor) also returns 401.
   This is the critical test — it proves the *live* successor dies, not merely
   the replayed token. ✓
4. **`test_logout_is_idempotent`** (line 100): Two consecutive logouts both
   return 204. ✓
5. **`test_refresh_rejects_an_unknown_jti`** (line 164): Crafts a validly-signed
   token with a jti absent from the store; confirms 401. ✓

**Coverage gaps (advisory, not blocking):**

- **`FOR UPDATE` concurrency path**: The serialization behaviour under
  concurrent requests is not unit-tested. Testing this correctly requires
  multi-threaded or async setup against a real Postgres instance, beyond the
  current synchronous SQLite test harness. The logic is verifiably correct by
  code inspection (see A2). Acceptable to defer; should be captured as a
  backlog item if long-lived.
- **Inactive-user on refresh**: `rotate_refresh_token:118–120` rejects a
  refresh attempt when the user is inactive. No test covers this branch. The
  logic is a single guard and the `RefreshTokenError` handling path is already
  covered by other tests, so the risk is low — but an explicit test before
  broader rollout is recommended.

### E15. No regression — **PASS**

Evidence: `test_auth_api.py:1–53`

- **`test_register_login_me_refresh_flow`**: Exercises the full happy path
  (register → login → `/me` → `/refresh`). The change adds jti-tagged refresh
  tokens backed by a store row; the flow is otherwise identical. Contract
  intact. ✓
- **`test_refresh_rejects_a_non_refresh_token`**: Presents an access token to
  `/auth/refresh` and expects 401 with `"Token is not a refresh token"`.
  `rotate_refresh_token:94–95` checks `payload.get("type") != "refresh"` before
  the jti lookup; this path is unchanged. Detail string preserved. ✓

---

## F. Scope / deferred work

### F16. Deferral hygiene — **PASS**

Evidence: `docs/BACKLOG.md:41–50`; `docs/tasks/2026-05-21_refresh-token-revocation.md:48–68`

1. **Resolved entry removed.** The original BACKLOG entry "Refresh tokens have
   no revocation / reuse detection" is absent from `BACKLOG.md`. ✓

2. **New low entry for purge job added.** BACKLOG.md lines 41–50 contain a new
   `low` entry "Expired `refresh_tokens` rows are never purged" with:
   - Concrete purge SQL: `DELETE FROM refresh_tokens WHERE expires_at < now()`
   - Index suggestion: `expires_at` column
   - Rationale and deferral justification. ✓

3. **`users.token_version` correctly out of scope.** Task doc line 67–68:
   "no password-change endpoint exists yet; revisit when one is added." ✓

4. **Cross-tab concurrent-refresh trade-off documented.** Task doc lines 50–53:
   strict reuse detection means a near-simultaneous cross-tab refresh burns the
   family; the web client single-flights `/auth/refresh` so this only bites
   genuine cross-tab races; accepted as v0.1 stance. ✓

---

## Summary of advisory items

| # | Item | Severity | Action |
|---|---|---|---|
| A3 | An expired refresh token presented at logout is silently ignored (decode_token raises on exp) | low | No action; best-effort logout is by design |
| A5 | Revoked sessions leave ≤30-min access-token window | accepted residual | Documented; no action at this tier |
| E14 | `FOR UPDATE` concurrency path not unit-tested | low | Defer; capture in backlog if extended |
| E14 | Inactive-user-on-refresh branch not unit-tested | low | Add test before broader rollout |

No advisory item is a blocker. The mandatory gates are all green.
