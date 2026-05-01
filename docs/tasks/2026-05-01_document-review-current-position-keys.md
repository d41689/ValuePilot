# Document Review Current Position Keys

## Goal / Acceptance Criteria

- `/documents/{id}/review` must not emit duplicate React keys when Current Position has repeated period end dates.
- Current Position column labels remain unchanged for users.
- Cell keys remain stable and unique per row/column.

## Scope

In:
- Frontend document review Current Position table model.
- Frontend unit test for duplicate period end date columns.

Out:
- Parser changes.
- Database or ingestion changes.
- Current Position date semantics changes.

## Files to Change

- `frontend/lib/documentReview.js`
- `frontend/lib/documentReview.test.js`

## Test Plan

- `docker compose exec web node --test lib/documentReview.test.js`

## Notes

- 2026-05-01: Started implementation. FICO document 576 has repeated `2025-12-31` period end dates in Current Position, which makes React keys collide when the table uses date-only keys.
- 2026-05-01: Added a failing unit test for duplicate Current Position period end dates, then updated table column keys to include period date/label/index while preserving labels.
- 2026-05-01: Verification passed:
  - `docker compose exec web node --test lib/documentReview.test.js`
  - `docker compose exec web node --test lib/uiStandard.test.js`
  - `docker compose exec web npm run lint`

## Contract Checklist

- [x] `metric_facts` contracts are not touched.
- [x] No raw SQL from user input.
- [x] No eval/exec formula execution.
- [x] Lineage behavior is unchanged.
- [x] `is_current` semantics are unchanged.
