# 13F Admin PM UX Hardening

## Goal / Acceptance Criteria

Address the PM/UI acceptance findings from the `/admin/13f` product review:

- Quarter detail opens with visible content instead of a blank drawer area when launched from lower scroll positions.
- Readiness separates data availability from operational health so `ready` does not conflict with blocked operations.
- Admin tasks provide direct next actions where safe, especially scheduler setup and quality checks.
- Manual controls are grouped by workflow and explain disabled states.
- Worker heartbeat defaults to active/latest workers and hides stopped history behind an explicit reveal.
- Dry-run confirmation presents a structured impact summary without a duplicated long sentence.
- Manager CIK revoke is protected by an explicit confirmation dialog.

## Scope

In:

- `frontend/app/(dashboard)/admin/13f/page.tsx`
- Focused frontend tests for 13F admin view-model helpers and UI behavior
- Task notes and verification results

Out:

- Backend schema or API contract changes
- New EDGAR job semantics
- PRD changes

## Files to Change

- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/package.json`
- `docs/tasks/2026-05-07_13f-admin-pm-ux-hardening.md`

## Execution Plan

1. Add failing tests for the new UI/view-model expectations:
   - operational health derived separately from data readiness
   - active/latest worker filtering
   - dry-run summary rows keep structured scope values and avoid duplicated prose
   - task-to-CTA mapping for known admin actions
2. Implement reusable frontend helpers in `frontend/lib/thirteenfAdmin.js`.
3. Update the 13F admin page:
   - fixed drawer with visible header/body layout
   - split Data Readiness and Operations Health badges
   - task CTA buttons where a retry/run action is available
   - grouped manual controls and disabled helper text
   - worker table active-first with show history toggle
   - structured dry-run dialog
   - revoke CIK confirmation state/dialog
4. Run Docker-based frontend tests.
5. Browser smoke-test `/admin/13f` for the drawer, dry-run dialog, and layout regressions.
6. Record verification and contract checklist.

## Rollback Strategy

Revert this task's frontend page/helper/test changes. No migrations or backend data changes are introduced.

## Contract Checks

- Screeners remain untouched and continue to use `metric_facts`.
- No raw SQL or formula execution paths are changed.
- No parser normalization or lineage semantics are changed.
- Admin job execution still goes through existing dry-run and queue APIs.

## Progress Notes

- 2026-05-07: Created after PM/UI acceptance review of `http://localhost:3001/admin/13f`.
- 2026-05-07: Added TDD coverage for operations-health separation, dry-run structured rows, worker-history filtering, and task primary actions.
- 2026-05-07: Implemented PM hardening in the admin page:
  - split data readiness from operations health
  - grouped manual controls by workflow
  - added safe primary CTAs for admin tasks
  - collapsed stopped worker heartbeat history by default
  - replaced duplicated dry-run prose with structured impact rows
  - replaced Revoke CIK prompt/confirm with a required-note dialog
  - changed detail drawers to fixed viewport dialogs with independently scrolling bodies
- 2026-05-07: Fixed the frontend build blocker by forcing `npm run build` to execute with `NODE_ENV=production`. The dev compose service intentionally runs with `NODE_ENV=development`, but Next production builds cannot prerender safely under that inherited environment.

## Verification

- `docker compose exec web node --test lib/thirteenfAdmin.test.js` passed.
- `docker compose exec web node --test lib` passed.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web npm run build` passed after the `NODE_ENV=production` script fix.
- Browser smoke-check of `/admin/13f` confirmed the revised loading/empty-state layout, grouped manual controls, and non-contradictory loading badge. Full admin-data smoke check was limited because the current in-app browser session is authenticated as a non-admin user and the app has no visible logout control to switch accounts.

## Contract Checklist

- Screeners remain untouched and continue to use `metric_facts`.
- Numeric normalization, parser lineage, formula execution, and schema contracts are unchanged.
- No raw SQL or backend job semantics were added.
- Admin job execution still goes through the existing dry-run preview and queue endpoint.
