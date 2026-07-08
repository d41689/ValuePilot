# Rate Guard — labelled accepted keys (`RATE_GUARD_API_KEY_<LABEL>`)

**Date:** 2026-07-08
**Branch:** `claude/rate-guard-labelled-keys`
**Follows:** [`2026-07-08_rate-guard-auth-hardening.md`](./2026-07-08_rate-guard-auth-hardening.md)

## Goal

Replace the fixed two-slot key scheme (`RATE_GUARD_API_KEY` +
`RATE_GUARD_API_KEY_PREVIOUS`) with a **self-documenting, N-key** convention:
Rate Guard accepts `RATE_GUARD_API_KEY` plus **any** `RATE_GUARD_API_KEY_<LABEL>`
var. Motivated by the `_PREVIOUS` name being misleading for what is actually the
remote dev box's active key — now `RATE_GUARD_API_KEY_DEVELOPMENT`.

## Change

- `rate-guard/app/auth.py` — `configured_api_keys()` scans the environment for
  `RATE_GUARD_API_KEY` and any `RATE_GUARD_API_KEY_` prefix; a Bearer matching any
  non-empty value is authorized (constant-time, non-early-exit). `_PREVIOUS` still
  works (it matches the prefix); rotation semantics unchanged.
- Tests: labelled slots all accepted; the `_REQUIRE_AUTH` flag is not a key.
- Docs: README, `.env.prod.example`, `rate-guard-public-exposure.md` — the
  labelled convention; current assignment (internal = `RATE_GUARD_API_KEY`,
  remote dev = `RATE_GUARD_API_KEY_DEVELOPMENT`).
- Client side unchanged: each caller still sets one `RATE_GUARD_API_KEY`.

## Rollout (gap-proof)

Ship the code first, then rename the host var — at no point is the remote key
rejected:

1. Merge → auto-deploy (new code accepts the prefix; the running container's
   baked-in `_PREVIOUS=B` still matches during the CI+deploy window; the
   redeploy also copies the renamed canonical env — see step 2).
2. Before merge, rename host `~/.config/valuepilot/.env`:
   `RATE_GUARD_API_KEY_PREVIOUS` → `RATE_GUARD_API_KEY_DEVELOPMENT` (value B
   unchanged). The old running container keeps `_PREVIOUS=B` in its baked env
   until the deploy recreates it with the new code + `_DEVELOPMENT=B`.
3. Verify: internal key A → 200, remote key B (now `_DEVELOPMENT`) → 200,
   random → 401.

Note: this is a code change, so it goes through the full auto-deploy — a brief
prod `web`/`api` restart, not just rate-guard.

## Test plan

```
docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"
```
Full canonical gate via CI on the PR.

## Sign-off

- 2026-07-08: implemented; user chose the generic-prefix design. rate-guard suite
  35 passed. PR + deploy + host-var rename pending.
