# Rate Guard auth hardening (PR #103 review follow-up)

**Date:** 2026-07-08
**Branch:** `claude/rate-guard-auth-hardening`
**Follows:** [`2026-07-07_rate-guard-public-auth.md`](./2026-07-07_rate-guard-public-auth.md)
(PR #103, merged `a4a927a`) and its
[review results](./2026-07-07_rate-guard-public-auth-review-results.md).

## Goal

Close the P0/P1 findings from the PR #103 review, plus the cheap P2/process
items, in one bundled hotfix. User picked **Option B** for the secret-strength
lane (keep the app Bearer key; add a rotation window; defer WAF/alerting).

## Findings addressed

| # | Finding | Action here |
|---|---|---|
| 1 (P0) | Fail-open on missing/blank key | `RATE_GUARD_REQUIRE_AUTH=1` → `enforce_auth_config()` refuses to boot with no key; loud warning when auth is off |
| 2 (P1) | Non-ASCII `Authorization` byte → `TypeError` → 500 | `is_authorized` compares on **bytes** (latin-1) — clean 401, still constant-time |
| 3 (P1) | Rollback coupling re-opens open proxy | Rollback runbook in `rate-guard-public-exposure.md` (tear down tunnel FIRST); keep `127.0.0.1` bind |
| 4 (P1) | Static single key, no rotation/dual-key | Second accepted slot `RATE_GUARD_API_KEY_PREVIOUS`; rotation runbook. WAF/alerting + split values → backlog |
| 5 (P2) | Key sent over non-HTTPS/off-box URL | Client warns (once/URL) when a key is set and `RATE_GUARD_URL` is non-https to a non-internal host |
| 6 (P2) | CI only exercised auth-disabled path | New tests: with-key `/v1/fetch` pass-through, `EdgarClient` end-to-end header, non-ASCII, multi-key, fail-closed startup |
| 7 (P2) | `/healthz` leaks upstream names | `/healthz` now returns only `{"status":"ok"}` |
| 8 (P2) | Repo↔reality drift | New `docs/architecture/rate-guard-public-exposure.md` manifest |
| 10 (process) | Deferred items not in backlog | 3 `docs/BACKLOG.md` entries (dev-api 401, observability, split-keys) |

Deferred to backlog: #9 (observability / CF WAF), #4 residual (split dev/prod key
values, CF Access as a future option). NITs #11/#12/#13 addressed by docs.

## Acceptance criteria

- With a key set: unchanged behaviour (401 without / correct `Bearer` → through).
- With `RATE_GUARD_REQUIRE_AUTH=1` and no key: the container **refuses to boot**.
- A non-ASCII `Authorization` value → **401**, never 500.
- `RATE_GUARD_API_KEY_PREVIOUS` is accepted alongside the primary.
- `/healthz` returns `{"status":"ok"}` only.
- Every canonical CI command green; rate-guard suite green.

## Scope

**In:** `rate-guard/app/auth.py`, `rate-guard/app/main.py`,
`rate-guard/tests/test_auth.py`, `backend/app/rate_guard/client.py`,
`backend/tests/unit/test_rate_guard_client.py`,
`backend/tests/unit/test_edgar_client.py`, `.env.prod.example`,
`rate-guard/README.md`, `docs/architecture/rate-guard-public-exposure.md` (new),
`docs/BACKLOG.md`.

**Out (deferred):** Cloudflare WAF rate rule + 401 alerting; provisioning
distinct dev/prod/remote key values; any move to Cloudflare Access.

## Rollout (after merge → auto-deploy)

1. Add `RATE_GUARD_REQUIRE_AUTH=1` to host `~/.config/valuepilot/.env` **before**
   the deploy so the fail-closed guard is active on the exposed instance.
2. Merge → CI green → `deploy.yml` rebuilds Rate Guard (recreates: sources +
   compose changed) and the prod stack.
3. Re-verify: `/healthz` → `{"status":"ok"}`; `/v1/fetch` no-key → 401, with-key
   → 200 on `127.0.0.1:9099` and `https://rate-guard.richmom.vip`; and confirm the
   container boots (key present, so the fail-closed guard passes).

## Test plan (Docker only)

```
docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

## Sign-off trail

- 2026-07-08: opened after the PR #103 review; user chose Option B. Code + tests
  + docs implemented. rate-guard suite 34 passed; backend
  `test_rate_guard_client.py` + `test_edgar_client.py` 28 passed. Full-gate run
  pending before opening the PR.
