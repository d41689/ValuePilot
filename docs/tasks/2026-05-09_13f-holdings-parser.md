# 13F-1B-04: HR/HR-A Cover Page and Information Table Parser

## Goal / Acceptance Criteria

- Parse cover page fields for combination reports: `other_managers_included` (list of managers whose holdings are included).
- Extend `HoldingRow` parser with `source_row_index`, `value_raw_str`, and `other_managers_raw` before any filtering.
- Normalize value units via G2-approved `infer_value_unit` rules; store `value_raw`, `value_unit_raw`, `value_parse_rule`, `value_usd`.
- Normalize `investment_discretion`: `SOLE→SOLE`, `DEFINED/DFND→DFND`, `OTR/OTHER/SHARED→OTR`.
- Compute `holding_attribution_status`: `SOLE→direct`, `OTR→shared`, `DFND+parseable otherManagers→reported_for_other`, `DFND+empty→unresolved`.
- Compute `holding_row_fingerprint` from raw-row anchored values (source_row_index, value_unit_raw, raw investment_discretion, etc.).
- Two-phase ParseRun13F: create `running`, insert holdings, switch to `succeeded+is_current=True`.
- `portfolio_weight_pct` remains NULL in MVP 1B.
- `cusip_mapping_status=pending_mapping` for all new holdings.
- All tests pass under Docker.

## Scope In

- Parser extension: `other_managers_included` on `PrimaryDocSummary`, `source_row_index`/`value_raw_str`/`other_managers_raw` on `HoldingRow`.
- Service update: write `other_managers_included` on filing in `thirteenf_filing_detail.py`.
- New service module `thirteenf_holdings_ingest.py` with normalization, attribution, fingerprint, and two-phase ingest.
- Unit tests covering parser extensions, value unit normalization, attribution, fingerprint stability, and DB ingest behavior.

## Scope Out

- OpenFIGI enrichment (13F-1B-07).
- Amendment activation (13F-1B-06).
- Two-phase parse run with reparse semantics (13F-1B-05).
- `portfolio_weight_pct` computation (MVP 2).
- Frontend.

## PRD References

- §6.2 holding_row_fingerprint definition
- §7.1 filing fields (other_managers_included)
- §7.2 holding fields (value_usd, investment_discretion, holding_attribution_status)
- §18.1-§18.2 MVP 1B holding fields

## Files Changed

- `backend/app/edgar/parsers/primary_doc.py`
- `backend/app/edgar/parsers/infotable.py`
- `backend/app/services/thirteenf_filing_detail.py`
- `backend/app/services/thirteenf_holdings_ingest.py` (new)
- `backend/tests/unit/test_13f_holdings_parser.py` (new)

## Progress Notes

- 2026-05-09: Task created after 13F-1B-03 completed.
- 2026-05-09: Wrote red tests covering all dev plan test cases.
- 2026-05-09: Implemented parser extensions, service, and ingest module.
- 2026-05-09: Docker verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_holdings_parser.py` → 29 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_holdings_parser.py tests/unit/test_13f_nt_handler.py tests/unit/test_13f_filing_detail.py tests/unit/test_13f_parsers.py tests/unit/test_13f_value_units.py tests/unit/test_13f_mvp1b_schema.py tests/unit/test_13f_daily_index_sync.py tests/unit/test_13f_job_scheduler.py` → 111 passed.
  - `docker compose exec api pytest -q tests/unit` → 432 passed.
- 2026-05-09: Tech Lead review passed. Non-blocking: session.commit() inside service is "slightly heavy" but safe given is_current contract from 13F-1B-03. Task confirmed complete.
