# 13F-1B-05: Parse Run Audit, Reparse, Watchdog, and Idempotent Ingestion

## Goal / Acceptance Criteria

Implement execution-plan task `13F-1B-05`: audit-preserving parse execution and reparse semantics.

Acceptance criteria:
- `reparse_accession(session, accession_number)` creates a new current parse_run and retains old holdings.
- Stage 2 failure (holdings insert crash) leaves the old current parse_run unchanged.
- Failed parse_run persists with an `error` field set.
- Watchdog marks stale **running** parse_runs (expired lease) as `abandoned`.
- A succeeded accession is skipped unless `parser_version` or `fingerprint_version` requires reparse.
- A succeeded accession is reparsed when `fingerprint_version` does not match the current version constant.
- Idempotent skip/retry is tested independently of amendment activation and CUSIP enrichment.
- No DELETE of old holdings is required for reparse.
- Product queries can rely on `parse_runs.is_current=true`.

## Scope In

- `thirteenf_holdings_ingest.py`: add `reparse_accession` service function.
- `thirteenf_job_worker.py`: add `mark_stale_parse_runs_abandoned` watchdog helper.
- `thirteenf_admin_dashboard.py`: wire `reparse_accession` into `_execute_ingest_job` for `reprocess_amendment` and add `reparse_accession` job type.
- `api/v1/endpoints/thirteenf_admin.py`: expose `POST /admin/13f/filings/{accession_no}/reparse` endpoint.
- `tests/unit/test_13f_parse_run_audit.py`: new test file, TDD first.

## Scope Out

- Amendment active filing replacement (13F-1B-06).
- Admin UI for parse run history (13F-1C2-01).
- OpenFIGI enrichment (13F-1B-07).
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §6.1–§6.5 parse_run semantics, reparse, idempotent ingestion.
- `docs/prd/13f_automation_and_resilience_prd.md` §7.3 query contract (is_current).
- `docs/prd/13f_automation_and_resilience_prd.md` §12.4 parse_run timeout and abandoned status.
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2 abandoned parse_run criterion.
- `docs/tasks/2026-05-09_13f-automation-development-plan.md` `13F-1B-05`.

## Files To Change

- `backend/app/services/thirteenf_holdings_ingest.py`
- `backend/app/services/thirteenf_job_worker.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_parse_run_audit.py` (new)
- `docs/tasks/2026-05-09_13f-parse-run-audit-reparse.md`

## Test Plan

Docker only:
- `docker compose exec api pytest -q tests/unit/test_13f_parse_run_audit.py`
- `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Task created. Dependencies confirmed: 13F-1B-01 (schema), 13F-1B-04 (holdings ingest), 13F-1A-05 (job worker) are all complete with green tests.
- 2026-05-09: TDD red phase — wrote 8 failing tests in `tests/unit/test_13f_parse_run_audit.py`.
- 2026-05-09: Implemented `_do_ingest_holdings` (savepoint-based two-phase ingest), `reparse_accession`, and `ingest_if_needed` in `thirteenf_holdings_ingest.py`.
- 2026-05-09: Implemented `mark_stale_parse_runs_abandoned` watchdog in `thirteenf_job_worker.py`.
- 2026-05-09: Added `POST /admin/13f/filings/{accession_no}/reparse` to `thirteenf_admin.py`.
- 2026-05-09: All 8 new tests green; full suite 440 passed (0 failures).
- 2026-05-09: **Tech Lead Review — CHANGES_REQUESTED** (2 blocking findings):
  1. Dashboard wiring mismatch: `_execute_ingest_job` still used legacy `ingest_filing_holdings`.
  2. Missing `reparse_accession` job type in `_JOB_LOCK_BUILDERS`.
- 2026-05-09: **Fix applied:**
  - Rewired `_execute_ingest_job` in `thirteenf_admin_dashboard.py`:
    - `reprocess_amendment` + `reparse_accession` → `reparse_accession()` service method.
    - `ingest_holdings` (bulk quarterly) → `ingest_if_needed()` with `load_body()`.
    - Filter changed from `raw_infotable_doc_id.is_(None)` to `.isnot(None)` (only process filings with stored infotables).
  - Added `reparse_accession` to `_JOB_LOCK_BUILDERS` and `_execute_job` dispatcher.
  - Fixed `reparse_accession()` to use `load_body` from `app.edgar.fetcher` (was broken reference to non-existent `file_storage.read_body_path`).
  - Deprecated legacy `ingest_filing_holdings` in `edgar_ingestion.py` with `DeprecationWarning`.
  - Full test suite 440 passed (0 failures).

## Contract Gate (§Phase 5)

- [x] `metric_facts`/`holdings_13f` queried only via `is_current=True` parse_run (product query contract preserved)
- [x] No raw SQL from user input
- [x] No eval/exec
- [x] Lineage fields present on all holdings (accession_number, parse_run_id, filing_id)
- [x] `is_current` semantics preserved — only one parse_run is current per accession at any time
- [x] Failed parse_runs persisted with `error` field for audit trail
- [x] Old holdings retained (no DELETE) on reparse failure
- [x] Watchdog timeout is configurable (default 10 min, matches PRD §12.4)
- [x] Dashboard fully wired — no production path uses legacy destructive ingest

## Status: DONE (pending re-review)
