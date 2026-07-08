# Rate Guard — public exposure (rate-guard.richmom.vip)

**Status: LIVE.** Rate Guard, normally an internal-only egress chokepoint, is
also reachable on the public internet at `https://rate-guard.richmom.vip` so a
remote dev machine can use the shared SEC/OpenFIGI/Dataroma egress. This file is
the version-controlled record of that exposure — the actual wiring lives on the
host (Cloudflare Tunnel + DNS + a host secret) and would otherwise be invisible
in the repo.

Background: [`rate-guard/README.md`](../../rate-guard/README.md) ·
first exposure [`docs/tasks/2026-07-07_rate-guard-public-auth.md`](../tasks/2026-07-07_rate-guard-public-auth.md) ·
hardening [`docs/tasks/2026-07-08_rate-guard-auth-hardening.md`](../tasks/2026-07-08_rate-guard-auth-hardening.md)

## Request path

```
https://rate-guard.richmom.vip/v1/fetch
  → Cloudflare (TLS terminates here)
  → cloudflared tunnel  (mathpilot-tunnel, host LaunchAgent
                         com.huawang.cloudflared.mathpilot-tunnel)
  → http://localhost:9099            (host-published port, bound to 127.0.0.1)
  → rate-guard:9000                  (container, on the projects-shared network)
  → Bearer-key check → gateway (host allowlist / https-only / no-redirect)
  → SEC / OpenFIGI / Dataroma
```

One shared Rate Guard serves dev **and** prod (and now the remote box). The
host port is bound to `127.0.0.1` so the only public path is the authenticated
tunnel — hitting the host's public IP on `:9099` is not possible.

## Cloudflared ingress (secret-free copy of the live host config)

Host file `~/.cloudflared/config.yml` (not in the repo). The `rate-guard` block
must sit **before** the `http_status:404` catch-all:

```yaml
ingress:
  - hostname: api.richmom.vip
    service: http://localhost:8080
  - hostname: study.richmom.vip
    service: http://localhost:3080
  - hostname: invest.richmom.vip
    service: http://localhost:3101
  - hostname: rate-guard.richmom.vip   # ← Rate Guard public exposure
    service: http://localhost:9099
  - service: http_status:404
```

DNS: a Cloudflare CNAME `rate-guard.richmom.vip → <tunnel-id>.cfargotunnel.com`,
created with `cloudflared tunnel route dns mathpilot-tunnel rate-guard.richmom.vip`.

## Authentication

App-level shared Bearer key (Option B — not Cloudflare Access). Enforced in
`rate-guard/app/auth.py`; every path except `/healthz` requires
`Authorization: Bearer <key>`.

| Env var | Where | Purpose |
|---|---|---|
| `RATE_GUARD_API_KEY` | host `~/.config/valuepilot/.env` (copied to the runner workspace `.env` on deploy) | The primary key (internal callers). Value is **never** committed. |
| `RATE_GUARD_API_KEY_<LABEL>` | same | Any additional accepted key, labelled by purpose — e.g. `RATE_GUARD_API_KEY_DEVELOPMENT` (remote dev box), `RATE_GUARD_API_KEY_PREVIOUS` (rotation window). A Bearer matching any is authorized. Don't put non-key config under this prefix. |
| `RATE_GUARD_REQUIRE_AUTH` | same | **Set to `1` on the exposed instance.** Makes an empty accepted-key set a hard startup failure — the container refuses to boot rather than silently serve an open proxy. |

**Current key assignment (2026-07-08):** `RATE_GUARD_API_KEY` = internal (host
prod + dev api); `RATE_GUARD_API_KEY_DEVELOPMENT` = the remote dev machine
(revocable on its own by dropping that var).

Fail-safe posture: with no key configured, auth is *disabled* (opt-in default,
for CI / internal). `RATE_GUARD_REQUIRE_AUTH=1` flips that to fail-closed for the
public deployment. Callers (`EdgarClient`/`OpenFigiClient`/`DataromaClient` via
`RateGuardClient`) send the key automatically when `RATE_GUARD_API_KEY` is set;
the remote box sets `RATE_GUARD_URL=https://rate-guard.richmom.vip` + the key.

## Rollback runbook — tear down the public path FIRST

A code-only revert removes the auth middleware **and** restores the `0.0.0.0`
host-port bind, while the tunnel + DNS still point at the container → that would
re-open an **unauthenticated public egress proxy**. Never revert the code while
the tunnel is live. Correct order:

1. **Remove the public path.** Delete the `rate-guard.richmom.vip` ingress block
   from `~/.cloudflared/config.yml`; `cloudflared --config ~/.cloudflared/config.yml
   tunnel ingress validate`; restart cloudflared
   (`launchctl kickstart -k gui/$(id -u)/com.huawang.cloudflared.mathpilot-tunnel`).
   Optionally delete the DNS CNAME in the Cloudflare dashboard.
2. **Verify** `curl -sI https://rate-guard.richmom.vip/healthz` no longer routes
   to the service (404 / no-route), and the other tunnels still answer.
3. **Only then** revert the code + redeploy.

Keep the `127.0.0.1:9099` bind even under rollback, so removing auth alone never
exposes the host IP.

## Rotation runbook (zero-downtime)

`is_authorized` accepts `RATE_GUARD_API_KEY` **and** any
`RATE_GUARD_API_KEY_<LABEL>`, so rotate without a hard cutover:

1. Set `RATE_GUARD_API_KEY_PREVIOUS` = the current key; set `RATE_GUARD_API_KEY`
   = a fresh `openssl rand -hex 32`. Redeploy Rate Guard (both keys now valid).
2. Update every caller to the new key: the host `.env` for internal api
   containers (**recreate** them — the api reads the key once at import, so a
   restart is not enough), and each remote client's labelled key.
3. Once all callers use the new key, remove `RATE_GUARD_API_KEY_PREVIOUS` and
   redeploy. The old key is now rejected.

Distinct labelled keys let internal and each remote client hold **different**
keys, so a leak of one is revoked (drop that var + recreate rate-guard) without
disrupting the others.

## Deferred hardening (see `docs/BACKLOG.md`)

- **Observability** — no 401/abuse metric or alert on the public path; add a
  Cloudflare WAF rate-limit rule on the subdomain + a 401-spike alert.
- **Separate dev/prod key values** — the remote dev box now has its own labelled
  key, but host prod and dev api still share `RATE_GUARD_API_KEY`; give them
  distinct labelled keys too.
- **Edge auth (future)** — Cloudflare Access service tokens / mTLS would give
  per-client identity + revocation; the app bearer would remain as
  defense-in-depth. Deferred by choice (Option B).
