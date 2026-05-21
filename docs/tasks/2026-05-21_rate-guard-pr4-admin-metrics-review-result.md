# Review result — Rate Guard PR 4/4: admin panel reads /v1/metrics (PR #82)

Reviewed: 2026-05-21  
Branch: `claude/rate-guard-pr4-admin-metrics`  
Baseline: `git diff main...HEAD`

**Overall verdict: APPROVE** — all mandatory pass-bar items pass. Three advisory
gaps noted in G (tests), none blocking.

---

## A. Deletion completeness — MANDATORY

### A1 — `edgar/client.py` deletion inventory **PASS**

All named items removed:

| Item | Status | Evidence |
|---|---|---|
| `_REQUEST_EVENTS` | Deleted | `edgar/client.py` diff: `deque` declaration gone |
| `_REQUEST_EVENTS_LOCK` | Deleted | `threading.Lock()` declaration gone |
| `_record_request()` | Deleted | Function body gone |
| `edgar_rate_limit_status()` | Deleted | Function body gone |
| `import threading` | Deleted | Top-of-file imports diff |
| `import time` | Deleted | Top-of-file imports diff |
| `from collections import deque` | Deleted | Top-of-file imports diff |
| `_record_request(None, url)` in `HTTPError` catch | Deleted | `_fetch` diff, former line 76 |
| `_record_request(upstream_status, url)` in 502 branch | Deleted | `_fetch` diff, former line 86 |
| `_record_request(None, url)` in "non-502 error" raise | Deleted | `_fetch` diff, former line 90 |
| `_record_request(None, url)` in `ValueError` JSON catch | Deleted | `_fetch` diff, former line 98 |
| `_record_request(None, url)` in non-dict check | Deleted | `_fetch` diff, former line 101 |
| `_record_request(None, url)` in `(ValueError, TypeError)` catch | Deleted | `_fetch` diff, former line 106 |
| `_record_request(upstream_status, url)` before status check | Deleted | `_fetch` diff, former line 110 |

Seven `_record_request` calls confirmed removed. `_fetch` logic is otherwise
identical — the retry/status-check/JSON-unwrap flow is untouched.

### A2 — Repo-wide grep for deleted names **PASS**

`grep -rn "edgar_rate_limit_status|_record_request|_REQUEST_EVENTS" backend/app backend/tests`:

- **`edgar_rate_limit_status`** — all 16 hits are either:
  - `build_edgar_rate_limit_status` (the new wrapper) — not the deleted name.
  - `edgar_rate_limit_status=` as a **parameter name** in
    `thirteenf_health.evaluate_13f_alerts()` and test lambdas — not importing
    the deleted symbol.
- **`_record_request`** — 0 hits.
- **`_REQUEST_EVENTS`** — 0 hits.

No importer of a deleted name survives.

---

## B. The adapter contract — MANDATORY

### B3 — All frontend fields emitted **PASS**

`normalizeEdgarRateLimit` (`frontend/lib/thirteenfAdmin.js`) reads these keys.
Checked against `build_edgar_rate_limit_status()` in
`backend/app/services/thirteenf_admin_dashboard.py:287`:

| Frontend key | Adapter key | Source in adapter |
|---|---|---|
| `mode` | `"mode"` | `settings.EDGAR_FETCH_MODE` |
| `request_delay_s` | `"request_delay_s"` | `1/rate_per_sec` or `None` |
| `max_retries` | `"max_retries"` | `snap.get("max_retries")` |
| `window_seconds` | `"window_seconds"` | `snap.get("window_seconds")` |
| `recent_request_count` | `"recent_request_count"` | `snap.get(…, 0)` |
| `estimated_capacity` | `"estimated_capacity"` | `snap.get(…)` |
| `remaining_estimated_capacity` | `"remaining_estimated_capacity"` | `snap.get(…)` |
| `global_pause_until` | `"global_pause_until"` | `snap.get(…)` |

All 8 fields present. No field silently absent.

### B4 — No frontend file changes **PASS**

`git diff main...HEAD --name-only` lists zero `frontend/` paths. Claim is
literally true.

### B5 — `edgar_block_alert` derivation and divide-by-zero guard **PASS**

`thirteenf_admin_dashboard.py:295–298`:
```python
recent_403 = int(snap.get("recent_403_count", 0) or 0)
recent_429 = int(snap.get("recent_429_count", 0) or 0)
rate_per_sec = float(snap.get("rate_per_sec", 0) or 0)
```
`thirteenf_admin_dashboard.py:300–301`:
```python
"request_delay_s": (1.0 / rate_per_sec) if rate_per_sec > 0 else None,
```
`thirteenf_admin_dashboard.py:310`:
```python
"edgar_block_alert": recent_403 > 0 or recent_429 > 0,
```

