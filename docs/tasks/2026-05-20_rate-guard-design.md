# Rate Guard — design proposal (2026-05-20)

> Status: **draft for review**. No code until this is approved.

## 1. Problem

ValuePilot calls rate-limited external APIs — SEC EDGAR (~10 req/s, IP-banned
on abuse), OpenFIGI (25–250 req/min), Dataroma. Rate limiting today lives
**inside each client, in-process**:

- `backend/app/edgar/client.py` — a module-level `_TokenBucket` + `_REQUEST_EVENTS`
  deque + `_GLOBAL_PAUSE_UNTIL`. All **per-process, in-memory.**
- `OpenFigiClient`, `DataromaClient` — per-process `time.sleep` throttles.

dev and prod run as **separate processes on the same host → the same outbound
IP**. Each process has its own limiter, so the *combined* egress rate is
`dev + prod` — unbounded as a whole. That is exactly how audit item #2's ~3-hour
EDGAR 403 (IP block) happened. A per-process limiter cannot bound a shared IP.

## 2. Goals / non-goals

**Goals**

- One process-independent chokepoint per external upstream, so the *combined*
  egress rate across dev + prod (+ CLI, workers) is structurally bounded.
- Centralize per-upstream concerns: rate limit, retry/backoff, the SEC
  User-Agent, OpenFIGI key, 429/503 global-pause, request metrics.
- Safe by construction — no "remember to flip a switch."
- Reuse the proven `EdgarClient` token-bucket / retry / 429 logic; lift it into
  the shared service rather than reinvent it.

**Non-goals**

- Not a general egress proxy. Low-volume webhooks (Slack/Discord) are out.
  Market-data (`yfinance`/`twelvedata`) can be added later as config — not in
  the initial rollout (decision below).

## 3. Architecture

A small dedicated service — **Rate Guard** — is the sole egress point for
rate-limited upstreams. Every ValuePilot process sends its external request to
Rate Guard; Rate Guard performs the real upstream call under a **single** token
bucket per upstream and returns the response.

```
 dev api / dev worker  ─┐
 prod api / prod worker ─┼─▶  Rate Guard  ──▶  SEC EDGAR / OpenFIGI / Dataroma
 CLI (one-off jobs)    ─┘   (one instance,
                            one bucket/upstream)
```

Because there is exactly **one** Rate Guard instance and it is a single
process, the limiter is trivially correct — no distributed-lock / shared-state
race to get right (see Alternatives).

**Tech:** a small FastAPI app (consistent with the stack), its own container.
The rate-limit state is in-memory in that one process — which is correct,
because it *is* one process. That is the whole point.

## 4. Interface

Rate Guard exposes a thin fetch RPC. Clients do not path-rewrite; they pass the
real target URL:

```
POST /v1/fetch
  { "upstream": "edgar", "method": "GET",
    "url": "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR2/form.20260519.idx" }
→ 200 { "status": 200, "body_b64": "...", "headers": {...} }
  (or a structured error after retries are exhausted)

GET  /v1/metrics?upstream=edgar     → the rate-limit/budget snapshot
GET  /healthz
```

Rate Guard **validates** that `url`'s host is in the upstream's allowlist
(`edgar` → `www.sec.gov`, `efts.sec.gov`; `openfigi` → `api.openfigi.com`;
`dataroma` → `www.dataroma.com`) — it will not forward to an arbitrary host.

## 5. Internals (per upstream)

Each upstream is config-driven:

| field | edgar | openfigi | dataroma |
|---|---|---|---|
| host allowlist | `*.sec.gov` | `api.openfigi.com` | `www.dataroma.com` |
| rate | 10 req/s (token bucket, burst 1) | 25 or 250 req/min (key-dependent) | ~0.5 req/s |
| retry / backoff | 5×, `5,30,120,300,300`s | (add — none today) | 2×, `10,60`s |
| injected headers | SEC User-Agent | `X-OPENFIGI-APIKEY` | browser UA |
| 429/503 | global-pause 60s, drop to 1 req/s | global-pause | basic retry |

The token bucket + retry + 429 global-pause logic is **lifted from the existing
`edgar/client.py`** — proven code, just relocated to the shared process.

Rate Guard keeps the per-upstream metrics the admin panel needs
(`recent_request_count`, `recent_403_count`, `recent_429_count`,
`global_pause_until`, `estimated_capacity`, …) and serves them at `/v1/metrics`.

