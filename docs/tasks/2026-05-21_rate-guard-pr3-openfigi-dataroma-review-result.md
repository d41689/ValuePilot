# Review result — Rate Guard PR 3/4: OpenFIGI + Dataroma repoint

Branch: `claude/rate-guard-pr3-openfigi-dataroma`  
Baseline: `git diff main...HEAD`  
Reviewer verdict: **FAIL / request changes**

The repoint is mostly behavior-preserving, but the mandatory lifecycle check
does not pass: `enrich_unmapped_holdings` self-constructs an `OpenFigiClient`
and never closes it, while the new client owns a persistent `httpx.Client`.
This should be fixed before auto-deploy.

## Must Fix

1. **[P1] Close self-constructed `OpenFigiClient` in `enrich_unmapped_holdings`.**
   The new `OpenFigiClient.__init__` eagerly creates `RateGuardClient`, which
   creates or owns an `httpx.Client` (`backend/app/openfigi/client.py:24-28`,
   `backend/app/rate_guard/client.py:55-56`). The client exposes `close()` and a
   context manager (`backend/app/openfigi/client.py:69-76`), but
   `enrich_unmapped_holdings` constructs `OpenFigiClient()` when no dependency is
   injected and calls `client.map_cusips(...)` without a `finally` close
   (`backend/app/services/cusip_enrichment.py:186-220`). The old implementation
   opened `httpx.Client` inside `map_cusips` with a `with` block and closed it
   per call (`main:backend/app/openfigi/client.py:52-56`). Add ownership-aware
   cleanup, e.g. track `owns_client = client is None`, then close in `finally`.
   Severity: **P1 for this PR's pass bar** (mandatory C6); operationally this is
   a resource leak across repeated enrichment jobs.

## Prompt Checklist

### A. Shared `RateGuardClient`

1. **PASS.** `RateGuardClient.fetch` builds `/v1/fetch` payload with
   `upstream`, `method`, `url`, and optional `body_b64`
   (`backend/app/rate_guard/client.py:75-80`); decodes 200 envelopes
   (`backend/app/rate_guard/client.py:103-125`); maps 502 detail
   `upstream_status` onto `RateGuardFetchError.status_code`
   (`backend/app/rate_guard/client.py:87-98`); maps non-200-non-502,
   unreachable, malformed envelope, and upstream non-200 to
   `RateGuardFetchError` with the expected status semantics
   (`backend/app/rate_guard/client.py:81-128`). This matches the post-PR2
   `EdgarClient._fetch` behavior minus EDGAR-specific metrics
   (`backend/app/edgar/client.py:119-178`).
2. **PASS.** The new `OpenFigiClient` and `DataromaClient` have no local
   throttle, retry loop, backoff, or `_parse_backoff`; they only build the
   upstream call and delegate to `RateGuardClient`
   (`backend/app/openfigi/client.py:30-47`, `backend/app/dataroma/client.py:20-27`).

### B. Behavior Parity

3. **PASS.** `RateGuardFetchError` subclasses `RuntimeError`
   (`backend/app/rate_guard/client.py:24-35`). `bootstrap_whitelist` uses
   `DataromaClient` in a context manager and lets failures propagate
   (`backend/app/services/edgar_ingestion.py:206-214`), so no exact exception
   type dependency was found.
4. **PASS.** `enrich_unmapped_holdings` does not catch a specific exception type
   around `map_cusips`; the call is outside the later persistence `try/except`
   (`backend/app/services/cusip_enrichment.py:217-239`). The change from
   `httpx.HTTPStatusError` to `RateGuardFetchError` should propagate similarly.
5. **PASS.** Public construction at call sites is unchanged:
   `OpenFigiClient()` in `cusip_enrichment.py`
   (`backend/app/services/cusip_enrichment.py:217-218`) and `DataromaClient()`
   in `edgar_ingestion.py` (`backend/app/services/edgar_ingestion.py:211`).
   Repo search found no `OpenFigiClient(api_key=...)` construction. The
   constructor now takes `use_stub` and `http_client`
   (`backend/app/openfigi/client.py:24-28`), and Dataroma accepts `http_client`
   (`backend/app/dataroma/client.py:17-18`).

