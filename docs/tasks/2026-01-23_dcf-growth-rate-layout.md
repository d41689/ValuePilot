# Task: DCF Growth Rate layout alignment

## Goal / Acceptance Criteria
- Growth Stage → Growth Rate label and input are on the same line.
- Growth Rate options (Sales/Cash Flow/Earnings) appear below the input and right-aligned.

## Scope
**In**
- Frontend layout changes in DCF page only.

**Out**
- Any API or calculation changes.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)**

## Files To Change
- `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
- `docs/tasks/2026-01-23_dcf-growth-rate-layout.md` (this file)

## Execution Plan (Requires Approval)
1. Adjust Growth Rate layout to keep label + input on one line.
2. Move options below input and right-align.
3. Verify with `docker compose exec web npm run lint`.

## Notes / Results
- Growth Rate label + input aligned on one line; options moved below and right-aligned.
- Tests:
  - `docker compose exec web npm run lint` → OK