## 5b. Response cache (v1)

Many upstream responses are immutable or slow-changing — re-fetching them
wastes rate-limit budget. Rate Guard keeps a per-upstream response cache:

- **Key:** `(upstream, method, url)`. Only `GET` (and idempotent `POST` for
  OpenFIGI map — keyed on the request body hash) are cacheable.
- **Per-upstream TTL config:**
  - `edgar` — `Archives/edgar/...` index/filing files are immutable once
    published → long TTL (e.g. 30 days). `cgi-bin/browse-edgar` listings →
    short TTL (e.g. 1 h) or uncached.
  - `openfigi` — CUSIP→ticker mappings are slow-changing → medium TTL (e.g.
    7 days).
  - `dataroma` — manager/holdings pages change → short TTL (e.g. 1 h) or off.
- **Store:** on-disk, content-addressed under a cache dir (a bind-mounted
  volume so it survives restarts); a small in-memory index. A cache hit skips
  the upstream call *and* the token bucket entirely.
- Only `200` responses are cached; never errors.
- `/v1/metrics` reports cache hit/miss counts per upstream.

## 6. Topology — one instance, shared by dev + prod

For Rate Guard to bound the *combined* rate, dev and prod must hit the **same**
instance. They already share a docker network — `projects-shared` (prod compose
`networks: shared-infra: external: projects-shared`).

- Rate Guard runs as **one** container on `projects-shared` (own compose file,
  or alongside prod). dev compose does **not** define its own — that would be
  two buckets and defeat the purpose.
- dev and prod set `RATE_GUARD_URL=http://rate-guard:PORT` and reach the one
  instance over the shared network.

## 7. Client changes

`EdgarClient` / `OpenFigiClient` / `DataromaClient` become **thin
pass-throughs**: when `RATE_GUARD_URL` is set they POST to Rate Guard instead
of calling the upstream directly, and they drop their own token-bucket / retry
code (Rate Guard owns it). Public method signatures (`get()`, `map_cusips()`,
…) are unchanged, so the ~10 call sites need no edits.

**Safety:** in `EDGAR_FETCH_MODE=live`, a missing `RATE_GUARD_URL` is a
**hard startup error** — live external access without the guard is not allowed.
Tests and CI run mocked / `replay` mode, so they need no Rate Guard.

## 8. Test / mock strategy

Unchanged for unit tests: they inject `FakeEdgarClient` etc. by parameter, or
run `EDGAR_FETCH_MODE=replay` — neither touches Rate Guard. CI (GitHub-hosted,
mocked) does not run Rate Guard. Rate Guard gets its own focused tests (bucket,
retry, host-allowlist, 429 pause).

## 9. Admin observability

The `/api/v1/admin/edgar-rate-limit` panel currently reads one api process's
in-memory deque. It will instead proxy Rate Guard's `/v1/metrics` — so the
panel shows the *true* global budget, and can show OpenFIGI / Dataroma too.

## 10. Build phasing (multi-PR)

1. **Rate Guard service** — the FastAPI gateway, per-upstream buckets, retry,
   `/v1/fetch` + `/v1/metrics` + `/healthz`, host allowlist, its own tests and
   container. Standalone; nothing else changes yet.
2. **Repoint `EdgarClient`** to Rate Guard; slim it; the live-mode startup guard.
3. **Repoint `OpenFigiClient` + `DataromaClient`.**
4. **Admin panel** reads Rate Guard `/v1/metrics`.

Each PR is independently CI-green and deployable.

## 11. Risks & mitigations

- *Rate Guard is a new single point of failure.* If it is down, external
  access stops — but "stopped" is a safe degraded state, far better than an IP
  ban. It is small and simple; `restart: unless-stopped`.
- *Extra hop / latency.* One in-network hop; negligible vs. the deliberate
  rate-limit delays already in play.
- *Cross-project network.* `projects-shared` is already used by prod; no new
  infra.

## 12. Alternatives considered

- **A-lite — shared rate-limit state (DB/Redis-backed bucket), no new service.**
  Avoids a new container, but a *distributed* token bucket is genuinely harder
  to make correct (races, clock skew) than one in-process bucket. Rejected in
  favour of the single-process service.
- **Env switch (dev on / others off).** Fragile — a forgotten switch bans the
  shared IP, taking prod down. Rejected.

## 13. Resolved decisions (2026-05-20)

