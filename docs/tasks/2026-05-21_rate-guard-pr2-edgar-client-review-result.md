# Review result — Rate Guard PR 2/4: repoint EdgarClient (PR #80)

Date: 2026-05-21
Branch reviewed: `claude/rate-guard-pr2-edgar-client`
Prompt: `docs/tasks/2026-05-21_rate-guard-pr2-edgar-client-review-prompts.md`

## Verdict

**暂不批准 / Not approved.**

One **P1 blocker** (B3): the rewrite flattens every EDGAR failure to a bare
`RuntimeError`, discarding the upstream status code. `run_daily_index_sync`
catches `httpx.HTTPStatusError` to classify a 404 — the rewritten client no
longer raises that type, so the daily index sync's entire 404 path (the
"expected no-index date" calendar) is dead in production. The test suite is
green (≈870) **because** the test `FakeEdgarClient`s still raise the old
exception type — the green is itself proof of the gap.

Everything else passes or is a recordable advisory. The fix is small and
contained.

## [P1 BLOCKER] B3 — daily index sync 404 handling is broken

### The defect

`run_daily_index_sync` (`backend/app/services/thirteenf_daily_sync.py:37-73`)
has two error paths:

```python
except httpx.HTTPStatusError as exc:        # line 65
    return _handle_http_error(session, sync, exc)
except Exception as exc:                    # line 67
    sync.status = "failed"
    ...
```

`_handle_http_error` (`thirteenf_daily_sync.py:210-225`) reads
`exc.response.status_code`, and on a **404 for an expected no-index date**
(weekend / federal holiday) sets `sync.status = "no_data"` — a benign, expected
outcome. Any other exception → `sync.status = "failed"`.

The **old** `EdgarClient` raised `httpx.HTTPStatusError` on a non-200 (via
`resp.raise_for_status()`), so a 404 reached the `HTTPStatusError` branch.

The **new** `EdgarClient._fetch` (`backend/app/edgar/client.py:135-141`) raises
a bare `RuntimeError` on an upstream non-200:

```python
if upstream_status != 200:
    raise RuntimeError(f"EDGAR returned HTTP {upstream_status} for {url}")
```

`RuntimeError` is **not** an `httpx.HTTPStatusError`, so it falls through to the
`except Exception` branch — `sync.status = "failed"`, **always**, even on an
expected no-index date.

### Production impact

EDGAR has no `form.idx` on weekends and federal holidays → a 404. The
`NoIndexExpectedDate` "expected no-index calendar" exists precisely so those
days resolve to `"no_data"` rather than `"failed"`. After this PR, **every
weekend and holiday daily sync is marked `"failed"`** — spurious failures,
retry churn, and 13F alert noise, on a job that runs every day. This silently
guts a working feature.

### Why 870 green tests did not catch it

`test_13f_daily_index_sync.py`'s `FakeEdgarClient.get()`
(`backend/tests/unit/test_13f_daily_index_sync.py:33-40`) raises
`httpx.HTTPStatusError` on a 404 — it still mimics the **old** real client:

```python
raise httpx.HTTPStatusError("fetch failed", request=request, response=response)
```

So `test_expected_no_index_404_marks_sync_no_data` and
`test_unexpected_404_marks_sync_failed_for_retry` exercise the
`HTTPStatusError` branch and pass — against a **stale test double** that no
longer matches the real client's exception contract. The 13F `FakeEdgarClient`
classes are now unfaithful fakes; that is the structural reason the regression
slipped through.

Production impact of B3 is localised to `run_daily_index_sync` — it is the only
EDGAR caller that catches `httpx.HTTPStatusError` (grep-confirmed). All other
call sites (`edgar_ingestion.py`) use a broad `except Exception`, which still
catches `RuntimeError`.

### Required fix

Restore a way for callers to recover the upstream status. Recommended:

1. Add a typed exception in `edgar/client.py`, e.g.
   `class EdgarFetchError(RuntimeError)` carrying `.status_code`. Subclassing
   `RuntimeError` keeps every existing `except Exception` / `except RuntimeError`
   caller working.
2. `_fetch` raises `EdgarFetchError(msg, status_code=upstream_status)` for an
   upstream non-200, and for the 502 case with the `upstream_status` from the
   error detail.
3. Update `run_daily_index_sync` to catch `EdgarFetchError` and branch on
   `.status_code == 404` (replacing or alongside the `httpx.HTTPStatusError`
   catch).
4. Update the 13F `FakeEdgarClient`s to raise the new typed exception so they
   stay faithful, **and add a regression test** that drives `run_daily_index_sync`
   with a fake raising the new 404 exception and asserts `"no_data"` on an
   expected no-index date — i.e. a test that would fail today.

## Per-question findings

### A. Design conformance / slim
- **A1 — PASS.** `client.py` deletes `_TokenBucket`, `_make_bucket` /
  `_get_bucket`, the retry loop, `_GLOBAL_PAUSE_UNTIL`, `_parse_backoff`, and
  `build_sec_user_agent`. No rate-limiting or retry logic remains; `_fetch`
  (`client.py:107-141`) is a single POST to `/v1/fetch`.
