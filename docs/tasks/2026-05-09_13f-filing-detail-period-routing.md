# 13F-1B-02 Filing Detail Fetch and Period Routing

## Goal / Acceptance Criteria

- Fetch 13F filing detail/header for HR, HR/A, and NT accession jobs through the shared SEC client.
- Persist raw filing/header content via `raw_source_documents` and link it to `filings_13f.raw_filing_url` / `raw_primary_doc_id`.
- Extract and persist filing metadata: `periodOfReport`, `accepted_at`, `form_type`, accession number, `form_spec_version`, and `xml_schema_version`.
- Normalize report quarter from `periodOfReport`, never from sync date, filing date, daily index date, or current system date.
- Apply PRD period anomaly handling:
  - missing period -> `parse_status=needs_review`, `PERIOD_MISSING`
  - invalid period -> `parse_status=failed`
  - eligible +/- 1-2 day HR/HR-A period -> normalize to nearest quarter end with `PERIOD_WEEKEND_ADJUSTED`
  - ineligible +/- 1-2 day period -> `needs_review`, `PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE`
- Calculate `official_filing_deadline` using quarter end + 45 calendar days adjusted to the next EDGAR operational business day.
- Upsert filing records idempotently by accession number.

## Scope In

- Filing detail/header URL resolution and raw document persistence.
- Primary document metadata parser improvements.
- Period routing helper and deadline helper.
- `ingest_accession` job execution path for filing metadata only.
- Focused unit tests and Docker verification.

## Scope Out

- Information table holdings parser implementation.
- Holdings persistence, CUSIP enrichment, OpenFIGI calls.
- Amendment replacement / activation logic.
- Frontend changes.
- PRD changes.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §2.1-§2.4
- `docs/prd/13f_automation_and_resilience_prd.md` §4.4
- `docs/prd/13f_automation_and_resilience_prd.md` §5.1-§5.3
- `docs/prd/13f_automation_and_resilience_prd.md` §6.1
- `docs/prd/13f_automation_and_resilience_prd.md` §7.1

## Files To Change

- `backend/app/edgar/parsers/primary_doc.py`
- `backend/app/services/thirteenf_filing_detail.py` (new)
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_filing_detail.py` (new)
- `docs/tasks/2026-05-09_13f-filing-detail-period-routing.md`

## Test Plan

- Red/green focused tests:
  - `docker compose exec api pytest -q tests/unit/test_13f_filing_detail.py`
- Regression slice:
  - `docker compose exec api pytest -q tests/unit/test_13f_daily_index_sync.py tests/unit/test_13f_job_scheduler.py tests/unit/test_13f_parsers.py tests/unit/test_13f_mvp1b_schema.py`
- Full unit regression if feasible:
  - `docker compose exec api pytest -q tests/unit`

## Progress Notes

- 2026-05-09: Started after 13F-1B-01 migration review approval. Accepted review NB items as downstream writer invariants: new parser paths must explicitly set `accession_number`, must write non-null `parse_run_id` for future holdings, and product holdings queries must join current `parse_runs`.
- 2026-05-09: Added red tests for accession detail ingest, period routing, missing/invalid periods, official deadline adjustment, metadata extraction, and idempotent accession upsert.
- 2026-05-09: Implemented metadata-only `ingest_accession` path through `thirteenf_filing_detail`; it fetches and stores the raw filing detail but does not fetch information tables or write holdings.
- 2026-05-09: `filings_13f.period_of_report` is a legacy non-null field, so missing/invalid period rows use a non-product placeholder date while leaving `quarter_end_date` and `report_quarter` null and `parse_status` non-product-facing (`needs_review`/`failed`).
- 2026-05-09: Docker verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_filing_detail.py` -> 7 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_filing_detail.py tests/unit/test_13f_daily_index_sync.py tests/unit/test_13f_job_scheduler.py tests/unit/test_13f_parsers.py tests/unit/test_13f_mvp1b_schema.py` -> 61 passed.
  - `docker compose exec api pytest -q tests/unit` -> 389 passed.
