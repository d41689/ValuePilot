# Review result (independent second review) — Rate Guard service, PR #76

Date: 2026-05-20
Branch reviewed: `claude/rate-guard-service`
Prompt: `docs/tasks/2026-05-20_rate-guard-service-review-prompts.md`
Reviewer: independent re-review (Claude Code)

## Relationship to the existing `…-review-result.md`

This branch already carries `docs/tasks/2026-05-20_rate-guard-service-review-result.md`,
a prior review that ended **批准 / approved** after one remediation round. This
file is a **separate, independent review** and was not influenced by that
verdict. It reaches a **different conclusion**: two real defects the prior
review marked "pass" — the host allowlist (D7) and the cache (E9) — do not hold
up. Both are demonstrated empirically below. The prior review's other findings
(the 429-pause blocker and its remediation) are confirmed correct.

## Verdict

**暂不批准 / Not approved.**

Two blocking findings:

- **[P1] The host allowlist is bypassable via HTTP redirects** — the security
  boundary the whole service exists to provide does not actually hold. Fails the
  mandatory pass-bar item D7.
- **[P2] `ResponseCache.put` is not concurrency-safe** — under the exact
  concurrent workload the cache is built for, ~43% of writes crash. Fails the
  pass-bar item "the cache (E9–E10) is correct and fails safe".

Everything else in the prompt passes or is a recordable non-blocking finding.
The token bucket bounds the rate, the retry/403/429 policy is correct (the prior
429-pause remediation is verified), PR 1 is genuinely inert for the rest of the
repo, and the service fails loud on a missing SEC contact.

## Blocking findings

### [P1] Host allowlist bypassable via redirects (Question D — MANDATORY)

`Gateway.__init__` builds the production HTTP client with
`follow_redirects=True` (`rate-guard/app/gateway.py:48`). `Gateway.fetch`
validates the host **only on the caller-supplied URL** (`gateway.py:61-71`); the
unchanged `url` string is then handed to `httpx` (`gateway.py:111`), which will
**follow a 3xx to any host without re-checking the allowlist**.

So an allowlisted host that issues a redirect (an open-redirect endpoint, a CDN
hop, a vanity-URL redirect — all common on large sites like `*.sec.gov`) makes
Rate Guard fetch and return content from a host that is **not** on the
allowlist. The allowlist's stated contract (design §4: "it will not forward to
an arbitrary host"; prompt D: "stops it being an open proxy / SSRF vector") is
not upheld.

**Empirically demonstrated** (PROBE 2, production `follow_redirects=True`
client via `MockTransport`): `fetch("test", "GET", "https://example.com/...")`
where only `example.com` is allowlisted followed a `302 → https://evil.com/...`
and returned `b"CONTENT-FROM-EVIL-COM"`.

There is also an internal inconsistency: `gateway.py:131-133` comments that
"2xx/3xx/404/other-4xx are definitive — return as-is", i.e. it expects a 3xx to
reach the caller — but `follow_redirects=True` consumes the 3xx before the
gateway ever sees it.

**Fix (recommended):** set `follow_redirects=False`. That closes the bypass
*and* makes the code consistent with its own `gateway.py:131-133` comment (the
3xx-return-as-is branch would then actually fire — the caller decides what to do
with a redirect). If a specific upstream genuinely needs redirect-following,
follow manually and re-run the `gateway.py:61-71` host check on every hop. Add a
regression test (a `MockTransport` 302 to a non-allowlisted host must raise
`UpstreamError`, not return the off-host body).

### [P2] `ResponseCache.put` is not concurrency-safe (Questions E9 / G14)

`ResponseCache.put` writes through a **fixed** temp filename derived only from
the key — `tmp = path.with_suffix(".tmp")` (`rate-guard/app/cache.py:55-57`).
Two threads writing the **same key** therefore share one `{key}.tmp` file: they
interleave their `write_text`, and the second `tmp.replace(path)` raises
`FileNotFoundError` because the first thread already renamed the temp away.
`Gateway.fetch` does not wrap `self._cache.put` (`gateway.py:91`), so that
exception propagates out of `/v1/fetch` as an HTTP 500.

This is not a rare edge — it is the cache's **designed-for** workload. `cache.py`
docstring: "two callers asking for the same immutable EDGAR archive file share
one fetch". FastAPI sync endpoints run in a threadpool (Dockerfile/uvicorn), so
two concurrent identical misses calling `put` on one key is normal.

**Empirically demonstrated** (PROBE 3): 16 threads × 80 `put`s on one key →
**557 / 1280 crashed** with
`FileNotFoundError: …/<key>.tmp -> …/<key>.json`.

**Fix:** write to a unique temp file per call — e.g. `tempfile.mkstemp(dir=path.parent)`
(or append pid + thread-id + counter) — then `os.replace` it onto `path`. The
`replace` is already atomic; only the shared temp *name* is the bug.

## A. Does it solve the stated problem

1. **Single limiter — PASS.** `Gateway.__init__` builds exactly one
   `TokenBucket` and one `UpstreamMetrics` per upstream
   (`gateway.py:44-47`); all state is per-process. One Rate Guard instance ⇒ one
   bucket per upstream ⇒ combined egress is bounded. No second limiter is
   reintroduced.
