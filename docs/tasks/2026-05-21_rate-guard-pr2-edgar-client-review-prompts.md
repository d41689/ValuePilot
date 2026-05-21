# Review prompt — Rate Guard PR 2/4: repoint EdgarClient (PR #80)

Paste this into a fresh reviewer session (human or agent). It is self-contained.
Pair it with `docs/tasks/2026-05-21_rate-guard-pr2-edgar-client.md` (task doc)
and `docs/tasks/2026-05-20_rate-guard-design.md` §7 / §10 (design).

## Reviewer brief

You are reviewing **PR #80**, branch `claude/rate-guard-pr2-edgar-client` —
**Rate Guard PR 2/4**. It repoints `EdgarClient` so every EDGAR fetch goes
through the Rate Guard egress service (`POST /v1/fetch`) instead of calling SEC
directly. Rate Guard (shipped in #76/#78, deploy-integrated in #79) is the
single shared rate limiter; this is the first client wired to it.

This is **prod-auto-deploying backend code** (a self-hosted runner deploys every
`main` push) that **rewrites a core HTTP client** and **deletes** its in-process
rate limiter, retry loop, and 429/503 global pause. Review it as a
behaviour-preserving rewrite of a load-bearing component, with particular
attention to: (1) the live-mode startup guard, (2) exception-behaviour parity
for the 8 call sites, (3) the test/CI seam.

Three review lenses — one agent may cover all: **security** (egress
containment / the guard), **backend** (the rewrite / exception parity / call
sites), **test & release engineering** (the conftest + `ci.yml` seam).

### Files in scope
- `backend/app/edgar/client.py` — rewritten (the slim pass-through)
- `backend/app/core/config.py` — `RATE_GUARD_URL`
- `backend/app/main.py` — `lifespan` startup guard
- `backend/tests/conftest.py`, `.github/workflows/ci.yml` — the test/CI seam
- `backend/tests/unit/test_edgar_client.py` — rewritten
- `backend/tests/unit/test_13f_admin_dashboard.py` — two removed tests
- `docs/tasks/2026-05-20_rate-guard-design.md` — build-log entry
- `docs/tasks/2026-05-21_rate-guard-pr2-edgar-client.md` — task doc

### Baseline
`git diff main...HEAD`.

## Answer each question with a verdict (PASS / FAIL / advisory) + file:line evidence

### A. Design conformance / is the slim complete
1. `EdgarClient` routes every `get()` / `head()` through Rate Guard
   `POST /v1/fetch`; the in-process token bucket, retry loop, and
   `_GLOBAL_PAUSE_UNTIL` are deleted. Confirm no rate-limiting or retry logic
   survives in `client.py`.
2. The public API (`get` / `head` / `close` / `__enter__` / `__exit__` /
   `BASE` / `EFTS_BASE` / `DATA_BASE`) is unchanged. Confirm the 8 `EdgarClient()`
   call sites (`edgar/fetcher.py`, `services/edgar_ingestion.py` ×4,
   `services/thirteenf_admin_dashboard.py` ×3) need no edits and still work.

### B. Exception-behaviour parity — MANDATORY (the rewrite risk)
3. The old `_request` raised `RuntimeError` on 403 and on retries-exhausted, and
   `raise_for_status()` (→ `httpx.HTTPStatusError`) on other non-200 (e.g. 404).
   The new `_fetch` raises `RuntimeError` for: a Rate Guard `502` (upstream 403 /
   exhausted), an upstream non-200, a non-200/non-502 from Rate Guard, and an
   unreachable Rate Guard. **Walk every call site that inspects an EDGAR
   failure** — especially the 404-aware paths (`edgar/fetcher.py`, the daily
   index sync's 404 handling). Confirm no caller depended on a specific
   exception *type* (e.g. `except httpx.HTTPStatusError`) that the rewrite no
   longer raises.
4. `head()` contract is "raises on any non-200 (e.g. 404)". Confirm a Rate Guard
   `200` with empty `body_b64` succeeds and a `404` raises.

### C. The live-mode startup guard — MANDATORY
5. `app/main.py` `lifespan` raises when `EDGAR_FETCH_MODE == "live"` and
   `RATE_GUARD_URL` is empty. Confirm it actually aborts uvicorn startup (a hard
   startup error, not a warning), and that there is no path that performs a live
   EDGAR fetch without `RATE_GUARD_URL` — `EdgarClient._fetch_endpoint` raising
   is the second line of defence; confirm it.
6. Confirm `(settings.RATE_GUARD_URL or "").strip()` correctly handles unset /
   blank / whitespace values.

### D. Test & CI seam — MANDATORY (subtle)
7. `conftest.py` sets a placeholder `RATE_GUARD_URL` *before any app import* —
   **not** `EDGAR_FETCH_MODE=replay`. Confirm the reasoning: the `client` fixture
   runs `lifespan` via `with TestClient(app)` so the guard must be satisfied;
   but forcing replay mode would make `fetch_and_store` read from the DB instead
   of using the **injected fake clients** the 13F ingestion tests provide, which
   breaks those tests. Confirm `EDGAR_FETCH_MODE` stays `live` for the test run.
8. `ci.yml` adds `RATE_GUARD_URL=http://rate-guard.invalid` to the CI `.env`.
   Confirm the api container starts in CI (its `lifespan` runs the guard) and
   that nothing in an idle CI api container actually dials that URL (the
   scheduler and job worker are off by default).
9. Confirm no test makes a real Rate Guard call — `test_edgar_client.py` uses
   `httpx.MockTransport`; everywhere else a `FakeEdgarClient` is injected.

### E. `_fetch` robustness
10. `_rate_guard_error_detail` unwraps the FastAPI 502 body shape
    `{"detail": {"upstream_status", "detail"}}`. Together with
    `base64.b64decode(... or "")` and `int(payload.get("status", 0))`, confirm
    these degrade safely on a malformed / partial Rate Guard response.
11. `_RATE_GUARD_TIMEOUT_S = 1800` — a single `/v1/fetch` can block while Rate
    Guard works through its own retry + 60s global pause. Is a 30-minute ceiling
    sane? (Rate Guard's `edgar` worst case ≈ 6 attempts × (≤120s pause +
    ≤300s backoff).)
12. `edgar_rate_limit_status()` is kept — the admin `edgar-rate-limit` panel and
    the 13F 403/429 alerting both read it; `_fetch` calls `_record_request` with
    the upstream status Rate Guard reports. Confirm the panel / alerting still
    get meaningful data, and that `global_pause_until` being always `None` (the
    real pause now lives in Rate Guard) is acknowledged for PR 4.

### F. Intentional deferrals
13. Confirm these are deliberate, not gaps: `OpenFigiClient` / `DataromaClient`
    untouched (PR 3/4); the admin panel still on `edgar_rate_limit_status()`
    rather than Rate Guard `/v1/metrics` (PR 4/4); unused EDGAR settings left in
    `config.py` (e.g. `EDGAR_RETRY_BACKOFF_S`).

### G. Tests
14. The rewritten `test_edgar_client.py` covers: routing payload, HEAD method,
    unset-`RATE_GUARD_URL` → raise (no fetch attempted), upstream non-200 →
    raise, Rate Guard 502 → raise, Rate Guard unreachable → raise, and the
    `_record_request` / `edgar_rate_limit_status` path. Note any material gap.
15. The two `test_13f_admin_dashboard.py` removals
    (`test_edgar_rate_limit_status_records_global_pause_after_429` and the
    `_GLOBAL_PAUSE_UNTIL` line) targeted deleted behaviour. Confirm the removal
    is correct and not a loss of still-relevant coverage.

## Verification
- `docker compose run --rm --no-deps api pytest -q` — expect all green (~870).
- `git diff main...HEAD` for scope; no DB migration expected (`RATE_GUARD_URL`
  is a settings field, not a column).
- Frontend is untouched.

## Pass bar
Approve only if: B3 (exception parity) holds for every call site; C5 (a real
hard startup error, no un-guarded live path); D7–D8 (the test/CI seam is sound,
CI green); the slim (A1) is complete; and E11's timeout is judged sane. F
(deferrals) and G (test coverage) are findings to record. The bar is "a
behaviour-preserving repoint of a load-bearing client onto Rate Guard, safe to
auto-deploy to prod."
