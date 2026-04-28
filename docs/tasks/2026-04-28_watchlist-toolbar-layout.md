# Watchlist Toolbar Layout

## Goal / Acceptance Criteria

- Move watchlist selection out of the left-side `My Watchlists` card into a compact top toolbar control.
- Let the watchlist holdings table use the full available page width.
- Keep existing watchlist behaviors: create list, switch list, add ticker, refresh prices, delete list, edit fair value, remove ticker, and show 3-year F-Score.
- Keep the implementation scoped to the watchlist UI and small supporting helpers.

## Scope

In:
- `/watchlist` page layout and controls.
- Watchlist state helper/test updates needed for the new dropdown label.

Out:
- Backend API changes.
- F-Score calculation changes.
- Production deployment changes.

## Files To Change

- `frontend/app/(dashboard)/watchlist/page.tsx`
- `frontend/lib/watchlistState.js`
- `frontend/lib/watchlistState.d.ts`
- `frontend/lib/watchlistState.test.js`

## Test Plan

- `docker compose exec web node --test lib/watchlistState.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Created branch `codex/watchlist-toolbar-layout`.
- Current UI has no shared select/menu components, so this task will use native controls styled to match the existing dashboard.
- Added `formatWatchlistOptionLabel` coverage and used it for dropdown labels.
- Replaced the two-column watchlist page with one full-width holdings card and a compact toolbar for list selection, creation, ticker add, price refresh, and destructive actions.

## Verification

- `docker compose exec web node --test lib/watchlistState.test.js` passed.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web npm run build` compiled and type-checked successfully, then failed during existing `/404` prerendering with `<Html> should not be imported outside of pages/_document`.

## Contract Checklist

- `metric_facts` query semantics unchanged.
- No backend API, formula, or screener changes.
- No raw SQL or eval/exec added.
- Existing F-Score display semantics preserved.
