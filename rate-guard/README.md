# Rate Guard

The single egress chokepoint for ValuePilot's rate-limited upstreams (SEC
EDGAR, OpenFIGI, Dataroma). dev and prod run on the same host behind the same
outbound IP, so a per-process limiter cannot bound the *combined* rate — one
shared Rate Guard instance can.

Design and rationale: `docs/architecture/` is the long-form home; the working
design doc is `docs/tasks/2026-05-20_rate-guard-design.md`.

## Topology

**One** Rate Guard container, shared by dev and prod, on the external
`projects-shared` Docker network. It has its own compose file
(`docker-compose.rateguard.yml`) on purpose — neither the dev nor the prod
compose may define its own Rate Guard, or there would be two limiters.

Internal callers reach it at `http://rate-guard:9000` over `projects-shared`.
The host port (`/healthz`, `/v1/metrics` inspection only) defaults to `9099`.

## Deployment

The prod deploy script (`scripts/deploy_prod_from_main.sh`) brings Rate Guard
up and waits for `/healthz` **before** the prod stack, on every `main` deploy.
`docker compose -f docker-compose.rateguard.yml up -d --build` recreates the
container only when something changed — the `rate-guard/` sources, the compose
file, or an interpolated env value — so an unrelated deploy leaves the running
container untouched.

Because dev and prod share this one instance, a deploy that *does* rebuild
Rate Guard restarts it in place — there is no blue-green swap or automatic
rollback (the same deploy model as the prod `api` / `web`). Any upstream
request in flight at that moment is dropped and the caller retries. Brief and
rare, but worth knowing — a safer staged rollout is a tracked follow-up for
Rate Guard PR 2/4 (`docs/BACKLOG.md`).

## Required environment

These live in the host file `~/.config/valuepilot/.env` (shared by dev and
prod — *not* in the repo). The deploy workflow copies it to `./.env`.

| Variable | Required | Purpose |
|---|---|---|
| `SEC_CONTACT_EMAIL` | **yes** | SEC mandates a contactable User-Agent. Rate Guard **fails loud at startup** without it. |
| `OPENFIGI_API_KEY` | no | Raises the OpenFIGI rate (~250/min with a key vs ~25/min without). |
| `RATE_GUARD_HOST_PORT` | no | Host port for `/healthz` + `/v1/metrics` (bound to `127.0.0.1`). Default `9099`. |
| `RATE_GUARD_API_KEY` | no | Shared Bearer key. **Set only when Rate Guard is exposed publicly** (see below). Unset = auth disabled (internal-only default). |
| `RATE_GUARD_API_KEY_PREVIOUS` | no | A second accepted Bearer key — the rotation window, or a distinct client key. |
| `RATE_GUARD_REQUIRE_AUTH` | no | Set to `1` on any **publicly-exposed** instance: a missing/blank key becomes a hard startup failure (fail-closed) instead of a silently-open proxy. |
| `RATE_GUARD_EDGAR_RPS` / `RATE_GUARD_OPENFIGI_RPS` / `RATE_GUARD_DATAROMA_RPS` | no | Per-upstream rate overrides. |

### `RATE_GUARD_URL` — for the ValuePilot app, not Rate Guard itself

ValuePilot's `EdgarClient` / `OpenFigiClient` / `DataromaClient` will POST to
Rate Guard when `RATE_GUARD_URL` is set. **Before Rate Guard PR 2/4 merges**,
add to `~/.config/valuepilot/.env`:

```
RATE_GUARD_URL=http://rate-guard:9000
```

In `EDGAR_FETCH_MODE=live`, PR 2/4 makes a missing `RATE_GUARD_URL` a hard
startup error — live external access without the guard is not allowed.

## Endpoints

- `POST /v1/fetch` — `{upstream, method, url, body?}` → the upstream response.
- `GET /v1/metrics?upstream=<name>` — per-upstream rate/budget snapshot.
- `GET /healthz` — liveness.

## Public exposure (authenticated)

Rate Guard is internal-only by default. If a machine outside the
`projects-shared` network needs it (e.g. a remote dev box), expose it through
the existing Cloudflare Tunnel on a **dedicated subdomain** and require the
shared key:

```
https://rate-guard.richmom.vip/v1/fetch  →  cloudflared  →  localhost:9099  →  rate-guard:9000
```

- Use a **subdomain**, not a path under an existing host — cloudflared does not
  strip a path prefix, so `.../rate-guard/v1/fetch` would arrive as
  `/rate-guard/v1/fetch` and 404. A subdomain maps `/v1/fetch` straight through.
- Set `RATE_GUARD_API_KEY` (see `openssl rand -hex 32`) **and**
  `RATE_GUARD_REQUIRE_AUTH=1`. With a key set, every path except `/healthz`
  requires `Authorization: Bearer <key>`; `/v1/fetch` and `/v1/metrics` return
  `401` without it, **before** any upstream call. With `RATE_GUARD_REQUIRE_AUTH=1`
  the container refuses to boot if the key is ever dropped — so an env slip fails
  closed, never silently open.
- The host port (`9099`) binds to `127.0.0.1` only, so the key can't be
  bypassed by hitting `http://<host-public-ip>:9099/v1/fetch` directly — the
  authenticated tunnel is the sole public path.
- The remote caller sets `RATE_GUARD_URL=https://rate-guard.richmom.vip` (must be
  **https** — the client warns if a key is set on a non-https off-box URL) and the
  same `RATE_GUARD_API_KEY`; `RateGuardClient` sends the header automatically.
- Rotate keys with the two-slot mechanism (`RATE_GUARD_API_KEY` +
  `RATE_GUARD_API_KEY_PREVIOUS`). Full runbook, the live ingress/DNS manifest, and
  the **rollback order (tear down the tunnel before reverting code)** are in
  [`docs/architecture/rate-guard-public-exposure.md`](../docs/architecture/rate-guard-public-exposure.md).

## Tests

`docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"`

CI runs the same suite via the `Run Rate Guard tests` step.
