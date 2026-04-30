# Watchlist Refresh Feedback

## Goal / Acceptance Criteria

- Give immediate visual feedback after clicking `Refresh Prices` on `/watchlist`.
- While refresh is in progress, keep the button disabled, show a spinning icon, and switch the label to `Refreshing`.
- Restore the normal button icon and label after the refresh finishes.

## Scope

In:
- Frontend watchlist refresh button presentation.
- Small helper/test coverage for refresh button state.

Out:
- Backend price refresh behavior.
- Watchlist Overview behavior.
- Price/F-Score calculation changes.

## Files To Change

- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/lib/watchlistState.js`
- `frontend/lib/watchlistState.d.ts`
- `frontend/lib/watchlistState.test.js`

## Test Plan

- `docker compose exec web node --test lib/watchlistState.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Working on branch `codex/watchlist-overview` because this is a follow-up UI refinement for the same watchlist toolbar.
- Added a refresh button presentation helper that switches label and spin class during pending refresh.
- Updated `/watchlist` to render the spinning `RefreshCcw` icon and `Refreshing` label while the mutation is in progress.

## Verification

- `docker compose exec web node --test lib/watchlistState.test.js` passed.
- `docker compose exec web npm run lint` passed.

## Contract Checklist

- Frontend-only UI feedback change.
- No backend API, metric fact, screener, or calculation behavior changed.