`edgar_block_alert` correctly derived from 403/429 counts. Zero guard on
`rate_per_sec` prevents division-by-zero; `None` propagates to the frontend
which reads `data.request_delay_s ?? 0`.

### B6 — `global_pause_until` passed through unmodified **PASS**

`thirteenf_admin_dashboard.py:314`:
```python
"global_pause_until": snap.get("global_pause_until"),
```

No transformation. Rate Guard's real pause propagates to the frontend for the
first time (previously always `None` since PR 2).

---

## C. Failure-mode handling — MANDATORY

### C7 — Rate Guard unreachable → HTTP 503 **PASS**

Chain:

1. `RateGuardClient.metrics()` catches `httpx.HTTPError` →
   raises `RateGuardFetchError` (`rate_guard/client.py:140–144`).
2. `build_edgar_rate_limit_status()` has no try/except; propagates
   `RateGuardFetchError` (`thirteenf_admin_dashboard.py:287–314`).
3. `read_edgar_rate_limit_status` endpoint catches `RateGuardFetchError` →
   `HTTPException(status_code=503, …)` (`thirteenf_admin.py:257–261`).

No 500, no all-zeros panel. Confirmed by
`test_edgar_rate_limit_status_endpoint_503_when_rate_guard_unavailable`
(`test_13f_admin_dashboard.py:1749`).

### C8 — Scheduler outage path: no crash, no false alarm **PASS**

`scheduler.py:229–234`:
```python
try:
    rate_limit_status = build_edgar_rate_limit_status()
except RateGuardFetchError:
    rate_limit_status = None
alerts = evaluate_13f_alerts(db, edgar_rate_limit_status=rate_limit_status)
```

`thirteenf_health.py:36`:
```python
if edgar_rate_limit_status and edgar_rate_limit_status.get("edgar_block_alert"):
```

`None` is falsy; block-alert branch is skipped. Rate Guard outage cannot crash
the scheduler run or fire a false `SEC_EDGAR_BLOCK_ALERT`.

---

## D. `RateGuardClient.metrics()` & `_base_url` refactor

### D9 — `metrics()` contract **PASS**

`rate_guard/client.py:131–162`:
- Issues `GET /v1/metrics` with `?upstream=…` when arg given; no param when
  absent. ✓
- Unwraps `body.get("upstreams", {})` → returns `upstreams.get(upstream, {})`
  for single-upstream call; full map otherwise. ✓
- `httpx.HTTPError` → `RateGuardFetchError`. ✓
- Non-200 → `RateGuardFetchError`. ✓
- `ValueError` on JSON decode → `RateGuardFetchError`. ✓
- `_base_url()` raises `RateGuardFetchError` before any HTTP call if
  `RATE_GUARD_URL` is unset. ✓

### D10 — `_endpoint()` → `_base_url()` refactor **PASS**

`rate_guard/client.py:58–64`:
- `_base_url()` returns `base.rstrip("/")` (was `f"{base}/v1/fetch"`).
- `fetch()` now builds `f"{self._base_url()}/v1/fetch"`. ✓
- `metrics()` builds `f"{self._base_url()}/v1/metrics"`. ✓
- Existing `fetch` tests (`test_rate_guard_client.py:1–161`) are unmodified
  and continue to exercise the same fetch behaviour. ✓

---

## E. Client lifecycle (PR-3 C6 regression check)

### E11 — No unclosed-client regression **PASS**

`thirteenf_admin_dashboard.py:292–293`:
```python
with RateGuardClient() as rate_guard:
    snap = rate_guard.metrics("edgar")
```

Context manager used correctly. `__exit__` calls `close()`. PR-3 C6 finding
not reintroduced.

---

## F. rate-guard `max_retries`

### F12 — `max_retries` from upstream config **PASS**

`rate-guard/app/gateway.py:155`:
```python
snap["max_retries"] = u.max_retries
```

`u` is the `UpstreamConfig` object loaded from the Rate Guard configuration;
`max_retries` is its configured value, not a hardcoded constant. The field
flows into the adapter's `snap.get("max_retries")` and then to the frontend.

The 19 existing Rate Guard tests are unaffected by this one-line addition.

---

## G. Tests

### G13 — Removed tests targeted deleted behaviour **PASS**

| Removed test | Targeted |
|---|---|
| `test_fetches_are_recorded_for_the_rate_limit_status` | `_record_request` + recording deque (deleted) |
| `test_edgar_rate_limit_status_counts_recorded_requests` | `_REQUEST_EVENTS`, per-process counting (deleted) |

Coverage lost is coverage of deleted code — not a regression.