- **A2 — PASS (API surface).** `get` / `head` / `close` / `__enter__` /
  `__exit__` / `BASE` / `EFTS_BASE` / `DATA_BASE` are all retained
  (`client.py:88-159`); the 8 `EdgarClient()` call sites compile unchanged. The
  *behavioural* break is B3, not an API-surface break.

### B. Exception-behaviour parity (MANDATORY)
- **B3 — FAIL.** See the blocker above.
- **B4 — PASS.** `head()` → `_fetch("HEAD", …)`: a Rate Guard `200` with empty
  `body_b64` decodes to `b""` and returns; a 404 raises. Its two callers
  (`edgar_ingestion.py:834,853`) wrap it in `except Exception`, so the
  `RuntimeError` is handled — `head()` itself is fine.

### C. Live-mode startup guard (MANDATORY)
- **C5 — PASS.** `app/main.py` `lifespan` raises `RuntimeError` before `yield`
  when `EDGAR_FETCH_MODE == "live"` and `RATE_GUARD_URL` is empty — an ASGI
  lifespan-startup failure that aborts uvicorn (a real hard startup error).
  `EdgarClient._fetch_endpoint` (`client.py:99-105`) raising is the second line
  of defence; confirmed there is no live-fetch path that skips it.
- **C6 — PASS.** `(settings.RATE_GUARD_URL or "").strip()` handles `None`,
  empty, and whitespace-only.

### D. Test & CI seam (MANDATORY)
- **D7 — PASS.** `conftest.py` sets a placeholder `RATE_GUARD_URL` before any
  app import and leaves `EDGAR_FETCH_MODE` at `live` — correct: forcing
  `replay` would route `fetch_and_store` to the DB and break the 13F tests'
  injected fakes.
- **D8 — PASS.** `ci.yml` `.env` carries `RATE_GUARD_URL=http://rate-guard.invalid`;
  the api container starts (guard satisfied) and nothing in an idle CI api
  dials it (scheduler / worker off by default).
- **D9 — PASS, with a caveat that is the heart of B3.** No test calls a real
  Rate Guard. But "tests inject `FakeEdgarClient`" is exactly why B3 went
  unnoticed — those fakes no longer mirror the real client's exception type.
  See B3's required-fix item 4.

### E. `_fetch` robustness
- **E10 — advisory.** `_rate_guard_error_detail` and the `b64decode(... or "")`
  / `int(payload.get("status", 0))` guards degrade safely. Minor: a Rate Guard
  `200` whose body is not JSON makes `resp.json()` raise `ValueError`, not
  `RuntimeError` — `_fetch`'s error contract is not 100% uniform. Rate Guard
  always returns JSON on 200, so this is theoretical; worth a one-line guard.
- **E11 — PASS.** `_RATE_GUARD_TIMEOUT_S = 1800s`. Rate Guard's `edgar` worst
  case ≈ 6 attempts × (≤60s pause, since `pause_s=60`) + backoff
  `5+30+120+300+300` + 6×30s requests ≈ ~22 min — comfortably under 30 min.
- **E12 — PASS.** `edgar_rate_limit_status()` is kept; `_fetch` calls
  `_record_request` with the upstream status, so the admin panel and the 13F
  403/429 alerting still get data. `global_pause_until: None` is acknowledged
  for PR 4/4.

### F. Intentional deferrals
- **F13 — PASS.** `OpenFigiClient` / `DataromaClient` untouched (PR 3); admin
  panel still on `edgar_rate_limit_status()` (PR 4); unused `EDGAR_*` settings
  left in `config.py` — all stated in the task doc.

### G. Tests
- **G14 — advisory.** The rewritten `test_edgar_client.py` covers the new
  client's happy and error paths well, but every error assertion is just
  `pytest.raises(RuntimeError, …)` — it locks in the flat `RuntimeError`
  contract that *is* the B3 root cause. No test verifies that a caller can
  recover the upstream status (404 vs 403) from the raised exception.
- **G15 — PASS.** The two `test_13f_admin_dashboard.py` removals targeted
  behaviour now owned by Rate Guard (the 429 global pause — covered by
  rate-guard's own `test_429_global_pause_is_respected_before_retry`) and dead
  `_GLOBAL_PAUSE_UNTIL` code.

## Verification

- `docker compose run --rm --no-deps api pytest -q` — green (~870) per the PR's
  own run. As shown under B3, green does not imply correct here: the 404 tests
  pass against a stale fake.
- `git diff main...HEAD` — scope matches the prompt; no DB migration.

## Pass bar

The bar — "a behaviour-preserving repoint of a load-bearing client" — is **not
met**: B3 is a behaviour regression in the daily index sync. Approvable once B3
is fixed (typed `EdgarFetchError` with `.status_code`, `run_daily_index_sync`
updated, the 13F fakes made faithful, and a regression test that fails today).
E10 and G14 are advisories to fold into the same change.
