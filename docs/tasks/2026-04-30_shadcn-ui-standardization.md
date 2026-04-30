# Shadcn UI Standardization

## Goal / Acceptance Criteria

- Standardize frontend controls on local shadcn/ui-style components plus Tailwind.
- Replace direct page-level primitive controls (`input`, `textarea`, `select`, `button`, `details`, `summary`) with shared UI components where practical.
- Add missing shared UI components needed by the app: `Input`, `Textarea`, `Select`, and `DropdownMenu`.
- Document the frontend UI convention in `AGENTS.md` so future frontend work follows shadcn/ui + Tailwind.

## Scope

In:
- Shared frontend UI components.
- Existing frontend app/components/features files that currently render direct primitive controls.
- `AGENTS.md` frontend UI standard.

Out:
- Backend behavior.
- Visual redesign beyond control standardization.
- Business logic changes.

## Files To Change

- `AGENTS.md`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/components/ui/*`
- Existing frontend pages/components using primitive controls.

## Test Plan

- `docker compose exec web node --test lib/appToast.test.js`
- `docker compose exec web node --test lib/watchlistState.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- Created branch `codex/shadcn-ui-standardization` from current `main`.
- Added local shadcn/ui-style components: `Input`, `Textarea`, `Select`, `DropdownMenu`, and `Checkbox`.
- Added Radix dependencies for `Select`, `DropdownMenu`, and `Checkbox`.
- Replaced direct primitive controls in app/feature/shared product UI with shared UI components.
- Migrated document review raw tables to the shared `Table` components.
- Added `frontend/lib/uiStandard.test.js` to guard against future raw primitive controls outside `components/ui`.
- Documented the shadcn/ui + Tailwind frontend standard in `AGENTS.md`.

## Verification

- `docker compose exec web node --test lib/uiStandard.test.js` passed.
- `docker compose exec web node --test lib/appToast.test.js lib/watchlistState.test.js` passed.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.
- Restarted the dev web container after production build and verified `http://localhost:3001/login` returns `200`.

## Contract Checklist

- Frontend-only UI standardization.
- No backend API, metric fact, screener, or calculation behavior changed.
- Product frontend TSX no longer renders raw primitive controls/table tags outside `components/ui`.
