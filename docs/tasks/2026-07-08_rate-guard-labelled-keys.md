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

Deploys recreate rate-guard on **every** main merge (observed in-session), so an
unrelated merge landing between the env rename and this PR could deploy **old
code + the new env name** and reject key B (self-review finding #2). To be
gap-proof regardless of merge ordering, keep **both** key names = B during the
transition:

1. On host `~/.config/valuepilot/.env`, **add** `RATE_GUARD_API_KEY_DEVELOPMENT`
   = B while **keeping** `RATE_GUARD_API_KEY_PREVIOUS` = B. Old code accepts B via
   `_PREVIOUS`, new code via either — no ordering can reject it.
2. Merge → auto-deploy (new code live; both names accepted).
3. Once the new code is confirmed live, **remove** `RATE_GUARD_API_KEY_PREVIOUS`
   from the host env and recreate rate-guard only (no prod blip).
4. Verify at each step: internal key A → 200, remote key B → 200, random → 401.

Note: the merge (step 2) is a code change → full auto-deploy — a brief prod
`web`/`api` restart, not just rate-guard.

## Test plan

```
docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"
```
Full canonical gate via CI on the PR.

## Sign-off

- 2026-07-08: implemented; user chose the generic-prefix design. rate-guard suite
  35 passed. PR #106 opened.
- 2026-07-08: self-review (P2s, no P0/P1). Fixed on-branch: (#1) the bare prefix
  `RATE_GUARD_API_KEY_` (empty label) was accepted as a key — now requires a
  non-empty label, with a `test_near_miss_var_names_are_not_keys` regression
  (covers the empty-label + plural `RATE_GUARD_API_KEYS` near-misses). (#2)
  rollout rewritten to keep both key names during the transition (above). No
  prefix collision exists in the repo today (every other `RATE_GUARD_*` env var
  uses a distinct prefix). PR + deploy + host-var rename pending.
