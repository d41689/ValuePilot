# Rate Guard — Bearer-key auth for public exposure

**Date:** 2026-07-07
**Branch:** `claude/rate-guard-public-auth`
**Owner:** Hua Wang (SRE) + Claude

## Goal

Expose Rate Guard's `POST /v1/fetch` to **one remote development machine** the
user owns, over the public domain, without turning it into an unauthenticated
open egress proxy to SEC / OpenFIGI / Dataroma.

Chosen mechanism (user picked **Option A**): an **application-level shared
Bearer key**, same mental model as an OpenAI API key — one secret, sent as
`Authorization: Bearer <key>`, verified inside Rate Guard.

The public URL will be a **dedicated subdomain** fronted by the existing
Cloudflare Tunnel:

```
https://rate-guard.richmom.vip/v1/fetch   →  cloudflared  →  http://localhost:9099  →  rate-guard:9000
```

(Subdomain, not the `invest.richmom.vip/rate-guard/...` path the user first
asked for, because cloudflared does **not** strip a path prefix — a path form
would deliver `/rate-guard/v1/fetch` to the app and 404. A subdomain maps
`/v1/fetch` straight through with no rewrite hop.)

## Acceptance criteria

- When `RATE_GUARD_API_KEY` is **set**:
  - `POST /v1/fetch` and `GET /v1/metrics` with no / wrong `Authorization`
    header → `401`, and **no upstream fetch happens**.
  - The same requests with `Authorization: Bearer <key>` behave exactly as
    before.
  - `GET /healthz` stays open (deploy + Docker healthcheck depend on it).
- When `RATE_GUARD_API_KEY` is **unset**: behaviour is unchanged (auth
  disabled) — so CI, existing internal callers, and the current tests keep
  passing without a key.
- The backend `RateGuardClient` attaches `Authorization: Bearer <key>` to every
  `/v1/fetch` and `/v1/metrics` request when `RATE_GUARD_API_KEY` is configured;
  all upstream clients (`EdgarClient`, `OpenFigiClient`, `DataromaClient`) inherit
  it for free.
- The Rate Guard host port (`9099`) binds to `127.0.0.1` only, so the key cannot
  be bypassed by hitting `http://<host-public-ip>:9099/v1/fetch` directly.
  cloudflared (on the host) still reaches it via `localhost:9099`.
- Every canonical CI command green; Rate Guard suite green.

## Scope

**In**
- `rate-guard/app/auth.py` (new) — pure `configured_api_key()` / `is_authorized()`.
- `rate-guard/app/main.py` — one HTTP middleware enforcing the key, `/healthz` exempt.
- `rate-guard/tests/test_auth.py` (new).
- `backend/app/core/config.py` — add `RATE_GUARD_API_KEY`.
- `backend/app/rate_guard/client.py` — send the Bearer header when configured.
- `backend/tests/unit/test_rate_guard_client.py` — header-sent / header-absent tests.
- `docker-compose.rateguard.yml` — bind `9099` to `127.0.0.1`.
- `.env.prod.example`, `rate-guard/README.md` — document `RATE_GUARD_API_KEY`.

**Out (host, done later with explicit go-ahead)**
- `~/.cloudflared/config.yml` — add the `rate-guard.richmom.vip` ingress rule +
  DNS route. Out-of-repo, outward-facing; the user confirms before I touch it.
  Back up the current tunnel config first.
- Rotating / distributing the key to the remote dev machine.

## Design notes

- **Opt-in, not mandatory.** Auth is enforced only when `RATE_GUARD_API_KEY` is
  non-empty. This keeps backward-compat: a shared `.env` with no key = today's
  behaviour. Setting the key in the shared `~/.config/valuepilot/.env` turns it
  on for the rate-guard container *and* both api containers at once (all three
  `env_file: .env`).
- **Constant-time compare** via `secrets.compare_digest` — no timing oracle on
  the key.
- **`/v1/metrics` is protected too** — it leaks fetch volumes; the internal
  admin dashboard calls it through `RateGuardClient.metrics()`, which now also
  carries the key.
- Auth logic lives in a pure module so it unit-tests without importing
  `app.main` (which needs `SEC_CONTACT_EMAIL` + a writable cache dir at import).

## Test plan (Docker only)

- Rate Guard suite (README-documented containerized run):
  ```
  docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
    sh -c "pip install -q -r requirements-dev.txt && pytest -q"
  ```
- Backend: `docker compose exec -T api pytest -q`
- Full canonical CI gate (verbatim) before calling done:
  - `docker compose up -d --build`
  - `docker compose exec -T api alembic upgrade head`
  - `docker compose exec -T api pytest -q`
  - `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
  - `docker compose exec -T web npm run lint`
  - `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
  - `cd rate-guard && pip install -r requirements-dev.txt && pytest -q` (CI step)

## Sign-off trail

- 2026-07-07: task opened; user chose Option A (app-level Bearer key).
- 2026-07-07: implementation complete. Verification:
  - **Rate Guard suite (fresh container):** 28 passed (10 new auth tests) —
    `docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim ...`.
  - **Backend `test_rate_guard_client.py`:** 19 passed (3 new header tests).
  - **Frontend:** `node --test lib/*.test.js` → 175 passed; `npm run lint` clean;
    production build succeeded (dev `web` restarted afterward to restore the
    live dev site).
  - **Full backend `pytest -q`:** 185 failures + 11 errors — **pre-existing and
    environmental, NOT from this change.** Proven by stashing this branch's
    changes and re-running representative failures: they fail identically on the
    base commit; `test_rate_guard_client.py` passes on base too. Root cause is a
    non-hermetic suite run against the **live dev DB (which holds real 13F
    data)** — teardown hits `DELETE FROM filings_13f` → FK `IntegrityError`,
    cascading into the 13F scheduler/quarter tests, plus date-sensitive quarter
    logic (today = 2026-07-07). CI does not see this: it runs on a fresh volume
    (`docker compose down -v`). The authoritative clean-DB backend gate is CI at
    PR time, or a local run on a throwaway DB (would wipe dev data — not run
    without the user's OK).
- Pending (out of repo, needs user): add the `rate-guard.richmom.vip` ingress to
  `~/.cloudflared/config.yml` + DNS route (back up first); generate + distribute
  the key.
