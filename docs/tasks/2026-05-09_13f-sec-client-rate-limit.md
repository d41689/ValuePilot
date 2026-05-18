# 13F SEC Client Rate Limit

## Goal / Acceptance Criteria

Implement execution-plan task `13F-1A-03`: establish a PRD-compliant shared SEC/EDGAR client path with a global 10 requests/second limiter, User-Agent construction from `SEC_CONTACT_EMAIL`, fail-fast configuration validation, retry/backoff behavior, and 429/403 detection for health summaries.

Acceptance criteria:
- Missing `SEC_CONTACT_EMAIL` fails before request execution.
- SEC client sends a User-Agent containing the configured contact email.
- The global EDGAR limiter is invoked for every SEC request path.
- Retry policy stops after configured max retries.
- 403/429 responses are recorded in health/status summaries.
- Tests mock network calls and do not access external SEC endpoints.

## Scope

In:
- `backend/app/edgar/client.py` hardening.
- `backend/app/core/config.py` SEC contact settings.
- Focused unit tests for config validation, User-Agent, rate limiter invocation, retries, and 403/429 status reporting.
- Task log progress and verification notes.

Out:
- Daily index parsing.
- Filing/holdings parser implementation.
- OpenFIGI client.
- Production alert delivery beyond status/health hooks.
- Frontend UI.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §3.5 CIK search and SEC endpoints.
- `docs/prd/13f_automation_and_resilience_prd.md` §4.5 rate limiting and stability.
- `docs/prd/13f_automation_and_resilience_prd.md` §12 job reliability context.
- `docs/prd/13f_automation_and_resilience_prd.md` §15.2 429/403 alert condition.

## Files To Change

- `backend/app/core/config.py`
- `backend/app/edgar/client.py`
- `backend/tests/unit/test_edgar_client.py`
- `docs/tasks/2026-05-09_13f-sec-client-rate-limit.md`

## Test Plan

Docker only:
- `docker compose exec api pytest -q tests/unit/test_edgar_client.py`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Started `13F-1A-03` after `13F-1A-02` review fixes were committed.
- 2026-05-09: Existing `app.edgar.client.EdgarClient` already centralizes EDGAR HTTP requests, retry, token-bucket limiting, and request event history. This task will harden it against the new PRD contract rather than introduce a second client.
- 2026-05-09: Wrote failing tests first for missing `SEC_CONTACT_EMAIL`, User-Agent construction, 10 req/s default, limiter invocation for GET/HEAD, max retry stop, and 403/429 health-summary detection.
- 2026-05-09: Added `SEC_CONTACT_EMAIL` and `EDGAR_REQUESTS_PER_SECOND` settings; changed EDGAR default rate to 10 requests/second while preserving legacy delay fallback.
- 2026-05-09: Hardened `EdgarClient` to build User-Agent from `SEC_CONTACT_EMAIL`, fail before request execution if missing, support injected mock HTTP clients, and expose recent 403/429 counts plus `edgar_block_alert` in `edgar_rate_limit_status`.
- 2026-05-09: Aligned retry defaults with PRD §4.5: max retries default to 5 and retry backoff is capped at 300 seconds.
- 2026-05-09: Updated existing tests that intentionally construct `EdgarClient` to set `SEC_CONTACT_EMAIL`; this is expected now that the fail-fast contract is enforced.
- 2026-05-09: Verification passed:
  - `docker compose exec api pytest -q tests/unit/test_edgar_client.py` (`7 passed`)
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` (`50 passed`)
  - `docker compose exec api pytest -q tests/unit` (`325 passed in 39.00s`)
- 2026-05-09: Contract check: no daily index parsing, no SEC network access in tests, no OpenFIGI, no parser/holdings implementation, no frontend, no PRD edits.
- 2026-05-09: Tech Lead review follow-up accepted:
  - Removed repeated `build_sec_user_agent()` calls inside the retry loop; `_request()` now validates once before any request attempt, preserving fail-fast for injected mock clients.
  - Added coverage that `EDGAR_USER_AGENT` overrides still include `SEC_CONTACT_EMAIL`.
  - Added API wiring coverage that 403/429 health fields are passed through by the admin rate-limit endpoint.
- 2026-05-09: Tech Lead review follow-up deferred:
  - Process-local vs IP-global rate limiting, 429 recovery back to 10 req/s, and global pause enforcement across concurrent threads are deferred to later multi-worker/production scheduler hardening.
- 2026-05-09: Post-review verification passed:
  - `docker compose exec api pytest -q tests/unit/test_edgar_client.py` (`8 passed`)
  - `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` (`50 passed`)
  - `docker compose exec api pytest -q tests/unit` (`326 passed in 38.50s`)