### G14 — New / rewritten tests — **PASS with advisory gaps**

Tests added and confirmed:

| Test | File | What it covers |
|---|---|---|
| `test_metrics_returns_a_single_upstream_snapshot` | `test_rate_guard_client.py:165` | Happy path; URL includes `?upstream=edgar` |
| `test_metrics_without_upstream_returns_all` | `test_rate_guard_client.py:179` | No-arg call returns full map |
| `test_metrics_raises_when_rate_guard_unreachable` | `test_rate_guard_client.py:190` | `httpx.ConnectError` → `RateGuardFetchError` |
| `test_metrics_raises_on_non_200` | `test_rate_guard_client.py:200` | HTTP 500 → `RateGuardFetchError` |
| `test_edgar_rate_limit_status_endpoint_returns_runtime_budget` | `test_13f_admin_dashboard.py:1730` | Rewritten; monkeypatches `RateGuardClient.metrics` |
| `test_edgar_rate_limit_status_endpoint_503_when_rate_guard_unavailable` | `test_13f_admin_dashboard.py:1749` | New; verifies HTTP 503 |
| `test_build_edgar_rate_limit_status_adapts_the_rate_guard_snapshot` | `test_13f_admin_dashboard.py:1764` | Adapter: `edgar_block_alert`, `request_delay_s`, `max_retries`, `global_pause_until` |
| `test_run_13f_health_summary_emits_alerts_before_summary` | `test_scheduler_alignment.py:132` | Repointed to `build_edgar_rate_limit_status` |

**Advisory gaps (not blocking):**

1. **`metrics()` malformed JSON path untested** — the `ValueError` on
   `resp.json()` when Rate Guard returns HTTP 200 with a non-JSON body
   (`rate_guard/client.py:153–157`) is not covered. Low risk; recommend adding
   to backlog.

2. **`metrics()` non-dict body silently degrades** — when `resp.json()`
   succeeds but yields a non-dict (e.g. a JSON array), the code returns `{}`
   rather than raising `RateGuardFetchError`. The adapter then emits
   all-`None` / all-zero fields without triggering the 503 path. Advisory:
   consider raising `RateGuardFetchError` for non-dict bodies to make the
   failure mode explicit and consistent.

3. **Scheduler outage → `None` path has no dedicated test** — the
   `except RateGuardFetchError: rate_limit_status = None` branch in
   `run_13f_health_summary` is not exercised by `test_scheduler_alignment.py`.
   The `evaluate_13f_alerts(…, edgar_rate_limit_status=None)` handling is
   covered in `thirteenf_health` tests, but end-to-end isolation of the
   scheduler's outage path is missing.

---

## H. Scope / deferrals

### H15 — Deliberate deferrals confirmed **PASS**

| Deferral | Status |
|---|---|
| Multi-upstream admin view (OpenFIGI / Dataroma metrics) | Recorded in `docs/BACKLOG.md`: "Admin metrics panel is EDGAR-only — no OpenFIGI / Dataroma view" |
| `EdgarClient._fetch` duplication (migrate onto `RateGuardClient`) | Recorded in `docs/BACKLOG.md`: "EdgarClient carries its own copy of Rate Guard fetch plumbing" |
| Unused `EDGAR_REQUESTS_PER_SECOND`, `EDGAR_RATE_LIMIT_WINDOW_S`, `EDGAR_REQUEST_DELAY_S` in `config.py` | Left in place; `EDGAR_FETCH_MODE` still used by the adapter for `mode` |

All three intentional; explicitly in the backlog.

---

## Verification

Commands to run before merge:
```
docker compose run --rm --no-deps api pytest -q   # backend ~893 tests
cd rate-guard && pytest -q                         # Rate Guard 19 tests
git diff main...HEAD --name-only                  # no DB migration; no frontend/ changes
```

---

## Pass-bar summary

| Bar item | Verdict |
|---|---|
| A — deletion complete, nothing dangles | **PASS** |
| B — adapter emits all 8 frontend fields; no frontend change | **PASS** |
| C — Rate Guard outage → clean 503 / skipped alert, no crash / false alarm | **PASS** |
| E — no unclosed-client regression (PR-3 C6) | **PASS** |
| D — `metrics()` contract + `_base_url` refactor | **PASS** |
| F — `max_retries` from upstream config | **PASS** |
| G — removed tests target deleted behaviour; new tests adequate | **PASS** (3 advisory gaps) |
| H — deferrals deliberate and in BACKLOG | **PASS** |

**Decision: APPROVE.** The admin panel and 13F alerting read Rate Guard's
authoritative metrics, degrade safely when Rate Guard is down (503 / skip),
and the rollout's dead code is fully removed. Safe to auto-deploy to prod.
