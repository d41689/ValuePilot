# Review results — Migrate EdgarClient onto the shared RateGuardClient (PR #83)

**Reviewer:** Claude (claude-sonnet-4-6), 2026-05-21  
**Branch:** `claude/migrate-edgar-client-rate-guard` → `main`  
**Baseline:** `git diff main...HEAD`

---

## A. Behaviour parity — MANDATORY

### A1 — `get()` / `head()` delegation and observable behaviour — PASS

`EdgarClient.get()` delegates to `self._rate_guard.fetch(upstream="edgar", method="GET", url=url)` (`edgar/client.py:30`) and `head()` delegates identically with `method="HEAD"` (`edgar/client.py:34`), discarding the return value exactly as before.

`RateGuardClient.fetch()` (`rate_guard/client.py:67–129`) is a line-for-line functional match of the deleted `EdgarClient._fetch`:

| Scenario | Old behaviour | New behaviour |
|---|---|---|
| Success | returns `base64.b64decode(payload["body_b64"])` | same, via `RateGuardClient.fetch` |
| Upstream non-200 | raises `EdgarFetchError(…, status_code=N)` | raises `RateGuardFetchError(…, status_code=N)` |
| Rate Guard 502 | raises with `upstream_status` from detail dict | same |
| Rate Guard unreachable | catches `httpx.HTTPError`, raises | same |
| `head()` on 200 | returns `None` (return value discarded) | same |
| `head()` on 404 | raises (upstream 404 surfaces as error) | same |

`RateGuardFetchError` is a `RuntimeError` subclass with `.status_code` — structurally identical to the deleted `EdgarFetchError` (`rate_guard/client.py:24–35`).

### A2 — Public API unchanged, 8 call sites need no edits — PASS

All public members are preserved in the new `edgar/client.py`:

| Member | Present | Evidence |
|---|---|---|
| `get(url)` | ✓ | `edgar/client.py:28` |
| `head(url)` | ✓ | `edgar/client.py:32` |
| `close()` | ✓ | `edgar/client.py:36` |
| `__enter__` / `__exit__` | ✓ | `edgar/client.py:39–43` |
| `BASE` | ✓ | `edgar/client.py:21` |
| `EFTS_BASE` | ✓ | `edgar/client.py:22` |
| `DATA_BASE` | ✓ | `edgar/client.py:23` |

All 8 call sites confirmed unchanged:

- `edgar/fetcher.py:17,90,95` — imports `EdgarClient`, instantiates, calls `.get()`, calls `.close()`
- `edgar_ingestion.py:20,364,454,632,702` — imports and uses `with EdgarClient() as client`
- `thirteenf_admin_dashboard.py:16,685,941,2940` — imports and uses `with EdgarClient() as client`

No edits to any call-site file appear in `git diff main...HEAD`.

### A3 — Lifecycle: no httpx client leak — PASS

`EdgarClient.close()` → `self._rate_guard.close()` → `self._client.close()` (`rate_guard/client.py:175–176`). The httpx client owned by `RateGuardClient` is always closed.

Context manager: `__exit__` calls `self.close()` (`edgar/client.py:42–43`). Correct.

Non-`with` call site in `edgar/fetcher.py:88–95`:
```python
own_client = client is None
if own_client:
    client = EdgarClient()
try:
    body = client.get(source_url)
finally:
    if own_client:
        client.close()
```
The `try/finally` correctly closes the client even on exception. No leak possible.

---

## B. Exception unification — MANDATORY

### B4 — `EdgarFetchError` deleted; `RateGuardFetchError` is a true drop-in — PASS

`grep -rn "EdgarFetchError" backend/` returns **no output** — the type is fully gone from the codebase.

`RateGuardFetchError` (`rate_guard/client.py:24–35`) is a `RuntimeError` subclass with `.__init__(message, *, status_code=None)` — structurally identical to the deleted `EdgarFetchError`. Broad-except sites in `edgar_ingestion.py` all use `except Exception:` (lines 278, 370, 733, 797, 836, 855, 869, 916, 995) which catches both the old and new type without any change. **Drop-in confirmed.**

### B5 — The B3 path (daily-index 404 classification) — PASS

Three links in the chain:

1. **Real `EdgarClient` raises `RateGuardFetchError`:** `EdgarClient.get()` calls `RateGuardClient.fetch()` which raises `RateGuardFetchError(…, status_code=404)` on a 404 upstream (`rate_guard/client.py:119–122`).

2. **`thirteenf_daily_sync` catches the right type:** `run_daily_index_sync` catches `RateGuardFetchError` at `thirteenf_daily_sync.py:65` and passes it to `_handle_http_error` (signature: `exc: RateGuardFetchError` at line 210), which reads `exc.status_code` to classify a 404 as `"no_data"`. Correct.

3. **`FakeEdgarClient` raises the same type:** `test_13f_daily_index_sync.py:37–40` raises `RateGuardFetchError(…, status_code=self.status_code)` — the fake matches the real. The 404 regression tests (`test_run_daily_index_sync_404_expected` at line 198, `test_run_daily_index_sync_404_unexpected` at line 211) remain faithful guards.

No surviving `EdgarFetchError` references anywhere in `backend/`. B3 regression guard is intact.

---

## C. The deletion / slim

### C6 — All dead code deleted; constants retention is deliberate — PASS

Confirmed deleted from `edgar/client.py`:

