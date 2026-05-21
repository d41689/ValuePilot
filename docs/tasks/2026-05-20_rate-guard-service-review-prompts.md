# Review prompt — Rate Guard service, PR 1/4 (2026-05-20, PR #76)

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the design doc
`docs/tasks/2026-05-20_rate-guard-design.md`.

---

## Reviewer brief

You are reviewing branch **`claude/rate-guard-service`** (PR #76) — the **first
of four** PRs building **Rate Guard**, a dedicated egress service that becomes
the single chokepoint for rate-limited external APIs (SEC EDGAR, OpenFIGI,
Dataroma).

**Why it exists:** rate limiting today lives inside each client, in-process
(`backend/app/edgar/client.py` has a module-level token bucket). dev and prod
run as separate processes on one host → one outbound IP, two limiters → the
*combined* egress rate is unbounded, which is how a ~3-hour EDGAR 403 IP block
happened. One shared single-process limiter fixes this structurally.

**Scope of THIS PR:** the service **only**. Nothing in `backend/` is repointed
at it yet — that is PR 2–4. So review it as *"is this service correct and safe
in isolation"*, not *"is the system integrated"*.

The **highest-risk** piece is the **host allowlist** (Question D): Rate Guard
forwards to caller-supplied URLs, so the allowlist is the boundary that stops
it being an open proxy / SSRF vector. Treat D as mandatory.

### Files in scope

- `rate-guard/app/` — `config.py`, `bucket.py`, `cache.py`, `metrics.py`,
  `gateway.py`, `main.py`
- `rate-guard/Dockerfile`, `requirements.txt`, `requirements-dev.txt`,
  `pytest.ini`, `tests/`
- `docker-compose.rateguard.yml`
- `.github/workflows/ci.yml` — the new `Run Rate Guard tests` step
- `docs/tasks/2026-05-20_rate-guard-design.md` — design (approved)

### Baseline

`git diff main...HEAD`. All of `rate-guard/` is new.

## Answer every question with a verdict + evidence

### A. Does it solve the stated problem

1. The design premise: **one** Rate Guard instance + every process routing
   through it ⇒ the combined egress rate is bounded by one token bucket per
   upstream. Confirm the service as built upholds that — i.e. the limiter state
   (`bucket`, `metrics`) is per-process and there is exactly one bucket per
   upstream. Flag anything that would reintroduce a second limiter.
2. Confirm PR 1 is genuinely inert for the rest of the repo (no `backend/`
   import of `rate-guard`, no compose wiring that routes traffic yet).

### B. Token bucket (`bucket.py`)

3. `TokenBucket.acquire()` lets `_tokens` go negative to reserve future
   capacity, and `time.sleep` happens **outside** the lock. Verify: (a) it is
   correct under concurrent callers (N threads each get spaced ~`1/rate`), (b)
   no busy-wait, (c) `burst` is honoured, (d) the refill math cannot let the
   effective rate exceed `rate_per_sec`.

### C. Gateway retry / 403 / 429 (`gateway.py`)

4. `_request_with_retry`: confirm the policy — `403` raises immediately (no
   retry); `429`/`503` set a 60s global pause then retry; `5xx` retry;
   transport errors retry; `2xx`/`3xx`/`404`/other-`4xx` return as-is. Check
   the retry counter has no off-by-one (`max_retries` retries actually
   attempted) and that backoff indexing into `backoff_s` is safe.
5. `_respect_pause` sleeps before a request when the upstream is paused, capped
   at `_MAX_PAUSE_WAIT`. Confirm a paused upstream cannot wedge a request
   thread indefinitely, and that the cap is sensible.
6. The token bucket is acquired once per attempt (each upstream call costs a
   token, retries included). Confirm that is intended.

### D. Host allowlist — security boundary (MANDATORY)

7. `Gateway.fetch` derives the host with `urlparse(url).hostname` and rejects
   anything not in the upstream's `allowed_hosts`. **Try to defeat it.**
   Confirm these are all rejected: `https://www.sec.gov@evil.com/x` (userinfo),
   a host with uppercase, a URL with no scheme, an empty/garbage URL. Confirm
   Rate Guard cannot be coerced into fetching an arbitrary host.
8. `method` is caller-supplied and passed straight to `httpx`. Is unrestricted
   method (e.g. `DELETE`) a concern given Rate Guard is internal-only? Flag if
   it should be allowlisted.

### E. Response cache (`cache.py`)

9. Cache key = `(upstream, method, url, body)`; only `200` is cached; writes
   are atomic (`tmp` + `replace`); TTL is checked on read. Confirm correctness,
   and that a corrupt/missing cache file degrades to a miss (no crash).
10. `POST` is cacheable (for the idempotent OpenFIGI map call, keyed on the
    body). Confirm caching a `POST` cannot return a stale/wrong result for the
    upstreams in scope. Also: `edgar` `cgi-bin/browse-edgar?...` query listings
    get the default 1 h TTL while `/Archives/` gets 30 days — is the 1 h
    listing TTL acceptable, or should listings be uncached?

### F. Config (`config.py`)

11. `_sec_user_agent()` falls back to `"<project> contact-not-configured"`
    when `SEC_CONTACT_EMAIL` is unset. SEC rejects requests without a proper
    UA → 403. Should Rate Guard instead **fail loud at startup** when the
    `edgar` upstream has no contact email? Give a recommendation.
12. OpenFIGI rate defaults (4 rps with key / 0.4 without) and the EDGAR 8 rps
    default — sane against the documented upstream limits?

### G. Service / compose / CI

13. `docker-compose.rateguard.yml` — one shared instance on `projects-shared`;
    cache on a bind-mount volume; `env_file: .env`. Confirm a single instance
    is what the topology needs, and that `.env` carries `SEC_CONTACT_EMAIL` /
    `OPENFIGI_API_KEY`.
14. `Dockerfile` uses an exec-form `CMD` (uvicorn = PID 1, clean SIGTERM).
    Sync FastAPI endpoints run in a threadpool ⇒ concurrent `fetch` calls.
    Confirm `Gateway` is thread-safe under that (bucket/metrics locks; one
    shared `httpx.Client`).
15. The `Run Rate Guard tests` CI step installs `requirements-dev.txt` and runs
    `pytest` on the runner. Confirm it is wired correctly.

### H. Tests

16. 14 tests cover bucket / cache / gateway. Material gaps to weigh: no test of
    the 429 → global-pause path, no `_respect_pause` test, no concurrency test,
    no test of the `main.py` FastAPI routes (`/v1/fetch`, `/v1/metrics`,
    `/healthz`). State which gaps are acceptable for PR 1 vs. should be added.

## Verification

- `cd rate-guard && pip install -r requirements-dev.txt && pytest -q` — 14 pass.
- `docker compose -f docker-compose.rateguard.yml up -d --build` then
  `curl localhost:9099/healthz` and `curl localhost:9099/v1/metrics`.

## Pass bar

Approve only if: **D7 holds** (the host allowlist cannot be defeated); the
token bucket (B3) genuinely bounds the rate; the retry/403/429 policy (C4) is
correct; the cache (E9–E10) is correct and fails safe; and PR 1 is confirmed
inert for the rest of the repo (A2). F11 (SEC UA on missing contact) and H16
(test gaps) are findings to record — block only if F11 is judged a real
foot-gun. The bar is "this service is correct and safe in isolation" — the
client integration is PR 2–4 and out of scope here.
