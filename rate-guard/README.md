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
`docker compose -f docker-compose.rateguard.yml up -d --build` is idempotent —
the container is only recreated when `rate-guard/` actually changed.

## Required environment

These live in the host file `~/.config/valuepilot/.env` (shared by dev and
prod — *not* in the repo). The deploy workflow copies it to `./.env`.

| Variable | Required | Purpose |
|---|---|---|
| `SEC_CONTACT_EMAIL` | **yes** | SEC mandates a contactable User-Agent. Rate Guard **fails loud at startup** without it. |
| `OPENFIGI_API_KEY` | no | Raises the OpenFIGI rate (~250/min with a key vs ~25/min without). |
| `RATE_GUARD_HOST_PORT` | no | Host port for `/healthz` + `/v1/metrics`. Default `9099`. |
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

## Tests

`docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"`

CI runs the same suite via the `Run Rate Guard tests` step.
