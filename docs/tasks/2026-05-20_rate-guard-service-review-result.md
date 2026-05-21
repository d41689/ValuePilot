# Review result — Rate Guard service PR #76

Date: 2026-05-20
Branch reviewed: `claude/rate-guard-service`
Prompt: `docs/tasks/2026-05-20_rate-guard-service-review-prompts.md`

## Second-review verdict

批准。

2026-05-20 remediation verified: the 429/503 global pause is now respected by
the current retry loop, non-HTTPS schemes are rejected, and missing
`SEC_CONTACT_EMAIL` now fails loudly at startup. The original blocking finding
below is resolved.

## Original verdict

暂不批准。

The service is structurally close: the host allowlist blocks arbitrary hosts,
the token bucket bounds normal egress, cache behavior is mostly sound, and the
compose/CI wiring works. One pass-bar item fails: `429` / `503` global-pause
handling does not apply to the current retry loop, so the request can retry
immediately into an upstream-imposed pause.

## Blocking Finding

### [P1] 429/503 global pause is set but not respected before retrying

In `Gateway.fetch()`, `_respect_pause(upstream)` runs once before
`_request_with_retry()`. Inside `_request_with_retry()`, a `429` or `503` calls
`self._metrics[u.name].pause(60)`, but the next retry only sleeps the normal
`backoff_s` value. It does not call `_respect_pause()` again before the next
attempt.

Probe result with `max_retries=1` and `backoff_s=(0.0,)`:

- first upstream response: `429`
- global pause set for 60s
- second attempt happened about `0.001s` later
- final response returned `200`

That violates the intended 429/503 policy: when the upstream says slow down,
Rate Guard should pause this request's retry too, not just future independent
requests. Recommended fix: before each retry attempt, respect the pause for the
same upstream, or make the 429/503 branch sleep the pause duration before
continuing. Add a test that 429 sets `global_pause_until` and delays the next
attempt, with a small monkeypatched pause duration for test speed.

### Remediation status: resolved

`Gateway._request_with_retry()` now calls `_respect_pause(u.name)` before every
attempt. A 429/503 sets `pause(u.pause_s)`, and the same in-flight retry waits
that pause before trying again. The new test uses `pause_s=0.3` with zero
backoff and verifies the retry is delayed.

The implementation also tightened the allowlist boundary by requiring
`https` URLs before any host comparison or upstream call.

## A. Does it solve the stated problem

1. **Single limiter premise: pass.** `Gateway` owns one `TokenBucket` and one
   `UpstreamMetrics` per configured upstream in one process. If dev/prod clients
   both route through a single deployed Rate Guard instance, combined egress is
   bounded by that one bucket per upstream.
2. **PR 1 inertness: pass.** No `backend/` code imports or calls Rate Guard yet,
   and neither dev nor prod compose is repointed in this PR. The new service is
   isolated behind `docker-compose.rateguard.yml` and a CI test step.

## B. Token bucket

3. **Token bucket: pass.** `acquire()` refills under a lock, may reserve future
   capacity by letting `_tokens` go negative, then sleeps outside the lock.
   This avoids busy-waiting and preserves concurrency. A 5-thread probe with
   `rate_per_sec=20`, `burst=1` produced completions spaced roughly 0.05s apart
   after the first immediate token. Burst behavior is covered by tests.

## C. Gateway retry / 403 / 429

4. **Retry policy: fail due to blocker above.** `403` raises immediately and is
   not retried. `5xx` and transport errors retry; 2xx/3xx/404/other 4xx return
   as-is. Retry counting is correct: `max_retries=1` gives one retry after the
   first failed attempt, and backoff indexing is bounded with `min(...)`.
   However, 429/503 global pause is not respected by the current retry loop.
5. **Pause cap: pass with caveat.** `_respect_pause()` caps a wait at 120s, so a
   paused upstream cannot wedge a request forever. The cap is reasonable, but
   because `_respect_pause()` is only called before `_request_with_retry()`, it
   currently protects future fetch calls rather than the retry that caused the
   pause.
6. **Token per attempt: pass.** The bucket is acquired inside the retry loop, so
   retries consume additional tokens. That is the right accounting because each
   attempt is an upstream request.

## D. Host allowlist

7. **Host allowlist: pass for arbitrary-host SSRF/open-proxy boundary.** The
   code derives `hostname` with `urlparse(url).hostname`, lowercases it, and
   compares exact hostnames against each upstream's `allowed_hosts`.
   Probe results:
   - `https://www.sec.gov@evil.com/x` rejected as host `evil.com`.
   - `www.sec.gov/x`, empty string, and garbage strings rejected with empty
     host.
   - `https://www.sec.gov.evil.com/x` rejected.
   - `HTTPS://WWW.SEC.GOV/x` allowed after hostname normalization. This differs
     from the prompt's literal "uppercase rejected" wording, but it is safe:
     DNS hostnames are case-insensitive and the normalized host is an allowed
     SEC host.
   Additional hardening note: scheme is not restricted. `http://www.sec.gov/x`
   passes the allowlist, and a mock transport also accepted `ftp://www.sec.gov/x`
   because host validation does not check scheme. This does not allow arbitrary
   hosts, but the service should probably require `scheme == "https"` for all
   current upstreams.
8. **Method allowlist: advisory.** The caller-supplied method is passed through
   to `httpx`. Because Rate Guard is intended as an internal service and hosts
   are fixed to read-oriented APIs, this is not a PR-1 blocker. Still, limiting
   methods to `GET` and `POST` would reduce the blast radius and match the
   cache/key semantics.

