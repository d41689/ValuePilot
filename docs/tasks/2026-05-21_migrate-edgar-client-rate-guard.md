# 2026-05-21 — Migrate EdgarClient onto the shared RateGuardClient

Backlog item: `docs/BACKLOG.md` → "EdgarClient not yet migrated onto the shared
RateGuardClient" (raised by Rate Guard PR 3, reinforced by PR 4).
Branch: `claude/migrate-edgar-client-rate-guard`.

## Goal / Acceptance Criteria

- `EdgarClient` becomes a thin wrapper over `RateGuardClient` (like
  `OpenFigiClient` / `DataromaClient` since PR 3) — its duplicated `_fetch` /
  `_fetch_endpoint` / `_rate_guard_error_detail` / `EdgarFetchError` /
  `_RATE_GUARD_TIMEOUT_S` are deleted. After Rate Guard PR 4 removed the
  per-process recording, `EdgarClient._fetch` and `RateGuardClient.fetch` were
  near-identical.
- The public API (`get` / `head` / `close` / context manager / `BASE`
  constants) is unchanged — the 8 `EdgarClient()` call sites need no edits.
- All three upstream clients now share one `POST /v1/fetch` implementation.

## Decision — drop `EdgarFetchError`, use `RateGuardFetchError`

The backlog item said "unify `EdgarFetchError` with `RateGuardFetchError`
(alias or subclass)". Since this is a de-cruft refactor, `EdgarFetchError` is
**removed** rather than kept as an alias — one egress error type, no duplicate
name. `RateGuardFetchError` is already a `RuntimeError` subclass carrying
`.status_code`, so it is a drop-in replacement.

## Scope

In:
- `backend/app/edgar/client.py` — rewrite: `EdgarClient` holds a
  `RateGuardClient`; `get`/`head` delegate with `upstream="edgar"`. Delete
  `EdgarFetchError`, `_fetch`, `_fetch_endpoint`, `_rate_guard_error_detail`,
  `_RATE_GUARD_TIMEOUT_S`. Keep the `BASE` / `EFTS_BASE` / `DATA_BASE` host
  constants.
- `backend/app/services/thirteenf_daily_sync.py` — catch `RateGuardFetchError`
  instead of `EdgarFetchError` (the daily-index 404 classification — PR 2's B3).
- `backend/tests/unit/test_13f_daily_index_sync.py` — `FakeEdgarClient` raises
  `RateGuardFetchError` (keeps the B3 regression guard faithful).
- `backend/tests/unit/test_edgar_client.py` — slimmed to wrapper tests
  (delegation with `upstream="edgar"`, GET/HEAD, error propagation, the host
  constants); the deep `/v1/fetch` error-path coverage already lives in
  `test_rate_guard_client.py`.
- `docs/BACKLOG.md` — remove the resolved item.

Out:
- No call-site changes (public API preserved); no behaviour change.

## Test plan

- `docker compose run --rm --no-deps api pytest -q` — backend green.
- The `thirteenf_daily_sync` 404 tests still exercise the typed-exception path
  (now `RateGuardFetchError`) — the PR 2 B3 guard stays intact.
