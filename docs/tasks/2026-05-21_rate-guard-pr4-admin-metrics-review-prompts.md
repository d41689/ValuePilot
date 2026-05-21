# Review prompt — Rate Guard PR 4/4: admin panel reads /v1/metrics (PR #82)

Paste this into a fresh reviewer session (human or agent). It is self-contained.
Pair it with `docs/tasks/2026-05-21_rate-guard-pr4-admin-metrics.md` (task doc)
and `docs/tasks/2026-05-20_rate-guard-design.md` §7 / §14 (design).

## Reviewer brief

You are reviewing **PR #82**, branch `claude/rate-guard-pr4-admin-metrics` —
**Rate Guard PR 4/4**, the final PR of the rollout. It repoints the admin
`edgar-rate-limit` panel and the 13F 403/429 block alerting onto Rate Guard's
`GET /v1/metrics`, and deletes `EdgarClient`'s now-dead per-process recording.

This is **prod-auto-deploying backend code** (a self-hosted runner deploys every
`main` push). It **deletes a public function** (`edgar_rate_limit_status`) and
**rewires a panel + an alerting path** onto a new data source. Review it with
particular attention to (1) the adapter contract — the claim "frontend
unchanged" must actually hold, (2) failure-mode handling when Rate Guard is
unreachable, and (3) deletion completeness.

Three review lenses — one agent may cover all: **backend / Python** (the
`metrics()` method, the adapter, the deletion, the scheduler repoint),
**frontend contract** (the preserved response shape), **failure-mode / ops**
(graceful degradation — 503, skipped alert, no false alarm, no crash).

### Files in scope
- `backend/app/rate_guard/client.py` — `RateGuardClient.metrics()`, `_base_url`
- `backend/app/services/thirteenf_admin_dashboard.py` — `build_edgar_rate_limit_status()`
- `backend/app/api/v1/endpoints/thirteenf_admin.py` — the endpoint's 503 mapping
- `backend/app/services/scheduler.py` — the 13F alert repoint
- `backend/app/edgar/client.py` — the deleted per-process recording
- `rate-guard/app/gateway.py` — `metrics()` snapshot gains `max_retries`
- `backend/tests/unit/test_rate_guard_client.py`, `test_13f_admin_dashboard.py`,
  `test_edgar_client.py`, `test_scheduler_alignment.py`
- design build-log, task doc, `docs/BACKLOG.md`

### Baseline
`git diff main...HEAD`.

## Answer each question with a verdict (PASS / FAIL / advisory) + file:line evidence

### A. Deletion completeness — MANDATORY
1. `edgar/client.py` deletes `_REQUEST_EVENTS`, `_REQUEST_EVENTS_LOCK`,
   `_record_request`, `edgar_rate_limit_status`, the seven `_record_request`
   calls in `_fetch`, and the now-unused imports (`threading`, `time`,
   `collections.deque`). Confirm nothing dangles and `_fetch` still behaves
   exactly as before minus the recording.
2. Grep the whole repo (`backend/app` **and** `backend/tests`) for
   `edgar_rate_limit_status`, `_record_request`, `_REQUEST_EVENTS`. Confirm
   every remaining reference is either deleted or repointed — no importer of a
   deleted name survives.

### B. The adapter contract — MANDATORY ("frontend unchanged")
3. `build_edgar_rate_limit_status()` must emit **every field** the frontend
   `normalizeEdgarRateLimit` (`frontend/lib/thirteenfAdmin.js`) reads: `mode`,
   `request_delay_s`, `max_retries`, `window_seconds`, `recent_request_count`,
   `estimated_capacity`, `remaining_estimated_capacity`, `global_pause_until`.
   Walk it field by field — if any are missing the panel silently degrades.
4. Confirm `git diff main...HEAD` touches **no** `frontend/` file, so the
   "frontend unchanged" claim is literally true.
5. `edgar_block_alert` is derived as `recent_403 > 0 or recent_429 > 0`;
   `request_delay_s` is `1 / rate_per_sec` with a divide-by-zero guard
   (`rate_per_sec == 0 → None`). Confirm.
