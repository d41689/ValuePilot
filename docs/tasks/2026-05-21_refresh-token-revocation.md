# 2026-05-21 — Refresh-token revocation & rotation reuse detection

Resolves the `docs/BACKLOG.md` entry **"Refresh tokens have no revocation /
reuse detection"** (found 2026-05-20, PR #64, severity medium). Full prior
analysis: `docs/tasks/2026-05-20_auth-hardening-followups.md` item 1.

## Goal

Refresh tokens are stateless JWTs today: rotation issues a new pair but the old
token stays valid until its 7-day `exp`, there is no logout, and there is no way
to revoke a stolen token. Give refresh tokens a server-side lifecycle so they
can be revoked and so a replayed (already-spent) token is detected.

## Acceptance criteria

- A refresh token can be **revoked** — an explicit logout invalidates it
  immediately, before its `exp`.
- **Rotation reuse detection** — once a refresh token is exchanged, presenting
  it again is treated as a replay: the whole rotation *family* (the live
  successor token included) is burned, so a stolen-then-rotated token cannot be
  used and the legitimate holder is forced to re-authenticate.
- `/auth/refresh` continues to work for the normal one-step rotation.
- A new `POST /auth/logout` endpoint; the web app's "Sign out" calls it.
- Canonical CI commands green; no critical invariant violated.

## Design

Chosen approach — option 1 from the follow-ups doc: persist refresh tokens
server-side, keyed by a `jti` claim, grouped into a rotation **family**.

- **`refresh_tokens` table** — one row per issued refresh token: `jti` (unique),
  `user_id`, `family_id`, `issued_at`, `expires_at`, `revoked_at`,
  `revoked_reason` (`rotated` | `logout` | `reuse_detected`).
- **Login** starts a new family (fresh `family_id`) and inserts row 1.
- **Refresh** looks the presented `jti` up (`SELECT ... FOR UPDATE`, so two
  concurrent refreshes of the same token serialize):
  - unknown / missing `jti` → 401 (also covers pre-migration tokens — a
    one-time forced re-login on deploy);
  - row already revoked → **reuse**: revoke the whole family, 401;
  - otherwise mark the row `revoked_at` / `rotated` and mint a successor in the
    same family.
- **Logout** revokes the presented token's whole family; idempotent; takes only
  the refresh token (no access token required — the refresh token is the proof,
  and an expired access token must not block logout).
- Access tokens stay stateless 30-min JWTs — revoking refresh tokens caps the
  stolen-credential window at one access-token lifetime.

### Known trade-off

Strict reuse detection means two near-simultaneous refreshes with the same token
(e.g. a second browser tab) burn the family and log the user out. The web client
already single-flights `/auth/refresh` (`frontend/lib/api/client.ts`), so this
only bites cross-tab races — acceptable for v0.1, and the secure default.

## Scope

**In:**
- `refresh_tokens` table + Alembic migration.
- `jti` claim on refresh tokens; server-side store / rotation / reuse-detection
  helpers (`app/core/refresh_tokens.py`).
- `/auth/refresh` rewired through the store; new `POST /auth/logout`.
- Web "Sign out" calls `/auth/logout` (best-effort).

**Out:**
- Expired-row purge job (the table grows ~1 row per refresh) — deferred to
  `docs/BACKLOG.md`.
- `users.token_version` for password-change-wide revocation — no password-change
  endpoint exists yet; revisit when one is added.
- Interceptor-level tests for `client.ts` — separate existing backlog item.
- Per-device session listing / shorter admin TTLs.

## Files to change

- `backend/app/models/auth_tokens.py` — new `RefreshToken` model.
- `backend/app/models/__init__.py` — register the model.
- `backend/alembic/versions/20260521120000-add_refresh_tokens_table.py` — new.
- `backend/app/core/security.py` — `create_refresh_token` takes a `jti`.
- `backend/app/core/refresh_tokens.py` — new: issue / rotate / revoke helpers.
- `backend/app/api/v1/endpoints/auth.py` — login/refresh rewired; `/logout`.
- `backend/tests/unit/test_auth_api.py` — revocation + reuse-detection tests.
- `frontend/components/layout/AppShell.tsx` — `handleSignOut` calls `/auth/logout`.

## Test plan (Docker)

```
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

New backend tests: logout revokes the token; rotation invalidates the old
token; reuse of a spent token burns the whole family; logout is idempotent;
an unknown `jti` is rejected.

## Sign-off trail

- 2026-05-21 — task opened; design = follow-ups doc option 1.
- 2026-05-21 — implemented test-first. Gotcha: a reuse replay burns the whole
  family, so a test exercising the live successor must do so *before* the
  replay, not after. All six canonical CI commands green: `up -d --build`,
  `alembic upgrade head`, `pytest -q` (901 passed), `node --test lib/*.test.js`
  (153 passed), `npm run lint` (clean), production build OK.
- 2026-05-21 — self-review before the review prompt: added `SELECT ... FOR
  UPDATE` on the `jti` lookup in `rotate_refresh_token`. Without it two
  concurrent refreshes of the same token both read `revoked_at IS NULL` and both
  mint a successor, defeating single-use; the row lock serializes them so the
  second is caught as reuse. Re-ran the full suite — still green.
- 2026-05-21 — two independent reviews returned PASS / APPROVE, no blockers
  (`..._review-result.md`, `..._review-results.md`). Acted on the one cheap
  advisory: added `test_refresh_rejects_a_disabled_account` for the
  inactive-user-on-refresh branch. The FOR UPDATE concurrency-test gap needs
  integration infra — deferred to `docs/BACKLOG.md` (low). Residuals A3/A5
  accepted in writing in both reviews.
