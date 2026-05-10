# 13F-1B-03: 13F-NT Header Handling and Query Contract Enforcement

## Goal / Acceptance Criteria

- Parse `other_managers_reporting` from 13F-NT cover page XML (`otherManagersInfo` elements), preserving `name`, `cik`, and `file_number` as distinct JSON keys when present.
- Store parsed `other_managers_reporting` on the `filings_13f` record for NT filings.
- Confirm NT ingestion via `ingest_accession_filing_detail` creates no `parse_runs` and no `holdings_13f` rows.
- Add `active_hr_holdings_query(session)` — a service-layer query guard that enforces the PRD §7.3 contract: only active HR/HR-A filings joined to current parse_runs enter the holdings query path.
- Add `nt_only_manager_ids(session, quarter)` — returns manager_ids with NT active filings but no HR/HR-A active filing for that quarter; used as an exclusion filter in the future readiness expected-filers denominator.
- All tests pass under Docker.

## Scope In

- Parser extension: `other_managers_reporting` field on `PrimaryDocSummary`.
- Service extension: write `other_managers_reporting` on NT filings.
- New service module `thirteenf_holdings_query.py` with the query guard.
- Unit tests covering parser, ingest, query guard, and NT exclusion.

## Scope Out

- Full readiness service (13F-1C1-01).
- Amendment replacement.
- Cross-manager NT attribution or merge.
- Frontend.
- PRD changes.

## PRD References

- §2.2 13F-NT semantics
- §4.4 step 7 NT ingestion rules
- §7.1 filing fields (`other_managers_reporting`)
- §7.3 holdings query contract
- §10.1 expected filers denominator

## Files Changed

- `backend/app/edgar/parsers/primary_doc.py`
- `backend/app/services/thirteenf_filing_detail.py`
- `backend/app/services/thirteenf_holdings_query.py` (new)
- `backend/tests/unit/test_13f_nt_handler.py` (new)

## Progress Notes

- 2026-05-09: Task created. Started after Tech Lead approval of 13F-1B-02.
- 2026-05-09: Wrote red tests: parser unit tests, ingest DB tests, query guard DB tests.
- 2026-05-09: Implemented parser extension, service extension, and query guard.
- 2026-05-09: Docker verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_nt_handler.py` → 11 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_nt_handler.py tests/unit/test_13f_filing_detail.py tests/unit/test_13f_daily_index_sync.py tests/unit/test_13f_job_scheduler.py tests/unit/test_13f_parsers.py tests/unit/test_13f_mvp1b_schema.py` → 75 passed.
  - `docker compose exec api pytest -q tests/unit` → 403 passed.
