# 2026-05-21 — Rate Guard PR 4/4: admin panel reads Rate Guard /v1/metrics

Design: `docs/tasks/2026-05-20_rate-guard-design.md` §7, §14 (PR 4 — final).
Branch: `claude/rate-guard-pr4-admin-metrics`.

## Goal / Acceptance Criteria

- The admin `edgar-rate-limit` panel and the 13F 403/429 block alerting read
  **Rate Guard's `GET /v1/metrics`** — the authoritative cross-process budget —
  instead of `EdgarClient`'s per-process `_REQUEST_EVENTS`.
- `global_pause_until` becomes **real** (Rate Guard owns the 429/503 pause); it
  was always `None` since PR 2.
- The per-process recording in `edgar/client.py` (`_REQUEST_EVENTS`,
  `_record_request`, `edgar_rate_limit_status`) is deleted — it is now dead.
- Frontend unchanged: the backend response keeps the same field names, so
  `normalizeEdgarRateLimit` works as-is; a Rate-Guard outage surfaces as a 503
  (the panel's existing query-error state).
- Canonical CI (backend + Rate Guard) green.

## Scope

In:
- `rate-guard/app/gateway.py` — `metrics()` snapshot gains `max_retries`
  (the panel shows Rate Guard's real retry budget).
- `backend/app/rate_guard/client.py` — `RateGuardClient.metrics(upstream)` →
  `GET /v1/metrics`; small `_base_url()` refactor shared with `_endpoint()`.
- `backend/app/services/thirteenf_admin_dashboard.py` —
  `build_edgar_rate_limit_status()` calls Rate Guard (`upstream="edgar"`) and
  adapts the snapshot into the panel shape (`mode`, `request_delay_s`,
  `edgar_block_alert` derived from 403/429, real `global_pause_until`, …). It
  uses `RateGuardClient` as a context manager (closes the httpx client — the
  PR 3 C6 lesson) and propagates `RateGuardFetchError`.
- `backend/app/api/v1/endpoints/thirteenf_admin.py` — the `edgar-rate-limit`
  endpoint maps `RateGuardFetchError` → HTTP 503.
- `backend/app/services/scheduler.py` — the 13F alert run sources the
  rate-limit status from `build_edgar_rate_limit_status()`; on
  `RateGuardFetchError` it passes `None` (alerting already tolerates `None`).
- `backend/app/edgar/client.py` — delete `_REQUEST_EVENTS`,
  `_record_request`, `edgar_rate_limit_status`, and the `_fetch` recording
  calls; drop the now-unused imports.
- Tests: `RateGuardClient.metrics`, the rewritten `build_edgar_rate_limit_status`
  (Rate Guard success + unreachable → 503), updated admin-dashboard and
  edgar-client tests.

Out:
- A multi-upstream (edgar + openfigi + dataroma) metrics panel — Rate Guard now
  tracks all three, but the admin panel stays EDGAR-focused per the design
  scope. Recorded in `docs/BACKLOG.md`.
- Migrating `EdgarClient` onto the shared `RateGuardClient` — still the separate
  `docs/BACKLOG.md` follow-up from PR 3.

## Behaviour notes

- `RateGuardClient.metrics("edgar")` returns the edgar upstream snapshot dict
  (`recent_request_count`, `recent_403_count`, `recent_429_count`,
  `cache_hits`/`cache_misses`, `global_pause_until`, `rate_per_sec`,
  `estimated_capacity`, `remaining_estimated_capacity`, `max_retries`,
  `window_seconds`); raises `RateGuardFetchError` on any failure.
- The frontend `normalizeEdgarRateLimit` reads `mode`, `request_delay_s`,
  `max_retries`, `window_seconds`, `recent_request_count`,
  `estimated_capacity`, `remaining_estimated_capacity`, `global_pause_until` —
  all preserved by the adapter, so no frontend change.

## Test plan

- `docker compose run --rm --no-deps api pytest -q` — backend green.
- `cd rate-guard && pytest -q` — Rate Guard green.
- New / updated tests cover `RateGuardClient.metrics`, the adapter on Rate
  Guard success and on a Rate-Guard outage (→ 503), and the removal of the
  per-process recording.
