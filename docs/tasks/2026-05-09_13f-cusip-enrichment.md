# 13F-1B-07: CUSIP Validation, OpenFIGI Mapping, Temporal Mapping, and Advisory Lock

## Goal
Implement MVP 1B CUSIP enrichment with temporal validity and conservative auto-confirm rules.

## Scope (In)
- CUSIP validation: all-zero, short length, invalid format.
- OpenFIGI client with independent rate limiter and 30-day cache.
- Auto-confirm only when all PRD conditions pass.
- `needs_review` for ambiguous cases.
- Temporal lookup by quarter.
- Application-level overlap check under canonical CUSIP 64-bit advisory lock.
- Update `holdings_13f.stock_id` and `holdings_13f.cusip_mapping_status`.
- Admin CUSIP mapping list/create/patch endpoints.

## Scope (Out)
- Dataroma CUSIP source.
- Corporate action management UI.

## Files to Change
- `backend/app/models/institutions.py`
- `backend/app/services/cusip_enrichment.py`
- `backend/app/openfigi/client.py`
- `backend/app/api/v1/endpoints/thirteenf_cusip.py`
- `backend/tests/unit/test_13f_cusip_enrichment.py`

## Test Plan
- Run `docker compose exec api pytest -q tests/unit/test_13f_cusip_enrichment.py`

## Execution Notes
- Implemented `is_valid_cusip` helper in `cusip_validation.py`.
- Wrote `OpenFigiClient` using `httpx` with `stub_mapping` fallback when `OPENFIGI_API_KEY` is not present.
- Replaced the MVP 3 Dataroma matching logic in `cusip_enrichment.py` with the PRD-compliant OpenFIGI implementation.
- Implemented `pg_try_advisory_xact_lock` hash lock and `_has_overlap` to strictly manage temporal intervals.
- `evaluate_openfigi_matches` correctly auto-confirms Single Exact Match for US Common Stock.
- Updated `thirteenf_admin_dashboard.py` and `thirteenf_admin.py` to provide the required endpoints for listing/creating/updating manual CUSIP overrides.
- All unit tests pass in Docker.