### C. `OpenFigiClient` Lifecycle

6. **FAIL.** See must-fix item above. The new client lifecycle is not sound for
   self-constructed clients in `enrich_unmapped_holdings`.

### D. OpenFIGI `Content-Type`

7. **PASS.** `rate-guard/app/config.py` injects
   `Content-Type: application/json` in both keyed and keyless OpenFIGI branches
   (`rate-guard/app/config.py:87-94`). Rate Guard forwards bytes with
   `httpx.Client.request(..., content=body or None, headers=...)`
   (`rate-guard/app/gateway.py:115-117`), so config injection is the correct
   place for the header. The old client sent `Content-Type` directly
   (`main:backend/app/openfigi/client.py:45-54`). OpenFIGI docs also show the
   mapping request with `Content-Type: application/json` and document 415 for
   invalid content type: https://www.openfigi.com/api/documentation.

### E. Request-Body Passthrough

8. **PASS.** `body_b64` is emitted only for non-empty request bodies
   (`backend/app/rate_guard/client.py:75-79`); Rate Guard accepts optional
   `body_b64` and decodes it before forwarding (`rate-guard/app/main.py:28-47`).
   OpenFIGI JSON bodies are encoded by the client
   (`backend/app/openfigi/client.py:39-43`) and covered in tests
   (`backend/tests/unit/test_openfigi_client.py:48-55`). Dataroma GETs send no
   body (`backend/app/dataroma/client.py:20-27`), covered by
   `test_get_routes_payload_through_rate_guard`
   (`backend/tests/unit/test_rate_guard_client.py:52-57`).

### F. Stub Mode & Scope

9. **PASS.** Stub mode is `use_stub or EDGAR_FETCH_MODE == "replay"`
   (`backend/app/openfigi/client.py:35-37`) and returns deterministic local
   mappings (`backend/app/openfigi/client.py:49-67`). Tests assert both explicit
   stub and replay skip Rate Guard (`backend/tests/unit/test_openfigi_client.py:60-88`).
   The replay change is acceptable because replay should be hermetic.
10. **PASS.** Deferrals are deliberate: the task doc scopes Edgar migration out
   (`docs/tasks/2026-05-21_rate-guard-pr3-openfigi-dataroma.md:42-46`) and the
   backlog records the shared-client follow-up (`docs/BACKLOG.md:28-42`). Unused
   backend settings remain in `backend/app/core/config.py:69-74`.

### G. Tests

11. **PASS with advisory gaps.** New coverage is solid for shared client
   payloads, success, 502, upstream non-200, Rate Guard faults, unreachable, and
   malformed envelopes (`backend/tests/unit/test_rate_guard_client.py:36-164`).
   OpenFIGI tests cover routing, request body, result parsing, stub, and replay
   (`backend/tests/unit/test_openfigi_client.py:32-88`). Dataroma tests cover
   holdings and managers URL routing (`backend/tests/unit/test_dataroma_client.py:31-60`).
   Material gap: no test catches the self-owned `OpenFigiClient` close path in
   `enrich_unmapped_holdings`, which is the failing issue above. Existing
   `test_13f_cusip_enrichment.py` only patches `OpenFigiClient` without
   constructor args (`backend/tests/unit/test_13f_cusip_enrichment.py:131-139`),
   so the dropped `api_key` arg does not break it.

## Verification

- `docker compose run --rm --no-deps api pytest -q` — **PASS**:
  `887 passed, 3 warnings in 55.07s`.
- `docker compose run --rm --no-deps -v /Users/huawang/projects/ValuePilot/rate-guard:/rate-guard api sh -lc 'cd /rate-guard && pytest -q'` — **PASS**:
  `19 passed in 1.62s`.

I used the API container for the Rate Guard pytest run to avoid installing
Python dependencies on the host, while still executing the Rate Guard test
suite against the branch source.