6. `global_pause_until` now carries Rate Guard's **real** pause (it was always
   `None` since PR 2). Confirm it is passed through unmodified from the snapshot.

### C. Failure-mode handling — MANDATORY
7. Rate Guard unreachable → `RateGuardClient.metrics()` raises
   `RateGuardFetchError` → `build_edgar_rate_limit_status()` propagates it →
   the `edgar-rate-limit` endpoint returns **HTTP 503** (not 500, not a
   misleading all-zeros panel). Confirm.
8. The scheduler's 13F alert run catches `RateGuardFetchError`, sets
   `rate_limit_status = None`, and `evaluate_13f_alerts` tolerates `None`
   (`if edgar_rate_limit_status and …`) — a Rate Guard outage must not crash the
   alert run or fire a false `SEC_EDGAR_BLOCK_ALERT`. Confirm.

### D. `RateGuardClient.metrics()` & the `_base_url` refactor
9. `metrics(upstream)` issues `GET /v1/metrics` (with `?upstream=` when given),
   unwraps `{"upstreams": {…}}`, and maps unreachable / non-200 / malformed-JSON
   to `RateGuardFetchError`; an unset `RATE_GUARD_URL` raises before any call.
10. `_endpoint()` was refactored to `_base_url()` (shared by `fetch` and
    `metrics`). Confirm `fetch` still targets `{base}/v1/fetch` and the existing
    `fetch` tests are unaffected.

### E. Client lifecycle (the PR-3 C6 regression check)
11. `build_edgar_rate_limit_status()` must use `RateGuardClient` as a context
    manager (or otherwise `close()` it) — PR 3's C6 finding was an unclosed
    client. Confirm this PR does not reintroduce that leak.

### F. rate-guard `max_retries`
12. `gateway.metrics()` adds `max_retries` from the upstream config
    (`u.max_retries`). Confirm it is the configured value and the Rate Guard
    test suite stays green.

### G. Tests
13. Removed: the per-process recording tests
    (`test_fetches_are_recorded_for_the_rate_limit_status`,
    `test_edgar_rate_limit_status_counts_recorded_requests`) — confirm they
    targeted deleted behaviour, not lost coverage.
14. Added / rewritten: `RateGuardClient.metrics` tests; the endpoint test
    (now monkeypatching `RateGuardClient.metrics`); the Rate-Guard-outage → 503
    test; the `build_edgar_rate_limit_status` adapter test;
    `test_scheduler_alignment.py` repointed to monkeypatch
    `thirteenf_admin_dashboard.build_edgar_rate_limit_status` (it is
    late-imported in the scheduler). Assess coverage; note gaps.

### H. Scope / deferrals
15. Confirm deliberate: the panel stays EDGAR-only (a multi-upstream view is a
    `docs/BACKLOG.md` follow-up); `EdgarClient` still carries its own `_fetch`
    copy (the existing BACKLOG migration item — now that the recording is gone,
    `EdgarClient._fetch` and `RateGuardClient.fetch` are near-identical);
    unused `EDGAR_*` rate settings are left in `config.py`.

## Verification
- `docker compose run --rm --no-deps api pytest -q` — backend green (~893).
- `cd rate-guard && pip install -r requirements-dev.txt && pytest -q` — Rate
  Guard green (19).
- `git diff main...HEAD` — scope; no DB migration; **no `frontend/` changes**.

## Pass bar
Approve only if: A (the deletion is complete, nothing dangles); B (the adapter
emits every field the frontend reads, and `git diff` proves no frontend change);
C (a Rate Guard outage is a clean 503 / skipped alert, never a crash or false
alarm); E (no unclosed-client regression). D / F / G / H findings are recorded.
The bar is "the admin panel and 13F alerting read Rate Guard's authoritative
metrics, degrade safely when Rate Guard is down, and the rollout's dead code is
gone — safe to auto-deploy to prod."
