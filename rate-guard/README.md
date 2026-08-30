# Rate Guard

The normal egress chokepoint for ValuePilot's rate-limited upstreams (SEC
EDGAR, OpenFIGI, Dataroma). Production owns the central process. Development
prefers it but has a private, low-rate emergency fallback when the production
Mac or its public tunnel is offline.

Design and rationale: `docs/architecture/` is the long-form home; the working
design doc is `docs/tasks/2026-05-20_rate-guard-design.md`.

## Topology

The central Rate Guard container is owned by the production host and shared by
dev and prod. It has its own compose file (`docker-compose.rateguard.yml`) on
purpose — neither dev nor prod Compose may define another *central* Rate Guard,
and a remote development machine must not start that compose file.

Production reaches it at `http://rate-guard:9000` over `projects-shared`.
Development always uses `https://rate-guard.richmom.vip`; the production deploy
proves that public route and the private route expose the same persistent
instance identity before it starts the production API. The host port defaults
to `9099` and is loopback-only.

Development Compose also owns `rate-guard-local`, reachable only inside its
private network. The API selects it only when the central identity origin has
a transport/gateway-unavailable failure. Authentication failures, malformed
identities, and pinned-identity mismatches fail closed. A background probe
switches new clients back after recovery. Central SEC egress is pinned at 8
requests/second and fallback at 1, keeping their worst-case aggregate at 9.

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
| `RATE_GUARD_API_KEY_<LABEL>` | no | Any additional accepted Bearer key — e.g. `RATE_GUARD_API_KEY_DEVELOPMENT` for a remote dev box, `RATE_GUARD_API_KEY_PREVIOUS` for a rotation window. A request is authorized if its Bearer matches `RATE_GUARD_API_KEY` **or** any labelled key. (Don't put non-key config under this prefix.) |
| `RATE_GUARD_REQUIRE_AUTH` | no | Set to `1` on any **publicly-exposed** instance: a missing/blank key becomes a hard startup failure (fail-closed) instead of a silently-open proxy. |
| `RATE_GUARD_EDGAR_RPS` / `RATE_GUARD_OPENFIGI_RPS` / `RATE_GUARD_DATAROMA_RPS` | no | Per-upstream rate overrides. |

### `RATE_GUARD_URL` — for the ValuePilot app, not Rate Guard itself

ValuePilot's `EdgarClient` / `OpenFigiClient` / `DataromaClient` POST to Rate
Guard. Production Compose pins the private URL. Development Compose pins the
authenticated public URL, so a copied `.env` cannot accidentally select a
second local limiter.

Every production live API requires the persistent identity returned by the
central service:

```
RATE_GUARD_EXPECTED_INSTANCE_ID=<UUID returned by /v1/identity>
```

The production deploy obtains and injects this value automatically after
comparing private and public routes. A development machine may record the same
non-secret UUID in its local `.env`; when present, it remains a hard pin.
Without one, development accepts the structurally valid identity returned over
the authenticated HTTPS route for that process lifetime. An unreachable origin
selects the local fallback; malformed, unauthorized, or mismatched identity is
a hard failure. Replay mode performs no probes.

Development's adaptive settings are pinned by `docker-compose.yml`:

```
RATE_GUARD_ALLOW_LOCAL_FALLBACK=true
RATE_GUARD_FALLBACK_URL=http://rate-guard-local:9000
RATE_GUARD_PRIMARY_PROBE_INTERVAL_S=30
```

Never enable them in production.

## Endpoints

- `POST /v1/fetch` — `{upstream, method, url, body?}` → the upstream response.
- `GET /v1/metrics?upstream=<name>` — per-upstream rate/budget snapshot.
- `GET /v1/identity` — authenticated persistent installation UUID.
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
- Development Compose sets `RATE_GUARD_URL=https://rate-guard.richmom.vip`
  (HTTPS is mandatory off-box). Its local `.env` holds its independently
  revocable client key and the central `RATE_GUARD_EXPECTED_INSTANCE_ID`;
  `RateGuardClient` sends the key automatically.
- Give each caller its own labelled key (`RATE_GUARD_API_KEY_<LABEL>`) and rotate
  with a `RATE_GUARD_API_KEY_PREVIOUS` window. Full runbook, the live ingress/DNS manifest, and
  the **rollback order (tear down the tunnel before reverting code)** are in
  [`docs/architecture/rate-guard-public-exposure.md`](../docs/architecture/rate-guard-public-exposure.md).

## Tests

`docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"`

CI runs the same suite via the `Run Rate Guard tests` step.
