# Watchlist Refresh Toast

## Goal / Acceptance Criteria

- Show a clear completion toast after the user manually clicks `Refresh Prices`.
- Keep the existing pending button feedback for slower refreshes.
- Place toast notifications at the top center of the viewport.
- Avoid showing success/error refresh toasts for automatic background refresh on page load.

## Scope

In:
- Watchlist manual refresh success/error toast behavior.
- Top-center toast viewport placement.
- Helper/test coverage for refresh success descriptions.

Out:
- Backend price refresh behavior.
- Watchlist membership or F-Score logic.

## Files Changed

- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/components/ui/toast.tsx`
- `frontend/lib/watchlistState.js`
- `frontend/lib/watchlistState.d.ts`
- `frontend/lib/watchlistState.test.js`

## Test Plan

- `docker compose exec web node --test lib/watchlistState.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Added a refresh success description helper that distinguishes updated stocks from already-current checks.
- Manual refresh passes `showToast: true`; automatic refresh passes `showToast: false`.
- Toast viewport now renders top-center.

## Verification

- `docker compose exec web node --test lib/watchlistState.test.js` passed.
- `docker compose exec web npm run lint` passed.

## Contract Checklist

- Frontend-only feedback change.
- No backend API, metric fact, screener, or calculation behavior changed.
