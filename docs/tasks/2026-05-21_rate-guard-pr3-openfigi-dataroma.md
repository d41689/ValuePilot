# 2026-05-21 — Rate Guard PR 3/4: repoint OpenFigiClient + DataromaClient

Design: `docs/tasks/2026-05-20_rate-guard-design.md` §7, §10 (PR 3).
Branch: `claude/rate-guard-pr3-openfigi-dataroma`.

## Goal / Acceptance Criteria

- `OpenFigiClient` and `DataromaClient` fetch through the Rate Guard egress
  service instead of calling the upstream directly — Rate Guard owns rate
  limiting, retry, and the API key / browser User-Agent.
- Public APIs unchanged so the call sites (`cusip_enrichment.py`,
  `edgar_ingestion.py`) need no edits.
- Canonical CI (backend + Rate Guard suites) stays green.

## Decision — shared `RateGuardClient` (confirmed with PO 2026-05-21)

A new `backend/app/rate_guard/client.py` holds `RateGuardClient` +
`RateGuardFetchError` — the `EdgarClient._fetch` logic generalised (an
`upstream` parameter, optional request `body`). `OpenFigiClient` and
`DataromaClient` become thin wrappers over it. `EdgarClient` is **left as-is**
this PR; migrating it onto the shared client is recorded in `docs/BACKLOG.md`.

## Scope

In:
- `backend/app/rate_guard/client.py` (new) — `RateGuardClient.fetch(upstream,
  method, url, body=b"")` → upstream body, or raises `RateGuardFetchError`
  (carries `.status_code`, subclasses `RuntimeError`).
- `backend/app/openfigi/client.py` — `map_cusips` routes through Rate Guard
  (`upstream="openfigi"`, POST, JSON body); drop the in-process throttle and
  the `api_key` constructor arg (Rate Guard injects the OpenFIGI key). The stub
  path is kept for `use_stub` / replay mode.
- `backend/app/dataroma/client.py` — `get` routes through Rate Guard
  (`upstream="dataroma"`, GET); drop the in-process throttle / retry / backoff.
- `rate-guard/app/config.py` — the `openfigi` upstream `extra_headers` gains
  `Content-Type: application/json`. OpenFIGI's `/v3/mapping` requires it (the
  old client sent it); Rate Guard forwards the raw body with `content=`, which
  sets no content type, so Rate Guard must inject it.
- New tests: `test_rate_guard_client.py`, `test_openfigi_client.py`,
  `test_dataroma_client.py`.

Out:
- Migrating `EdgarClient` onto `RateGuardClient` — `docs/BACKLOG.md` follow-up.
- Admin panel onto Rate Guard `/v1/metrics` — PR 4/4.
- Unused `DATAROMA_*` / `OPENFIGI_API_KEY` settings left in `backend` config
  (a later cleanup), consistent with PR 2/4 leaving the EDGAR retry settings.

## Behaviour notes

- `RateGuardClient.fetch` mirrors `EdgarClient._fetch` (the post-review final
  version): unreachable / non-200-non-502 / malformed envelope → typed error
  with `status_code=None`; Rate Guard 502 and upstream non-200 → typed error
  carrying the upstream status. It does **not** record per-request metrics —
  `edgar_rate_limit_status()` stays EDGAR-specific in `edgar/client.py`.
- The live-mode startup guard from PR 2/4 already covers the whole app; PR 3
  needs no new guard. `RateGuardClient._endpoint()` raising on an unset
  `RATE_GUARD_URL` is the second line of defence.
- `OpenFigiClient` stub: `use_stub or EDGAR_FETCH_MODE == "replay"` — replay is
  now hermetic for OpenFIGI (the old code also required no key); tests mock the
  whole client so this is behaviour-only.

## Test plan

- `docker compose run --rm --no-deps api pytest -q` — backend suite green.
- `docker run … rate-guard … pytest -q` — Rate Guard suite green (config-only
  change).
- New tests cover `RateGuardClient` (routing payload, body passthrough,
  success, upstream non-200, 502, unreachable, malformed envelope), and the two
  thin clients (routing + OpenFIGI payload/stub/result parsing).

## Review remediation (2026-05-21)

Two independent reviews. Both converged on the **C6 lifecycle** finding (one
rated it advisory + approved, one rated it P1 + request-changes); A / B / D / E
/ F / G otherwise PASS. Fixed:

- **C6 — close the self-constructed `OpenFigiClient`.** The new client holds a
  persistent `httpx.Client`; `enrich_unmapped_holdings` self-constructed an
  `OpenFigiClient` and never closed it. `cusip_enrichment.py` now tracks
  `owns_client = client is None` and closes it in a `finally` — an injected
  client is left for the caller to manage.
- **G11 — the missing test.** `test_13f_cusip_enrichment.py` gains
  `test_enrich_closes_a_self_constructed_client` and
  `test_enrich_does_not_close_an_injected_client`, locking both paths.

Re-verified: backend `pytest -q` green; Rate Guard `pytest -q` green.
