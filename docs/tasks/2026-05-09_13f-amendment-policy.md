# 13F-1B-06: Amendment Policy and Active Filing Switching

## Goal
Implement amendment classification and safe active filing replacement.

## Scope (In)
- Parse amendment type and raw value.
- RESTATEMENT applies only after successful parse.
- Non-RESTATEMENT amendments become amendments_pending/needs review.
- NEW HOLDINGS requires admin activate_as_original.
- Same manager/period multiple original filings use latest accepted_at; ambiguous ordering requires admin review.
- Admin pending amendments list and resolve endpoint.

## Scope (Out)
- Partial amendment merge logic.
- UI implementation.

## Files to Change
- `backend/app/edgar/parsers/primary_doc.py`
- `backend/app/services/thirteenf_filing_detail.py`
- `backend/app/services/thirteenf_holdings_ingest.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_amendment_policy.py`

## Test Plan
- Run `docker compose exec api pytest -q tests/unit/test_13f_amendment_policy.py`

## Execution Notes
- Implemented `<amendmentType>` extraction in `primary_doc.py`.
- Updated `thirteenf_filing_detail.py` with `_apply_amendment_policy` to handle tie-breaking for original filings and `amendments_pending` routing.
- Switched `is_active_for_manager_period` atomically within Phase 2 commit block in `thirteenf_holdings_ingest.py`.
- Added `POST /api/v1/admin/13f/amendments/{accession_no}/resolve` and wired it into dashboard service.
- Fixed constraints around `is_latest_for_period` in test fixtures.
- Test suite passing (`test_13f_amendment_policy.py`).