1. **Initial upstreams** — `edgar`, `openfigi`, `dataroma`. Market-data and
   webhooks are deferred (addable later as config).
2. **Deployment** — its own `docker-compose.rateguard.yml`, one shared
   instance on the `projects-shared` network.
3. **Response cache** — **in scope for v1** (see §5b).

## 14. Build log

- **PR 1 — the Rate Guard service.** `rate-guard/` (FastAPI app: `config`,
  `bucket`, `cache`, `metrics`, `gateway`, `main`), `Dockerfile`,
  `docker-compose.rateguard.yml`, unit tests, a CI step. Standalone —
  nothing else points at it yet.
  - **Review (PR #76) — remediated.** External review flagged one blocker
    and two advisories:
    - *Blocker* — `_request_with_retry` armed a global pause on 429/503 but
      the retry loop only slept its own backoff, so retries fired through
      the pause. Fixed: `_respect_pause` now runs as the first step of every
      retry iteration; the one-shot pre-flight call in `fetch()` was removed.
    - *Advisory* — only `https` URLs are accepted; `fetch()` rejects any
      other scheme alongside the existing host allowlist check.
    - *Advisory* — `_sec_user_agent()` raises `RuntimeError` when
      `SEC_CONTACT_EMAIL` is unset instead of shipping a placeholder UA, so
      a misconfigured `edgar` upstream fails loud at startup.
    - The global-pause duration moved from a module constant to a
      per-upstream `Upstream.pause_s` field (default 60s).
  - Verified: 16 tests pass (added `test_429_global_pause_is_respected_before_retry`
    and `test_rejects_non_https_url`); the container builds, starts, and
    serves `/healthz` + `/v1/metrics` for all three upstreams.
  - PR #76 merged after that review approved it.
- **PR 1 fix — redirect bypass + cache concurrency.** An independent second
  review (`…-review-result-2.md`) found two blockers PR #76 shipped, both
  reproduced empirically:
  - *P1 (security)* — the host allowlist was bypassable via HTTP redirects:
    the httpx client used `follow_redirects=True`, and a 3xx is not
    re-checked against the allowlist, so an allowlisted host could bounce a
    fetch to an arbitrary host. Fixed: `follow_redirects=False` — a 3xx is
    now returned to the caller as-is (consistent with the existing
    `_request_with_retry` comment).
  - *P2* — `ResponseCache.put` shared one fixed `{key}.tmp` filename, so two
    threads writing the same key raced and ~43% of writes crashed with
    `FileNotFoundError`. Fixed: each write uses a unique `tempfile.mkstemp`
    temp file, then `os.replace`; the temp file is cleaned up on failure.
  - Verified: 18 tests pass (added `test_redirect_to_off_allowlist_host_is_not_followed`
    and `test_concurrent_put_same_key_does_not_crash`).
  - **Review (PR #78) — remediated.** An independent review confirmed both
    fixes are correct in production but flagged the P1 regression test as
    decorative: it always injects its own `httpx` client (default
    `follow_redirects=False`), so `Gateway.__init__`'s production-default
    client — the actual fix line — is never exercised; reverting it would
    not turn the test red. Added `test_default_client_does_not_follow_redirects`,
    which builds a `Gateway` with `client=None` and asserts
    `_client.follow_redirects is False`. Verified it goes red when the fix is
    reverted. 19 tests pass.
  - PR #78 merged after the final re-review approved it.
- **PR 1.5 — prod deploy integration.** PR 2/4 will make a live-mode prod api
  hard-depend on Rate Guard, and the runner auto-deploys every `main` push, so
  Rate Guard must be running *before* that dependency lands.
  `scripts/deploy_prod_from_main.sh` now brings up
  `docker-compose.rateguard.yml` and waits for `/healthz` before the prod
  stack; `deploy.yml` dumps rateguard logs on failure; `rate-guard/README.md`
  is the operator runbook (required `.env` keys, the `RATE_GUARD_URL`
  pre-merge step for PR 2/4). Task doc:
  `docs/tasks/2026-05-20_rate-guard-deploy-integration.md`.
- PR 2 — repoint `EdgarClient`; slim it; live-mode startup guard. *(next)*
- PR 3 — repoint `OpenFigiClient` + `DataromaClient`.
- PR 4 — admin `edgar-rate-limit` panel reads Rate Guard `/v1/metrics`.