## E. Response cache

9. **Cache correctness: pass.** Key includes `(upstream, method, url, body)`.
   Only `200` responses are cached by `Gateway`. Writes use temp file plus
   `replace()`, and reads check TTL. Missing/corrupt JSON/OSError degrades to a
   miss.
10. **POST and TTL policy: pass with advisory.** Caching POST by body is suitable
    for OpenFIGI map calls. EDGAR `/Archives/` long TTL is appropriate for
    immutable filing artifacts. The default 1h TTL for non-archive EDGAR listing
    endpoints is acceptable for PR 1; if operators need immediate index
    freshness, integration PRs can disable/bypass cache for those listing URLs.

## F. Config

11. **SEC User-Agent fallback: advisory, leaning fix-before-integration.**
    `_sec_user_agent()` falls back to `"ValuePilot contact-not-configured"`.
    Existing backend EDGAR client fails loud when `SEC_CONTACT_EMAIL` is absent,
    and local `.env` currently lacks `SEC_CONTACT_EMAIL`. Rate Guard should
    ideally fail at startup, or at least mark EDGAR unavailable, when the EDGAR
    upstream is enabled without a real contact email. I would not block PR 1 on
    this if the retry blocker is fixed, but it should be addressed before PRs
    2-4 route production EDGAR traffic through this service.
12. **Rate defaults: pass.** EDGAR 8 rps is below the common SEC 10 rps limit.
    OpenFIGI 4 rps with key and 0.4 rps without key are reasonable relative to
    the documented minute quotas and leave headroom.

## G. Service / compose / CI

13. **Compose topology: pass.** `docker-compose.rateguard.yml` defines one
    shared instance on `projects-shared` with a bind-mounted cache. That matches
    the topology needed to avoid two independent limiters. Local `.env` does
    not currently include `SEC_CONTACT_EMAIL` or `OPENFIGI_API_KEY`, so prod
    deploy env should be checked before integration.
14. **Service runtime/thread-safety: pass.** Dockerfile uses exec-form `CMD`, so
    uvicorn is PID 1. FastAPI sync handlers will run in a threadpool; buckets
    and metrics use locks, cache writes are atomic, and a shared `httpx.Client`
    is acceptable for concurrent use.
15. **CI wiring: pass.** `.github/workflows/ci.yml` adds a `Run Rate Guard tests`
    step that `cd`s into `rate-guard`, installs `requirements-dev.txt`, and
    runs `pytest -q`.

## H. Tests

16. **Test coverage: adequate for PR 1 except the blocker path.** Existing tests
    cover bucket basics, cache miss/hit/TTL/keying, host rejection, cache hit,
    403 no-retry, 5xx retry success/exhaustion, and metrics. Material missing:
    429/503 global-pause behavior, `_respect_pause()`, concurrent bucket
    behavior as an automated test, and FastAPI route tests for `/v1/fetch`,
    `/v1/metrics`, `/healthz`. The 429/503 global-pause test should be added
    with the blocker fix; the route tests can be added soon but are not the main
    safety boundary.

## Verification run

- `docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim sh -lc
  'pip install -r requirements-dev.txt && pytest -q'` — passed, 14 tests.
- Host allowlist probe — arbitrary-host cases rejected; uppercase allowed host
  normalized and accepted; scheme is not restricted.
- Token bucket concurrency probe — passed, concurrent calls spaced by rate.
- `docker compose -f docker-compose.rateguard.yml up -d --build` — service
  built and started.
- Container-internal checks:
  - `/healthz` — 200, returned upstreams `edgar`, `openfigi`, `dataroma`.
  - `/v1/metrics` — 200, returned per-upstream budgets/cache counters.
- `docker compose -f docker-compose.rateguard.yml down` — cleanup completed.

## Second-review verification

- `docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim sh -lc
  'pip install -q -r requirements-dev.txt && pytest -q'` — passed, 16 tests.
- 429 pause probe with `pause_s=0.3` and zero backoff — passed; second attempt
  occurred about 0.304s after the first.
- Host/scheme allowlist probe — passed. Userinfo host injection, fake suffix
  host, no-scheme URL, empty/garbage URL, `ftp`, and `http` were rejected.
  Uppercase legitimate HTTPS SEC URL normalized and was allowed.
- `docker compose -f docker-compose.rateguard.yml up -d --build` with current
  local `.env` — failed loudly as expected because `SEC_CONTACT_EMAIL` is
  missing.
- `docker compose -f docker-compose.rateguard.yml run --rm --service-ports -e
  SEC_CONTACT_EMAIL=review@example.com rate-guard` — started successfully.
  Container-internal `/healthz` and `/v1/metrics` returned 200. Temporary
  container stopped cleanly.

## Remaining advisory notes

- `docker-compose.rateguard.yml` now requires the deploy/local env to provide
  `SEC_CONTACT_EMAIL`. That is the right fail-loud behavior, but the runbook or
  environment setup should make the prerequisite explicit before integration.
- `method` remains unrestricted. It is acceptable for PR 1 because hosts are
  allowlisted and the service is internal, but future integration can reduce
  blast radius by allowing only `GET` and `POST`.
- FastAPI route tests and an automated concurrent-bucket test would still be
  useful follow-ups; the main safety boundary is now covered.
