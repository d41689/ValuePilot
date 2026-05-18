# Oracle's Lens Duplicate Period Key Fix

## Goal / Acceptance Criteria

- Fix the React warning on `/13f/oracles-lens`:
  `Encountered two children with the same key, 2026-Q2`.
- Preserve existing Oracle's Lens scoring, period selection, and API
  contracts.
- Add a regression test that duplicate period labels from the API do
  not produce duplicate frontend option keys.

## Scope

In:
- Frontend period option rendering / helper logic for Oracle's Lens.
- Focused frontend tests.

Out:
- Backend 13F scoring changes.
- Database migrations.
- Product copy or layout changes beyond the duplicate-key fix.

## Files To Change

- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`
- `docs/tasks/2026-05-13_oracles-lens-duplicate-period-key.md`

## Test Plan

- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Created after observing duplicate React key warning for period
  label `2026-Q2` on `/13f/oracles-lens`.
- Added `uniquePeriodOptions()` in `frontend/lib/oraclesLens.js`
  to collapse duplicate API period labels before rendering the
  period `<SelectItem>` list. The first occurrence wins, preserving
  latest-complete and manager-count metadata from the API order.
- Updated `/13f/oracles-lens` to use the helper and use the helper's
  stable `key` field for React keys while keeping the selected value
  as the period label.

## Verification

- `docker compose exec web node --test lib/oraclesLens.test.js` —
  18 passed.
- `docker compose exec web npm run lint` — no ESLint warnings or
  errors.

## Contract Checklist

- No backend API changes.
- No scoring formula changes.
- No database migrations.
- Frontend selector remains period-label based; duplicate labels are
  deduped before render to keep React child identity stable.