2. **PR 1 inert — PASS.** `git diff main...HEAD --name-only` touches **no
   `backend/` files**. No `backend/` import of `rate-guard`; no dev/prod compose
   is repointed. The service is isolated behind `docker-compose.rateguard.yml`
   plus a CI step.

## B. Token bucket (`bucket.py`)

3. **PASS.** `acquire()` (`bucket.py:29-41`) refills under the lock, lets
   `_tokens` go negative to reserve future capacity, computes `wait`, then
   `time.sleep`s **outside** the lock — so N concurrent callers are each spaced
   ~`1/rate` (caller k waits `(k-1)/rate`) without serialising on the sleep.
   No busy-wait (one `sleep`). `burst` is honoured via `_capacity`. Sustained
   rate cannot exceed `rate_per_sec`: refill is `elapsed*rate` capped at
   capacity, each `acquire` consumes exactly 1, and the post-lock sleep can only
   make a caller *later*, never earlier. Covered by `test_bucket.py`.

## C. Gateway retry / 403 / 429 (`gateway.py`)

4. **PASS.** `_request_with_retry` (`gateway.py:99-142`): `403` raises
   immediately (`:120-124`), no retry; `429`/`503` arm a global pause and retry
   (`:125-130`); `5xx` and transport errors retry; `2xx/3xx/404`/other-`4xx`
   return as-is (`:131-133`). Retry counting is correct — `max_retries=5` ⇒ 6
   total attempts (1 initial + 5 retries); the raise fires at `attempt >
   max_retries` (`:135`). Backoff indexing `backoff_s[min(attempt-1, len-1)]`
   (`:141`) is bounds-safe. The prior review's P1 (429 pause not respected) is
   genuinely fixed: `_respect_pause` now runs first in **every** retry iteration
   (`:104-108`), verified by `test_429_global_pause_is_respected_before_retry`.
5. **PASS (with a note).** `_respect_pause` (`gateway.py:165-170`) caps a single
   wait at `_MAX_PAUSE_WAIT = 120s`. A request thread cannot wedge
   *indefinitely* — total wait is bounded by `(max_retries+1) × (120 + backoff)`.
   Note: for `edgar` the worst case is ~40 min of a held threadpool thread; a
   burst of requests during a long upstream pause could pressure the uvicorn
   threadpool. Acceptable for PR 1; worth watching once integrated.
6. **PASS.** The bucket is acquired once per attempt inside the loop
   (`gateway.py:109`), so retries consume tokens too. Correct — each retry is a
   real upstream request and must count against the limit.

## D. Host allowlist — security boundary (MANDATORY)

7. **FAIL — see [P1].** The *direct-URL* allowlist itself is sound: PROBE 1
   confirmed `urlparse(url).hostname` (`gateway.py:67`) and what `httpx` actually
   connects to agree on every bypass vector — userinfo
   (`https://www.sec.gov@evil.com/x` → `evil.com`, rejected), uppercase
   (normalised, legit host allowed), backslash, fragment, no-scheme, empty —
   **no parser-differential bypass**, and the `https`-only scheme gate
   (`gateway.py:62-66`) plus exact-set membership are correct. **But** the
   boundary as a whole fails: `follow_redirects=True` lets an allowlisted host
   redirect the fetch to an arbitrary host (PROBE 2). D7 requires "Rate Guard
   cannot be coerced into fetching an arbitrary host" — it can.
8. **Advisory (non-blocking).** `method` is caller-supplied, `.upper()`-ed and
   passed straight to `httpx` (`gateway.py:59,111`; `main.py:28-31`) — no
   allowlist. Against the in-scope read-oriented upstreams a stray `DELETE`/`PUT`
   just earns a 405, and Rate Guard is internal-only, so this is low-risk. Still
   worth a per-upstream `{GET, POST, HEAD}` allowlist as defence-in-depth.

## E. Response cache (`cache.py`)

9. **FAIL — see [P2].** Read-side behaviour is correct: a missing or corrupt
   cache file degrades to a miss — `get` catches `FileNotFoundError, ValueError,
   OSError` (`cache.py:36-39`; `ValueError` covers `JSONDecodeError` and
   `UnicodeDecodeError`), and TTL is enforced on read (`:40-42`). Only `200` is
   cached (`gateway.py:90`). **But** the write path is not concurrency-safe (the
   shared `.tmp` filename) and crashes ~43% of the time under concurrent
   same-key writes.
10. **PASS (with notes).** Caching `POST` keyed on the body (`cache.py:21-27`)
    is correct for the only in-scope `POST` — the idempotent OpenFIGI mapping
    call. Note: the cache layer will cache *any* `POST` whenever `cache_ttl_s >
    0` — a latent foot-gun if a future upstream has a non-idempotent `POST`;
    consider making `POST` cacheability opt-in per upstream. The 1 h default TTL
    on `edgar` non-`/Archives/` listings (`cgi-bin/browse-edgar`, `data.sec.gov`
    JSON) is acceptable — daily-cadence 13F ingestion tolerates ≤1 h staleness;
    drop it to `0` later only if sub-hour index freshness is ever needed.

