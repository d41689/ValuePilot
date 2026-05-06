# Oracle's Lens Review Drawer

## Goal / Acceptance Criteria

- Restore `Signal-Ranked Candidates` to full-width table space.
- Remove the permanently visible `Why This Signal May Be Misleading` right-column card.
- Keep the caution/review content available from each row's `Review` button.
- Use a right-side drawer/overlay that does not shrink the table.

## Scope

In:
- Frontend layout changes for `/13f/oracles-lens`.
- Preserve existing caution groups, missing data, provenance, top holders, and next steps.
- Lint verification.

Out:
- Backend API changes.
- New review workflow persistence.
- Visual redesign of all Oracle's Lens cards.

## Files to Change

- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec web npm run lint`
- Browser check on `http://localhost:3001/13f/oracles-lens`

## Progress Notes

- 2026-05-06: Started after UX feedback that the permanent review card narrows the candidate table.
- 2026-05-06: Removed the permanent right-column review card so `Signal-Ranked Candidates` renders full width.
- 2026-05-06: Added an on-demand right-side review drawer opened by row `Review` buttons. It preserves caution flags, missing data, Value Line provenance, top holders, and suggested next steps.
- 2026-05-06: Browser checked the local page and confirmed `Candidate Review` appears after clicking a table row review button.

## Verification

- `docker compose exec web npm run lint` - passed.
