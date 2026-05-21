# Review prompt — Rate Guard PR 3/4: repoint OpenFigiClient + DataromaClient (PR #81)

Paste this into a fresh reviewer session (human or agent). It is self-contained.
Pair it with `docs/tasks/2026-05-21_rate-guard-pr3-openfigi-dataroma.md` (task
doc) and `docs/tasks/2026-05-20_rate-guard-design.md` §7 / §14 (design).

## Reviewer brief

You are reviewing **PR #81**, branch `claude/rate-guard-pr3-openfigi-dataroma` —
**Rate Guard PR 3/4**. It routes `OpenFigiClient` and `DataromaClient` through
the Rate Guard egress service via a new shared `RateGuardClient`, following the
`EdgarClient` repoint of PR 2/4 (#80, merged).

This is **prod-auto-deploying backend code** (a self-hosted runner deploys every
`main` push). It introduces a shared module and **rewrites two load-bearing HTTP
clients**, deleting their in-process throttle / retry. Review it as a
behaviour-preserving repoint plus a new shared abstraction, with particular
attention to (1) exception / behaviour parity for the call sites, (2) the
`OpenFigiClient` httpx-client lifecycle, and (3) the OpenFIGI `Content-Type`
change to the Rate Guard service config.

Three review lenses — one agent may cover all: **backend / Python** (the shared
client + the two rewrites + parity), **Rate Guard integration** (the `openfigi`
`Content-Type`, the `/v1/fetch` body contract), **test** (coverage — both
clients had next to no direct tests before).

### Files in scope
- `backend/app/rate_guard/__init__.py`, `backend/app/rate_guard/client.py` — new
- `backend/app/openfigi/client.py` — rewritten
- `backend/app/dataroma/client.py` — rewritten
- `rate-guard/app/config.py` — `openfigi` upstream `Content-Type`
- `backend/tests/unit/test_rate_guard_client.py`,
  `test_openfigi_client.py`, `test_dataroma_client.py` — new
- `docs/BACKLOG.md`, design build-log, task doc

### Baseline
`git diff main...HEAD`.

## Answer each question with a verdict (PASS / FAIL / advisory) + file:line evidence

### A. Shared `RateGuardClient` — correctness & slim
1. `RateGuardClient.fetch` faithfully generalises `EdgarClient._fetch` (the
   post-#80-review final version): the `/v1/fetch` payload (`upstream` /
   `method` / `url`, `body_b64` only when there is a body); a 200 envelope →
   decoded body; a Rate Guard `502` → `RateGuardFetchError` carrying the
   upstream status; non-200-non-502 / unreachable / malformed envelope →
   `RateGuardFetchError` with `status_code=None`; upstream non-200 →
   `RateGuardFetchError` carrying the upstream status.
2. The slim: `OpenFigiClient` / `DataromaClient` retain **no** in-process
   throttle, retry loop, backoff, or `_parse_backoff`. Confirm.

### B. Behaviour parity — MANDATORY (the rewrite risk)
3. `DataromaClient.get` — the old client raised a bare `RuntimeError` on
   failure; the new one raises `RateGuardFetchError` (a `RuntimeError`
   subclass). Its only caller, `bootstrap_whitelist` (`edgar_ingestion.py`),
   lets it propagate. Confirm parity — no caller depended on the exact type.
4. `OpenFigiClient.map_cusips` — the old client raised `httpx.HTTPStatusError`
   (via `raise_for_status()`); the new one raises `RateGuardFetchError`.
   Confirm `enrich_unmapped_holdings` (`cusip_enrichment.py`) does not catch a
   specific exception *type* around the `map_cusips` call.
5. Public API: `OpenFigiClient(use_stub=…, http_client=…)` — the old `api_key`
   constructor arg is **dropped** (Rate Guard injects the OpenFIGI key);
   `DataromaClient(http_client=…)`; the methods and context managers are
   preserved. Confirm the call sites (`cusip_enrichment.py`,
   `edgar_ingestion.py`) run unchanged and that nothing constructs
   `OpenFigiClient(api_key=…)`.

### C. `OpenFigiClient` httpx-client lifecycle — MANDATORY
6. The new `OpenFigiClient` creates a **persistent** `httpx.Client` (via
   `RateGuardClient`) in `__init__`; the old client opened and closed an
   `httpx.Client` *per `map_cusips` call*. `enrich_unmapped_holdings`
   self-constructs `OpenFigiClient()` when no client is injected and never
   calls `.close()`. Decide: is the httpx client leaked, and does
   `enrich_unmapped_holdings` need a `finally: client.close()` (or should the
   client be created lazily)? Rate the severity.

### D. The OpenFIGI `Content-Type` fix — MANDATORY
7. `rate-guard/app/config.py` — the `openfigi` upstream `extra_headers` now
   includes `Content-Type: application/json`. Confirm: OpenFIGI's `/v3/mapping`
   requires it (the old `OpenFigiClient` set it explicitly); Rate Guard's
   gateway forwards the request body with httpx `content=`, which sets no
   content type; and the header is present in **both** the keyed and keyless
   `extra_headers` branches. Without this, OpenFIGI POSTs via Rate Guard fail.

### E. Request-body passthrough
8. `RateGuardClient.fetch` base64-encodes `body` into `body_b64` only when it is
   non-empty; Rate Guard's `/v1/fetch` `FetchRequest.body_b64` is optional.
   Confirm the OpenFIGI JSON request body round-trips (client base64-encodes →
   Rate Guard decodes → raw bytes forwarded to OpenFIGI) and that GET callers
   (`DataromaClient`) send no `body_b64`.

### F. Stub mode & scope
9. `OpenFigiClient` stubs on `use_stub or EDGAR_FETCH_MODE == "replay"` (old:
   `use_stub or (not api_key and replay)`). Confirm the stub path touches no
   network, and that the behaviour change — replay mode now always stubs
   OpenFIGI regardless of key — is acceptable (replay should be hermetic).
10. Confirm the deferrals are deliberate: `EdgarClient` is untouched (a
    `docs/BACKLOG.md` follow-up migrates it onto `RateGuardClient`); unused
    `DATAROMA_*` / `OPENFIGI_API_KEY` backend settings are left in `config.py`.

### G. Tests
11. New `test_rate_guard_client.py` / `test_openfigi_client.py` /
    `test_dataroma_client.py` — `OpenFigiClient` and `DataromaClient` had next
    to no direct test coverage before. Assess coverage and note material gaps.
    Confirm `test_13f_cusip_enrichment.py` (which `@patch`es `OpenFigiClient`)
    is unaffected by the constructor change.

## Verification
- `docker compose run --rm --no-deps api pytest -q` — backend green (~887).
- `cd rate-guard && pip install -r requirements-dev.txt && pytest -q` — Rate
  Guard green (19).
- `git diff main...HEAD` for scope; no DB migration; frontend untouched.

## Pass bar
Approve only if: A1 (the shared client faithfully generalises the reviewed
`EdgarClient._fetch`); B3–B5 (parity holds, no call site broken); C6 (the
`OpenFigiClient` lifecycle is sound, or fixed); D7 (the `Content-Type` fix is
correct and in both config branches). E / F / G findings are recorded. The bar
is "a behaviour-preserving repoint of OpenFigiClient + DataromaClient onto a
shared Rate Guard client, safe to auto-deploy to prod."
