# Task: Enable shadcn/ui + Tailwind and restyle Documents page

## Goal / Acceptance Criteria
- Tailwind CSS is fully configured (content paths, theme tokens) and active in the frontend.
- shadcn/ui base is installed (utils, core components) and used on `/documents`.
- `/documents` page is visually improved with consistent typography, spacing, and status styling.
- Toast feedback is visible on success/error actions.
- No backend or schema changes.

## Scope
### In Scope
- Add Tailwind config + PostCSS config.
- Add shadcn/ui base setup (components, utils, CSS variables).
- Update layout typography (fonts) to match the new theme.
- Restyle `/documents` page using shadcn/ui components.
- Add/adjust toast rendering to use the shared UI system.

### Out of Scope
- Redesign other pages beyond minimal compatibility tweaks.
- Backend/API changes.
- Schema migrations.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` (pdf_documents + document artifacts lineage sections)
- `docs/prd/value-pilot-prd-v0.1-multipage.md` (parse_status semantics)

## Files To Change
- `frontend/tailwind.config.ts`
- `frontend/postcss.config.js`
- `frontend/app/globals.css`
- `frontend/app/layout.tsx`
- `frontend/components/layout/AppShell.tsx`
- `frontend/components/providers.tsx`
- `frontend/app/(dashboard)/documents/page.tsx`
- `frontend/components/ui/*`
- `frontend/lib/utils.ts`
- `frontend/package.json`

## Test Plan (Docker)
- `docker compose exec web npm run lint`

## Progress
- Added Tailwind content/theme config and PostCSS config.
- Introduced shadcn/ui primitives (button, badge, card, table, toast) and `cn` helper.
- Updated global styles and fonts (Manrope + Fraunces) plus AppShell styling.
- Restyled `/documents` page and switched toast handling to shared Toaster.

## Decisions / Notes
- Light theme with teal/amber accents and a soft gradient background.
- Toasts use Radix via shadcn patterns for consistent UX.

## Verification
- `docker compose exec -T web npm install --no-fund --no-audit`
- `docker compose exec -T web npm run lint` (interactive ESLint setup prompt blocked; no config present yet)

## Gotchas
- `npm run lint` auto-updated `frontend/tsconfig.json` (added target) and touched `frontend/next-env.d.ts`.
- `npm install` created `frontend/package-lock.json`.
