# 13F Admin Review Followups

## Goal / Acceptance Criteria

Address accepted findings from the review of commit `c01a08f Harden 13F admin UX flows`:

- Worker API errors must render operations health as indeterminate, not blocked.
- Worker history hidden counts must distinguish stopped history from non-stopped rows omitted by the display limit.
- The worker history toggle must not show `Show history (0)` when there is nothing hidden.

## Scope

In:

- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`

Out:

- Backend job/task contracts
- Build script placement changes
- Component decomposition of the large admin page

## Files to Change

- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-07_13f-admin-review-followups.md`

## Test Plan

- `docker compose exec web node --test lib/thirteenfAdmin.test.js`
- `docker compose exec web node --test lib`
- `docker compose exec web npm run lint`
- `docker compose exec web npm run build`

## Progress Notes

- 2026-05-07: Created from external review findings after `c01a08f`.
- 2026-05-07: Accepted and fixed the second review's worker API error false positive and worker history count/toggle findings.
- 2026-05-07: Left `NODE_ENV=production next build` unchanged because it is the most direct fix for the canonical `docker compose exec web npm run build` workflow inside the dev web container. Moving this into Compose would require a separate build-time service/profile to avoid breaking the dev server's `NODE_ENV=development`.

## Verification

- `docker compose exec web node --test lib/thirteenfAdmin.test.js` passed.
- `docker compose exec web node --test lib` passed.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web npm run build` passed.
