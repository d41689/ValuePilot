# Review result — Migrate EdgarClient onto the shared RateGuardClient

Date: 2026-05-21
Branch reviewed: `claude/migrate-edgar-client-rate-guard`
Baseline: `git diff main...HEAD`
Prompt: `docs/tasks/2026-05-21_migrate-edgar-client-rate-guard-review-prompts.md`

## Overall verdict

PASS. I did not find a blocker against auto-deploy. `EdgarClient` is now a thin
wrapper over `RateGuardClient`, the public `EdgarClient` API is preserved for
the existing call sites, `RateGuardFetchError` is a drop-in egress exception
with `.status_code`, and the daily-index expected/no-index 404 path remains
faithfully covered by a fake that raises the same exception type as production.

No code findings.

## Prompt checklist

### A. Behaviour parity

1. PASS. `EdgarClient.get()` delegates to
   `RateGuardClient.fetch(upstream="edgar", method="GET", url=url)` and
   returns the upstream body. `head()` delegates with `method="HEAD"` and
   ignores the returned body, preserving the prior "succeeds on 200, raises on
   non-200" behaviour. `RateGuardClient.fetch()` still returns decoded body on
   upstream 200 and raises `RateGuardFetchError` for upstream non-200, Rate Guard
   502/non-200, unreachable, malformed envelope, and undecodable body. Evidence:
   `backend/app/edgar/client.py:28-34`,
   `backend/app/rate_guard/client.py:67-129`,
   `backend/tests/unit/test_edgar_client.py:39-82`,
   `backend/tests/unit/test_rate_guard_client.py:96-159`.
2. PASS. The public API remains `get`, `head`, `close`, context manager methods,
   and the three host constants. The eight `EdgarClient()` call sites still use
   that API and need no edits: one non-`with` owner in `fetcher.py`, four in
   `edgar_ingestion.py`, and three in `thirteenf_admin_dashboard.py`. Evidence:
   `backend/app/edgar/client.py:18-43`,
   `backend/app/edgar/fetcher.py:88-95`,
   `backend/app/services/edgar_ingestion.py:364-370`,
   `backend/app/services/edgar_ingestion.py:454-461`,
   `backend/app/services/edgar_ingestion.py:632-655`,
   `backend/app/services/edgar_ingestion.py:702-710`,
   `backend/app/services/thirteenf_admin_dashboard.py:685-691`,
   `backend/app/services/thirteenf_admin_dashboard.py:941-942`,
   `backend/app/services/thirteenf_admin_dashboard.py:2940-2942`.
3. PASS. `EdgarClient.close()` delegates to `RateGuardClient.close()`, and
   `__exit__` calls `close()`. The non-`with` call site in `fetcher.py` owns the
   client when it constructs one and closes it in `finally`, so the PR-3 C6
   leak pattern is not reintroduced. Evidence:
   `backend/app/edgar/client.py:36-43`,
   `backend/app/rate_guard/client.py:175-182`,
   `backend/app/edgar/fetcher.py:88-95`.

### B. Exception unification

4. PASS. `EdgarFetchError` is gone from `backend/app`; `RateGuardFetchError` is
   the single egress error type. It subclasses `RuntimeError` and carries
   `.status_code`, so broad `except Exception` call sites still catch it and
   status-aware call sites can read the same field. Evidence:
   `backend/app/rate_guard/client.py:24-35`,
   `backend/app/services/edgar_ingestion.py:368-372`,
   `backend/app/services/thirteenf_daily_sync.py:65-66`,
   `backend/app/services/thirteenf_daily_sync.py:210-220`.
5. PASS. The B3 daily-index 404 path is intact. Production `EdgarClient` raises
   `RateGuardFetchError` through `RateGuardClient.fetch()` with
   `.status_code == 404` on upstream 404; `run_daily_index_sync()` catches that
   same type; `_handle_http_error()` classifies expected 404s as `no_data`; and
   `FakeEdgarClient` now raises `RateGuardFetchError`, keeping the tests faithful
   to production. Grep found no surviving `EdgarFetchError` references under
   `backend/app` or `backend/tests`. Evidence:
   `backend/app/rate_guard/client.py:119-123`,
   `backend/app/services/thirteenf_daily_sync.py:65-66`,
   `backend/app/services/thirteenf_daily_sync.py:210-220`,
   `backend/tests/unit/test_13f_daily_index_sync.py:26-42`,
   `backend/tests/unit/test_13f_daily_index_sync.py:186-216`.

### C. The deletion / slim

6. PASS. `_fetch`, `_fetch_endpoint`, `_rate_guard_error_detail`,
   `_RATE_GUARD_TIMEOUT_S`, `EdgarFetchError`, and the old direct `base64`,
   `logging`, and `settings` imports are removed from `edgar/client.py`; no
   deleted name dangles in backend code/tests. The retained `BASE`, `EFTS_BASE`,
   and `DATA_BASE` constants are now documentation/compatibility constants and
   are explicitly covered by a wrapper test. Evidence:
   `backend/app/edgar/client.py:13-43`,
   `backend/tests/unit/test_edgar_client.py:85-88`.

### D. Tests

7. PASS. `test_edgar_client.py` is correctly slimmed to wrapper behavior:
   GET routes as `upstream="edgar"`, HEAD routes as `upstream="edgar"`, upstream
   404 propagates with `.status_code`, and constants are preserved. The removed
   deep envelope/error-path coverage still lives in `test_rate_guard_client.py`
   for unset `RATE_GUARD_URL`, upstream non-200, Rate Guard 502, non-502 errors,
   unreachable, malformed status, and undecodable body. Evidence:
   `backend/tests/unit/test_edgar_client.py:39-88`,
   `backend/tests/unit/test_rate_guard_client.py:80-159`.
8. PASS. The removed `SEC_CONTACT_EMAIL` monkeypatch was dead for this test:
   migrated `edgar/client.py` no longer imports `settings`, the test stubs
   `_search_edgar_by_company_name`, and `SEC_CONTACT_EMAIL` is not referenced in
   `backend/app` outside config. Evidence:
   `backend/app/edgar/client.py:13-15`,
   `backend/tests/unit/test_13f_admin_dashboard.py` diff removes only the
   monkeypatch line,
   `backend/app/core/config.py:37`.

### E. Scope

9. PASS. This is a behaviour-preserving refactor with no DB migration and no
   `frontend/` or `rate-guard/` changes. `git diff --name-status main...HEAD`
   includes backend app/tests and docs only. The `docs/BACKLOG.md` item
   "EdgarClient not yet migrated onto the shared RateGuardClient" is removed as
   resolved, and the design build log records the post-rollout cleanup. Evidence:
   `docs/BACKLOG.md` diff removes the resolved item,
   `docs/tasks/2026-05-20_rate-guard-design.md:286-293`.

## Verification performed

- Read the review prompt, task doc, and Rate Guard design build-log.
- Inspected `git diff main...HEAD` scope and stats.
- Grepped for `EdgarFetchError`, `RateGuardFetchError`, and `EdgarClient()` call
  sites under `backend/app` and `backend/tests`.
- Reviewed the in-scope implementation, tests, backlog, and design updates.

I did not run the Docker backend test suite in this review pass.
