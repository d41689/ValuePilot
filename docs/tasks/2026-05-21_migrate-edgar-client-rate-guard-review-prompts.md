# Review prompt — Migrate EdgarClient onto the shared RateGuardClient (PR #83)

Paste this into a fresh reviewer session (human or agent). It is self-contained.
Pair it with `docs/tasks/2026-05-21_migrate-edgar-client-rate-guard.md` (task
doc) and `docs/tasks/2026-05-20_rate-guard-design.md` §14 (design build-log).

## Reviewer brief

You are reviewing **PR #83**, branch `claude/migrate-edgar-client-rate-guard` —
a post-Rate-Guard-rollout cleanup. `EdgarClient` becomes a thin wrapper over the
shared `RateGuardClient` (like `OpenFigiClient` / `DataromaClient` since PR 3),
deleting its duplicated `_fetch` plumbing and the `EdgarFetchError` type.

This is **prod-auto-deploying backend code** (a self-hosted runner deploys every
`main` push) and it **rewrites a load-bearing HTTP client** and **deletes a
public exception type**. It is intended to be **behaviour-preserving** — review
it as such, with particular attention to (1) behaviour parity for the 8 call
sites, and (2) the `EdgarFetchError` → `RateGuardFetchError` unification,
especially the daily-index 404 path (PR 2's B3).

Two review lenses — one agent may cover both: **backend / Python** (parity, the
exception unification, the deletion), **test** (the slimmed coverage).

### Files in scope
- `backend/app/edgar/client.py` — rewritten as a `RateGuardClient` wrapper
- `backend/app/services/thirteenf_daily_sync.py` — catches `RateGuardFetchError`
- `backend/tests/unit/test_edgar_client.py` — slimmed to wrapper tests
- `backend/tests/unit/test_13f_daily_index_sync.py` — the fake raises `RateGuardFetchError`
- `backend/tests/unit/test_13f_admin_dashboard.py` — a dead monkeypatch removed
- `docs/BACKLOG.md`, design build-log, task doc

### Baseline
`git diff main...HEAD`.

## Answer each question with a verdict (PASS / FAIL / advisory) + file:line evidence

### A. Behaviour parity — MANDATORY (it is a load-bearing rewrite)
1. `EdgarClient.get()` / `head()` delegate to `RateGuardClient.fetch(upstream=
   "edgar", method=…, url=…)`. Confirm the observable behaviour is unchanged vs
   `main`: success returns the upstream body; a non-200 / 404 / 502 / unreachable
   raises; `head()` succeeds on a 200 (empty body) and raises on a 404.
2. The public API (`get` / `head` / `close` / `__enter__`/`__exit__` /
   `BASE` / `EFTS_BASE` / `DATA_BASE`) is unchanged — confirm the 8
   `EdgarClient()` call sites (`edgar/fetcher.py`, `services/edgar_ingestion.py`,
   `services/thirteenf_admin_dashboard.py`) need no edits.
3. Lifecycle: `EdgarClient.close()` delegates to `RateGuardClient.close()`, and
   the context manager closes it. Confirm no httpx client is leaked (the PR-3 C6
   lesson) — including the non-`with` call site in `edgar/fetcher.py`.

### B. Exception unification — MANDATORY
4. `EdgarFetchError` is deleted; `RateGuardFetchError` is the single egress error
   type. It is a `RuntimeError` subclass carrying `.status_code` — confirm it is
   a true drop-in: broad-`except` call sites (`edgar_ingestion.py`) are
   unaffected.
5. **The B3 path.** `thirteenf_daily_sync.run_daily_index_sync` now catches
   `RateGuardFetchError` to classify a 404 (`_handle_http_error` reads
   `.status_code`). Confirm: the real `EdgarClient` raises `RateGuardFetchError`
   (via `RateGuardClient.fetch`), and `test_13f_daily_index_sync.py`'s
   `FakeEdgarClient` raises the *same* type — so the expected-no-index 404 tests
   stay faithful regression guards. Grep for any surviving `EdgarFetchError`
   reference anywhere in `backend/`.

### C. The deletion / slim
6. `_fetch`, `_fetch_endpoint`, `_rate_guard_error_detail`,
   `_RATE_GUARD_TIMEOUT_S`, `EdgarFetchError`, and the now-unused imports are
   all gone from `edgar/client.py`; nothing dangles. The kept
   `BASE` / `EFTS_BASE` / `DATA_BASE` host constants have no external callers —
   confirm leaving them is a deliberate (documentation) choice, not an oversight.

### D. Tests
7. `test_edgar_client.py` is slimmed to wrapper tests (routes as `upstream=
   edgar`, GET/HEAD, error propagation with `.status_code`, the host constants).
   Confirm the removed deep error-path tests (502, malformed envelope,
   unreachable, …) are genuinely still covered by `test_rate_guard_client.py` —
   not lost coverage.
8. The removed `test_13f_admin_dashboard.py` line monkeypatched
   `app.edgar.client.settings.SEC_CONTACT_EMAIL`. Confirm it was dead: the
   migrated `edgar/client.py` no longer imports `settings`, the test fully stubs
   `_search_edgar_by_company_name`, and `SEC_CONTACT_EMAIL` is referenced
   nowhere in `backend/app`.

### E. Scope
9. Confirm this is a behaviour-preserving refactor: no call-site edits, no DB
   migration, no `frontend/` or `rate-guard/` changes, and the `docs/BACKLOG.md`
   "EdgarClient not yet migrated" item is removed (resolved).

## Verification
- `docker compose run --rm --no-deps api pytest -q` — backend green (~892).
- `git diff main...HEAD` — scope; no DB migration; no frontend / rate-guard
  changes.

## Pass bar
Approve only if: A (behaviour is genuinely preserved for every call site, no
client leak); B (the exception unification is a true drop-in and the B3 404
guard is intact). C / D / E findings are recorded. The bar is "a
behaviour-preserving consolidation of EdgarClient onto the shared Rate Guard
client — safe to auto-deploy to prod."
