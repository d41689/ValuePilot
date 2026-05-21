# 2026-05-21 — Rate Guard PR 2/4: repoint EdgarClient

Design: `docs/tasks/2026-05-20_rate-guard-design.md` §7, §10 (PR 2).
Branch: `claude/rate-guard-pr2-edgar-client`.

## Goal / Acceptance Criteria

- `EdgarClient` fetches EDGAR through the Rate Guard egress service instead of
  calling SEC directly — Rate Guard owns rate limiting, retry, and the 429/503
  global pause.
- Live-mode safety: `EDGAR_FETCH_MODE=live` with no `RATE_GUARD_URL` is a hard
  startup error — live EDGAR access without the guard is not allowed.
- `EdgarClient`'s public API (`get` / `head` / `close` / context manager /
  `BASE` constants) is unchanged, so the 8 call sites need no edits.
- Canonical CI stays green.

## Decision — EdgarClient shape (confirmed with PO 2026-05-21)

**Route-all-through-Rate-Guard (slim).** `EdgarClient` always fetches via
Rate Guard `POST /v1/fetch`. The in-process `_TokenBucket`, retry loop, and
`_GLOBAL_PAUSE_UNTIL` are deleted (Rate Guard owns them). If `RATE_GUARD_URL`
is unset, `get()` / `head()` raise a clear config error — there is no
un-rate-limited direct-to-SEC path. Replay mode never fetches; tests inject
fakes or a mocked Rate Guard.

## Scope

In:
- `backend/app/core/config.py` — add `RATE_GUARD_URL`.
- `backend/app/edgar/client.py` — rewrite: thin pass-through to Rate Guard;
  delete the token bucket / retry / global-pause machinery and
  `build_sec_user_agent` (Rate Guard sets the SEC User-Agent now).
- `backend/app/main.py` — live-mode startup guard in `lifespan`.
- `backend/tests/conftest.py` — set a placeholder `RATE_GUARD_URL` before app
  import so the live-mode guard is satisfied (the `client` fixture runs
  `lifespan` via `with TestClient(app)`). `EDGAR_FETCH_MODE` is left at its
  default `live` so `fetch_and_store` keeps using the injected fake clients
  rather than the replay-from-DB path.
- `.github/workflows/ci.yml` — CI `.env` gets the same placeholder
  `RATE_GUARD_URL` so the api container starts (its `lifespan` runs the guard).
- `backend/tests/unit/test_edgar_client.py` — rewrite for Rate Guard routing.

Out:
- `OpenFigiClient` / `DataromaClient` — PR 3/4.
- Admin `edgar-rate-limit` panel reading Rate Guard `/v1/metrics` — PR 4/4.
  This PR keeps `edgar_rate_limit_status()` working (admin panel + the 13F
  403/429 alerting both read it); it is populated from the upstream statuses
  Rate Guard reports back per fetch. `global_pause_until` goes to `None` (the
  real pause now lives in Rate Guard) until PR 4 wires the panel to it.
- Safer Rate Guard deploy rollout (`docs/BACKLOG.md`) — deploy-script work,
  kept as a separate focused follow-up rather than bundled into this app-code
  PR.

## Behaviour notes

- `EdgarClient._fetch` POSTs `{upstream:"edgar", method, url}`; Rate Guard
  returns `200 {status, body_b64, …}` (`status` = the upstream status) or
  `502 {detail:{upstream_status, detail}}` (403 / retries exhausted). `get()`
  returns the decoded body only for upstream `200`; any other upstream status,
  a 502, or an unreachable Rate Guard raises `RuntimeError` — matching the
  pre-Rate-Guard client's "raises on non-200" contract.
- `/v1/fetch` can block while Rate Guard works through its own retry + 60s
  global pause, so the EdgarClient→RateGuard HTTP timeout is large (1800s).

## Test plan

- `docker compose run --rm --no-deps api pytest -q` — full suite green.
- New `test_edgar_client.py` covers: GET/HEAD routing payload, decoded body,
  unset `RATE_GUARD_URL` → raise (no fetch), upstream non-200 → raise, Rate
  Guard 502 → raise, Rate Guard unreachable → raise, 403 recorded for the
  health summary.
- Frontend untouched.

## Review remediation (2026-05-21)

Independent review (`2026-05-21_rate-guard-pr2-edgar-client-review-result.md`)
verdict was **not approved** — one P1 blocker plus two advisories. All three are
fixed in this PR (none deferred — they share the same files and root cause):

- **B3 (P1) — daily index sync 404 handling.** The rewrite flattened every EDGAR
  failure to a bare `RuntimeError`, discarding the upstream status, while
  `run_daily_index_sync` catches `httpx.HTTPStatusError` to classify a 404 — so
  expected no-index (weekend / holiday) 404s would have been marked `"failed"`
  instead of `"no_data"`. Fix: `EdgarClient` raises a typed
  `EdgarFetchError(RuntimeError)` carrying `.status_code`; `_fetch` raises it on
  every failure path; `thirteenf_daily_sync.py` catches `EdgarFetchError` and
  reads `.status_code`. `EdgarFetchError` subclasses `RuntimeError`, so the
  broad-`except` call sites are unaffected.
- **E10 (advisory) — uniform error contract.** `_fetch` now wraps `resp.json()`
  and checks the payload shape, so a malformed Rate Guard 200 raises
  `EdgarFetchError`, not a stray `ValueError`.
- **G14 (advisory) — tests lock the contract.** `test_edgar_client.py` asserts
  `EdgarFetchError` and the recovered `.status_code` (404 / 403 / None).

The `test_13f_daily_index_sync.py` `FakeEdgarClient` now raises `EdgarFetchError`
(it previously raised `httpx.HTTPStatusError`, which masked B3) — so the
existing `test_expected_no_index_404_marks_sync_no_data` /
`test_unexpected_404_marks_sync_failed_for_retry` are now genuine regression
guards.
