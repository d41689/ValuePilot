# Task: Promote user to admin and add documents upload notice

## Goal / Acceptance Criteria
- Inspect current ValuePilot prod users and identify which accounts are admins.
- Promote `d41689@gmail.com` to admin in the ValuePilot prod database.
- `/documents` shows a clear notice for non-admin users that they cannot upload files.
- Existing admin upload workflow remains available.

## Scope
**In**
- Prod data inspection and one-off user role update.
- Frontend documents page messaging for non-admin users.
- Minimal frontend unit coverage if a helper is introduced.
- Docker-based verification for frontend changes.

**Out**
- Backend auth model changes.
- Broad role/permission redesign.
- Upload flow redesign on `/documents`.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> Docker-based runtime / deployment expectations
- `docs/prd/value-pilot-prd-v0.1.md` -> UI & Query Semantics (V1)

## Files To Change
- `docs/tasks/2026-04-20_promote-admin-and-documents-upload-notice.md` (this file)
- `frontend/app/(dashboard)/documents/page.tsx`
- `frontend/lib/documentsAccess.js` (new, if needed)
- `frontend/lib/documentsAccess.test.js` (new, if needed)

## Execution Plan (Assumed approved per direct request)
1. Inspect prod users and current admin accounts via Docker Compose in the prod API container.
2. Update `d41689@gmail.com` to `role='admin'` in the prod database.
3. Add a small frontend helper/test if useful, then update `/documents` to show a non-admin notice.
4. Verify in Docker:
   - prod user/admin inspection output
   - prod role update output
   - `docker compose run --rm --no-deps web node --test ...` (if helper test added)
   - `docker compose run --rm --no-deps web npm run lint`

## Contract Checks
- Runtime and verification commands use Docker Compose.
- No schema, parser, screener, formula, or lineage behavior changes.
- No raw SQL from user input.

## Rollback Strategy
- Revert the frontend `/documents` notice change.
- Set `d41689@gmail.com` back to `role='user'` in prod if requested.

## Progress Log
- [x] Inspect prod users and admins.
- [x] Promote `d41689@gmail.com` to admin.
- [x] Add non-admin documents upload notice.
- [x] Run Docker verification.

## Notes / Decisions / Gotchas
- Prod user inspection found exactly one user:
  - `d41689@gmail.com` (`id=1`)
- Before the update there were no admin users in prod.
- Promoted `d41689@gmail.com` from `role='user'` to `role='admin'` in the prod database.
- Updated `/documents` to show:
  - an `Upload Document` button for admin users
  - a clear amber notice for non-admin users that they cannot upload files
- Added a small helper and unit test for the documents upload access messaging.
- Frontend role detection still relies on the `vp_role` cookie, so an already logged-in session may need to sign out and sign back in before the new admin navigation becomes visible.

## Verification Results
- `docker compose -f docker-compose.prod.yml exec api ...` -> `TOTAL_USERS=1`
- `docker compose -f docker-compose.prod.yml exec api ...` before update -> `ADMINS=` (none)
- prod role update -> `UPDATED d41689@gmail.com role user -> admin (id=1)`
- `docker compose -f docker-compose.prod.yml exec api ...` after update -> `ADMINS=d41689@gmail.com(id=1)`
- `docker compose run --rm --no-deps web node --test lib/documentsAccess.test.js` -> pass
- `docker compose run --rm --no-deps web npm run lint` -> pass (`No ESLint warnings or errors`)
- `docker compose down` -> pass (temporary dev network removed)