| Symbol | Status |
|---|---|
| `_RATE_GUARD_TIMEOUT_S` | deleted |
| `EdgarFetchError` | deleted |
| `_rate_guard_error_detail` | deleted |
| `_fetch_endpoint` | deleted |
| `_fetch` | deleted |
| `import base64` | deleted |
| `import logging` | deleted |
| `from app.core.config import settings` | deleted |
| `logger = logging.getLogger(...)` | deleted |

Remaining imports: `httpx` (required for `httpx.Client | None` type annotation in `__init__`) and `RateGuardClient`. Nothing dangles.

**`BASE` / `EFTS_BASE` / `DATA_BASE` retention:** `grep -rn "EdgarClient\.BASE\|EdgarClient\.EFTS_BASE\|EdgarClient\.DATA_BASE"` on `backend/app/` returns no output — no external callers. The task doc (`docs/tasks/2026-05-21_migrate-edgar-client-rate-guard.md`) explicitly says "Keep the `BASE` / `EFTS_BASE` / `DATA_BASE` host constants" as a deliberate scope decision (documentation value). The test `test_base_constants_name_the_sec_hosts` asserts their values. Retention is intentional, not an oversight.

---

## D. Tests

### D7 — Removed deep error-path tests are genuinely covered by `test_rate_guard_client.py` — PASS

Every test removed from `test_edgar_client.py` maps to an existing test in `test_rate_guard_client.py`:

| Removed from `test_edgar_client.py` | Covered by `test_rate_guard_client.py` |
|---|---|
| `test_get_without_rate_guard_url_raises_and_does_not_fetch` | `test_unset_rate_guard_url_raises_and_does_not_fetch` (line 80) |
| `test_upstream_non_200_raises` | `test_upstream_non_200_carries_status` (line 96) |
| `test_rate_guard_502_raises` | `test_rate_guard_502_carries_upstream_status` (line 106) |
| `test_rate_guard_non_502_error_raises` | `test_rate_guard_non_502_error_raises` (line 121) |
| `test_rate_guard_unreachable_raises` | `test_rate_guard_unreachable_raises` (line 131) |
| `test_malformed_success_envelope_raises` | `test_malformed_envelope_raises` (line 144) |
| `test_edgar_fetch_error_is_a_runtime_error` | `test_rate_guard_fetch_error_is_a_runtime_error` (line 162) |

Coverage is not lost — it moved to the right place (the shared client's own test file).

The new `test_edgar_client.py` correctly keeps the wrapper-specific assertions: `upstream="edgar"` routing for GET and HEAD (`test_get_routes_through_rate_guard_as_the_edgar_upstream`, `test_head_routes_method_head`), error propagation with `.status_code` (`test_upstream_404_propagates_with_status`), and the SEC host constants (`test_base_constants_name_the_sec_hosts`).

### D8 — Removed `monkeypatch` line in `test_13f_admin_dashboard.py` was dead — PASS

The removed line (`monkeypatch.setattr("app.edgar.client.settings.SEC_CONTACT_EMAIL", "ops@example.com")`) patched a setting that:

1. **`edgar/client.py` no longer imports `settings`** — confirmed, the import is deleted.
2. **`SEC_CONTACT_EMAIL` is not referenced anywhere in `backend/app/`** — `grep -rn "SEC_CONTACT_EMAIL" backend/app/` returns only `app/core/config.py:37` (the field definition), not any usage site.
3. **The test fully stubs `_search_edgar_by_company_name`** — the monkeypatch was superfluous even before this PR (Rate Guard owns the SEC User-Agent header since PR 2).

Removing the line is correct cleanup.

---

## E. Scope

### E9 — Behaviour-preserving refactor; backlog item resolved — PASS

Confirmed via `git diff main...HEAD`:

- **No call-site edits:** `edgar/fetcher.py`, `edgar_ingestion.py`, `thirteenf_admin_dashboard.py` are not in the diff.
- **No DB migration:** no Alembic file in diff; no migration-related changes.
- **No `frontend/` changes:** `git diff main...HEAD -- frontend/` is empty.
- **No `rate-guard/` changes:** `git diff main...HEAD -- rate-guard/` is empty.
- **Backlog item removed:** `docs/BACKLOG.md` diff removes the "EdgarClient not yet migrated onto the shared RateGuardClient" entry.
- **Design build-log updated:** `docs/tasks/2026-05-20_rate-guard-design.md` gets a §14 addendum recording the cleanup.

---

## Verification

PR body states `docker compose run --rm --no-deps api pytest -q` passes with **892 passed**. The test count is consistent with the suite (old `test_edgar_client.py` had ~8 tests; new has 4; the 4-test reduction accounts for the net diff, with the 7 removed tests replaced by coverage already in `test_rate_guard_client.py`).

---

## Overall verdict — APPROVE ✓

All mandatory criteria are met:

- **A (behaviour parity):** `get()`/`head()` delegation is correct; the full error taxonomy is preserved via `RateGuardClient.fetch`; lifecycle is clean with no httpx client leak in any call site, including the non-`with` path in `edgar/fetcher.py`.
- **B (exception unification):** `EdgarFetchError` is fully gone with zero surviving references; `RateGuardFetchError` is a structurally identical drop-in; the B3 daily-index 404 classification and its regression tests are intact.
- **C/D/E:** Clean deletion with nothing dangling; test coverage genuinely preserved in `test_rate_guard_client.py`; monkeypatch removal confirmed dead; scope is strictly the declared refactor.

**Safe to auto-deploy to prod.** This is a behaviour-preserving consolidation of `EdgarClient` onto the shared Rate Guard client.
