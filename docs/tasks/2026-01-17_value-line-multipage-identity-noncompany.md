# Task: Handle non-company pages and expand identity parsing for Value Line multi-page PDFs

## Goal / Acceptance Criteria
- Multi-page Value Line reparse returns `parse_status=parsed` when all company pages parse successfully.
- Industry/non-company pages are marked as `unsupported_template` (or skipped) and do not count as failures.
- Identity extraction supports `TSE/TSX/PNK/NSDQ` and tickers with `.TO` suffix.
- Documents list Pages column shows `parsed / total` (already shipped) and parsed count reflects company pages.

## Scope
### In Scope
- Expand identity regex patterns and exchange normalization.
- Adjust parse_status logic to exclude industry pages from failure count.
- Add tests for identity extraction and multi-page reparse status.

### Out of Scope
- Schema migrations.
- UI changes beyond pages count display.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md`
- `docs/prd/value-pilot-prd-v0.1-multipage.md`

## Files To Change
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/services/ingestion_service.py`
- `backend/tests/unit/test_ingestion.py`
- `backend/tests/unit/test_reparse_existing_document.py`
- `docs/tasks/2026-01-17_value-line-multipage-identity-noncompany.md`

## Test Plan (Docker)
- `docker compose exec api pytest -q tests/unit/test_ingestion.py`
- `docker compose exec api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec api pytest -q`

## Notes / Decisions
- Treat non-company pages as `unsupported_template` and exclude them from parse_status counts.
- Exchange normalization expanded to map `NSDQ` -> `NDQ` and `TSX` -> `TSE`, with `.TO` ticker support.
- Parser check on `VL_20260109_VLIS_multi.pdf`: total pages 127; company candidate pages 120; identity extracted for all 120; non-company pages 7 (pages 39, 56, 74, 81, 94, 103, 112).

## Decision Summary
- Container `parsed` is defined by company pages only.
- Industry summary pages use `status=unsupported_template` with `error_code=unsupported_template`.
- Supported exchanges include NYSE/NDQ/NAS plus TSX/TSE/PNK, with `NSDQ` aliased to `NDQ`.
- Ticker suffixes supported: `.TO`.

## Verification
- `docker compose exec -T api pytest -q tests/unit/test_ingestion.py`
- `docker compose exec -T api pytest -q tests/unit/test_reparse_existing_document.py`
- `docker compose exec -T api pytest -q`
- Results: 36 passed, 1 warning (FastAPI deprecation).
