# App Toast Standard

## Goal / Acceptance Criteria

- Define a reusable toast standard for success, error, warning, and info messages.
- Render semantic icons and accent colors consistently across toast notifications.
- Provide a small helper API so pages can show standardized app toasts without duplicating icon/color details.
- Migrate `/watchlist` toast calls to the new helper.
- Keep the existing low-level `toast({...})` API working for existing pages.

## Scope

In:
- Shared app toast helper.
- Toast type metadata and centralized toaster rendering.
- Watchlist page toast migration.
- Helper tests.

Out:
- Backend behavior.
- Broad migration of documents/DCF pages.
- Toast persistence or queue semantics.

## Files To Change

- `frontend/lib/appToast.js`
- `frontend/lib/appToast.d.ts`
- `frontend/lib/appToast.test.js`
- `frontend/components/ui/use-toast.ts`
- `frontend/components/ui/toaster.tsx`
- `frontend/app/(dashboard)/watchlist/page.tsx`

## Test Plan

- `docker compose exec web node --test lib/appToast.test.js`
- `docker compose exec web node --test lib/watchlistState.test.js`
- `docker compose exec web npm run lint`

## Progress Notes

- Implementing on `codex/watchlist-overview` because the current watchlist toast changes live on this branch.
- Added `frontend/lib/appToast.js` with `showAppToast`, semantic type normalization, and standardized payload construction.
- Extended toast metadata with `appType = success | error | warning | info`.
- Centralized semantic icon and accent color rendering in `frontend/components/ui/toaster.tsx`.
- Migrated `/watchlist` toast calls to `showAppToast`.

## Verification

- `docker compose exec web node --test lib/appToast.test.js` passed.
- `docker compose exec web node --test lib/watchlistState.test.js` passed.
- `docker compose exec web npm run lint` passed.

## Contract Checklist

- Frontend-only notification API/style change.
- Existing low-level `toast({...})` API remains supported for pages not yet migrated.
- No backend API, metric fact, screener, or calculation behavior changed.
