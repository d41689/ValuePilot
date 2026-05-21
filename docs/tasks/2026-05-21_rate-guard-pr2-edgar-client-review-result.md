# Review result — Rate Guard PR 2/4: repoint EdgarClient (PR #80)

Date: 2026-05-21
Branch reviewed: `claude/rate-guard-pr2-edgar-client`
Prompt: `docs/tasks/2026-05-21_rate-guard-pr2-edgar-client-review-prompts.md`

## Verdict

**批准 / approved**, with non-blocking follow-ups.

The previous B3 blocker is fixed in the current branch: EDGAR failures now
raise `EdgarFetchError(RuntimeError)` with a recoverable `.status_code`, and
`run_daily_index_sync` catches that typed exception for expected 404/no-index
dates. The load-bearing pass-through is otherwise complete: no in-process EDGAR
rate limiter/retry/global-pause logic remains, live mode hard-requires
`RATE_GUARD_URL`, the CI/test seam keeps `EDGAR_FETCH_MODE=live`, and the full
backend suite is green.

No blocking findings.

## Per-question findings

### A. Design conformance / slim

- **A1 — PASS.** `backend/app/edgar/client.py:1-8` documents the Rate Guard
  pass-through, `client.py:119-167` sends every fetch as `POST /v1/fetch`, and
  the old token bucket / `_GLOBAL_PAUSE_UNTIL` / retry loop / SEC User-Agent
  construction are gone.
- **A2 — PASS.** Public API surface remains: `BASE`, `EFTS_BASE`, `DATA_BASE`
  at `client.py:103-105`; constructor, `get`, `head`, `close`, context manager
  at `client.py:107-184`. The eight direct `EdgarClient()` call sites in
  `edgar_ingestion.py` and `thirteenf_admin_dashboard.py` still compile without
  edits.

### B. Exception-behaviour parity

- **B3 — PASS.** The old `httpx.HTTPStatusError`-aware daily sync path is now
  explicitly migrated: `thirteenf_daily_sync.py:65-66` catches
  `EdgarFetchError`, and `_handle_http_error` reads `.status_code` at
  `thirteenf_daily_sync.py:210-220`. The test fake now mirrors the real client
  by raising `EdgarFetchError(status_code=...)` at
  `test_13f_daily_index_sync.py:26-40`, preserving the expected 404/no-data
  behavior. Grep found no remaining application `except httpx.HTTPStatusError`
  paths.
- **B4 — PASS.** `head()` delegates to `_fetch("HEAD", url)` at
  `client.py:173-175`. A Rate Guard 200 with empty `body_b64` returns cleanly
  through `base64.b64decode(payload.get("body_b64") or "")`; upstream 404s
  raise `EdgarFetchError(status_code=404)`.

### C. Live-mode startup guard

- **C5 — PASS.** `app/main.py:19-24` raises before `yield` when
  `EDGAR_FETCH_MODE == "live"` and `RATE_GUARD_URL` is empty, which aborts ASGI
  lifespan startup. `EdgarClient._fetch_endpoint` is a second guard at
  `client.py:110-117`, so live EDGAR fetches cannot silently bypass Rate Guard.
- **C6 — PASS.** Both guard sites use `(settings.RATE_GUARD_URL or "").strip()`
  (`main.py:19`, `client.py:111`), covering unset, empty, and whitespace-only
  values.

### D. Test & CI seam

- **D7 — PASS.** `backend/tests/conftest.py:1-9` sets
  `RATE_GUARD_URL=http://rate-guard.invalid` before importing the app and leaves
  `EDGAR_FETCH_MODE` at its default `live`, so `fetch_and_store` continues to
  use injected fake clients instead of replay mode.
- **D8 — PASS.** `.github/workflows/ci.yml:36-42` writes the same placeholder
  `RATE_GUARD_URL` into CI `.env`. The dev compose defaults keep scheduler and
  job worker off in an idle CI api container, so startup satisfies the guard
  without dialing the placeholder URL.
- **D9 — PASS.** `test_edgar_client.py` uses `httpx.MockTransport`
  (`test_edgar_client.py:20-22`), and the other affected backend tests inject
  fake clients. No test requires a real Rate Guard process.

### E. `_fetch` robustness

- **E10 — advisory.** The structured 502 error unwrap is safe for malformed
  JSON/body shapes (`client.py:90-97`), and non-JSON 200 responses are wrapped
  as `EdgarFetchError` (`client.py:150-156`). Two malformed-success edges still
  leak lower-level exceptions: `int(payload.get("status", 0))` at
  `client.py:160` can raise `ValueError`/`TypeError`, and invalid base64 at
  `client.py:167` can raise a decode error. This is not a blocker because Rate
  Guard owns that envelope, but wrapping both in `EdgarFetchError` would make
  the client contract cleaner.
- **E11 — PASS.** `_RATE_GUARD_TIMEOUT_S = 1800.0` (`client.py:29-31`) is sane
  for Rate Guard's retry/backoff + global pause worst case and avoids cutting
  off long EDGAR retries prematurely.
- **E12 — PASS.** `edgar_rate_limit_status()` remains at `client.py:55-87`;
  `_fetch` records upstream statuses at `client.py:139`, `client.py:145`, and
  `client.py:160-161`. The admin panel / scheduler alerting still get recent
  403/429 counts, while `global_pause_until` is intentionally `None` until PR 4.

### F. Intentional deferrals

- **F13 — PASS.** `OpenFigiClient` / `DataromaClient` are untouched, the admin
  panel still reads `edgar_rate_limit_status()`, and legacy EDGAR retry/rate
  settings remain in `config.py` for compatibility until later cleanup.

### G. Tests

- **G14 — PASS.** `backend/tests/unit/test_edgar_client.py` covers routing
  payload, HEAD method, unset `RATE_GUARD_URL`, upstream non-200 with status,
  Rate Guard 502 with upstream status, unreachable Rate Guard, request-status
  recording, and the `RuntimeError` subclass contract. Material remaining gap:
  malformed success envelopes from Rate Guard are only partially covered; see
  E10.
- **G15 — PASS.** The removed admin-dashboard tests targeted deleted local
  global-pause behavior (`_GLOBAL_PAUSE_UNTIL`) now owned by Rate Guard. The
  remaining request-count/status behavior is still covered in
  `test_13f_admin_dashboard.py` and `test_edgar_client.py`.

## Verification

- `docker compose run --rm --no-deps api pytest -q` — **passed**:
  `871 passed, 3 warnings in 51.35s`.
- `git diff origin/main...HEAD` — scope matches the prompt; no DB migration.
- Frontend application code is untouched.

## Non-blocking follow-ups

- **Task doc drift:** `docs/tasks/2026-05-21_rate-guard-pr2-edgar-client.md:34-38`
  still says `conftest.py` / CI force `EDGAR_FETCH_MODE=replay`; current code
  correctly uses placeholder `RATE_GUARD_URL` and leaves live mode on. Update
  those lines so the task doc matches the final test/CI seam.
- **Malformed Rate Guard success envelope:** wrap invalid `status` and invalid
  `body_b64` failures in `EdgarFetchError` for a fully uniform client error
  contract.
