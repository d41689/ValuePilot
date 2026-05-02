# Document Register Ticker Sort

## Goal / Acceptance Criteria

- Rename the `/documents` Document Register table header from `Companies` to `Ticker`.
- Sort document rows by ticker and report date so reports for the same ticker are grouped together.
- Preserve existing company/ticker payload shape and active report behavior.

## Scope

In:
- Backend document list ordering.
- Frontend table header copy.
- Unit test coverage for ordering.

Out:
- Schema changes.
- New filtering/search controls.
- Changing the document API response fields.

## Files to Change

- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/app/(dashboard)/documents/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_documents_api.py`
- `docker compose exec web npm run lint`

## Notes

- 2026-05-02: Started implementation. Multi-company documents will sort by their first displayed ticker because the existing row displays a comma-separated ticker list.
- 2026-05-02: Backend `/documents` output now sorts by first displayed ticker, then `report_date`, then document id.
- 2026-05-02: Frontend Document Register header changed from `Companies` to `Ticker`.

## Verification

- 2026-05-02: `docker compose exec api pytest -q tests/unit/test_documents_api.py` passed (`21 passed`).
- 2026-05-02: `docker compose exec web npm run lint` passed.

## Contract Checklist

- Response payload shape is unchanged.
- Sorting uses existing normalized stock identity through document `companies`.
- No schema changes.
- No raw SQL from user input.