## F. Config (`config.py`)

11. **PASS — prompt premise is outdated.** The prompt says `_sec_user_agent()`
    "falls back to a placeholder". The actual code **raises `RuntimeError`** when
    `SEC_CONTACT_EMAIL` is unset (`config.py:42-56`), and `build_upstuts` runs at
    `main.py` import time (`main.py:23`) — so a misconfigured `edgar` upstream
    **fails loud at startup**, exactly what F11 asks for. Verified (PROBE 4:
    `build_upstreams()` raised `RuntimeError`). No change needed.
12. **PASS.** EDGAR 8 rps (`config.py:66`) sits below SEC's ~10 rps limit with
    headroom. OpenFIGI 4 rps with key / 0.4 without (`:81-84`) tracks the
    documented mapping-endpoint quotas. Dataroma 0.5 rps (`:95`) matches the
    existing `DATAROMA_REQUEST_DELAY_S=2.0` in the main app. Sane.

## G. Service / compose / CI

13. **PASS.** `docker-compose.rateguard.yml` defines one shared `rate-guard`
    service on the external `projects-shared` network with a bind-mounted cache
    — the topology the design requires (one instance ⇒ one limiter). It relies
    on `.env` carrying `SEC_CONTACT_EMAIL` / `OPENFIGI_API_KEY`; the compose
    comment (`:16`) states this, and the F11 fail-loud behaviour means a missing
    contact crash-loops the container loudly rather than shipping a bad UA.
    Recommend a short runbook / `.env.example` note so an operator sets it
    before first deploy.
14. **PASS for bucket/metrics/client; FAIL for the cache.** `Dockerfile:14` uses
    an exec-form `CMD` ⇒ uvicorn is PID 1, clean SIGTERM. Sync FastAPI handlers
    run in a threadpool. `TokenBucket` and `UpstreamMetrics` each guard state
    with their own lock; one shared `httpx.Client` is thread-safe for concurrent
    requests. The one un-thread-safe component is `ResponseCache.put` — see [P2].
15. **PASS (with a minor note).** The `Run Rate Guard tests` CI step
    (`.github/workflows/ci.yml`) `cd`s into `rate-guard`, installs
    `requirements-dev.txt`, runs `pytest -q`, and gates the job. Note: unlike the
    rest of CI it runs **on the runner host**, not in a container, and pins no
    Python version (no `actions/setup-python`) — it inherits whatever
    `ubuntu-latest` ships. Works today; slightly fragile. Non-blocking.

## H. Tests

16. **Adequate for the happy paths; the safety-critical gaps are now larger
    than the prompt states.** 16 tests cover bucket basics/burst, cache
    roundtrip/TTL/keying, host + non-https rejection, cache hit, 403 no-retry,
    5xx retry + exhaustion, 429 global-pause, and metrics. Missing — and given
    P1/P2 these are no longer optional:
    - **no redirect-bypass test** (would have caught P1);
    - **no concurrent-`cache.put` test** (would have caught P2);
    - no `_respect_pause` direct test, no automated concurrency test for the
      bucket, no `main.py` route tests (`/v1/fetch`, `/v1/metrics`, `/healthz`).
    The redirect and concurrency tests must land with the P1/P2 fixes; the route
    tests are a reasonable follow-up.

## Verification run

- `docker run --rm -v "$PWD/rate-guard:/code" … python:3.11-slim` —
  `pip install -r requirements-dev.txt && python -m pytest -q` → **16 passed**.
- PROBE 1 (urlparse vs httpx host parsing, 10 vectors) — **no bypass**; the two
  parsers agree on every vector.
- PROBE 2 (production `follow_redirects=True` gateway via `MockTransport`) —
  **allowlist bypassed**: `fetch` of an allowlisted host followed a 302 and
  returned the off-allowlist body.
- PROBE 3 (16 threads × 80 `cache.put` on one key) — **557 / 1280 crashed** with
  `FileNotFoundError` on the shared `.tmp` → `.json` rename.
- PROBE 4 (`build_upstreams()` with `SEC_CONTACT_EMAIL` unset) — raised
  `RuntimeError` (fail-loud confirmed).

## Required before approval

1. **P1** — stop the redirect bypass: `follow_redirects=False` (recommended), or
   re-validate every redirect hop against the allowlist. Add a regression test.
2. **P2** — make `ResponseCache.put` concurrency-safe with a unique temp file
   per write. Add a concurrent-`put` regression test.
3. Re-run the verification (16 tests + the P1/P2 regression tests) and the
   redirect/concurrency probes.

Non-blocking, record as follow-ups: D8 (method allowlist), E10 (per-upstream
opt-in for `POST` caching), G15 (CI step runs on the runner host, unpinned
Python), H16 route tests, and a runbook note for the `SEC_CONTACT_EMAIL`
prerequisite.

The bar applied is the prompt's: "this service is correct and safe in
isolation." It is not yet — the allowlist, which is the reason the service
exists, can be defeated.
