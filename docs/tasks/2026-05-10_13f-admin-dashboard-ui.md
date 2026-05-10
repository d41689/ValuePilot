# 13F-1C2-02 Admin Dashboard UI

## Goal / Acceptance Criteria

- Build the MVP 1C-2 admin dashboard UI on top of the reviewed 13F admin backend read models.
- Admin can inspect operations health, managers, daily sync quarters, filings, parse runs, holdings coverage, jobs, readiness, amendments, and unresolved CUSIP mappings.
- Filing rows visibly expose report type, coverage completeness/type, confidential treatment, amendments, parse status, deadlines, and NT caveats.
- Missing / unavailable numeric data is displayed as unavailable, not as zero.
- UI uses `frontend/components/ui/` shadcn-style components, Tailwind utilities, and `lucide-react` icons.

## Scope In

- Extend existing `frontend/app/(dashboard)/admin/13f/page.tsx`.
- Add client-side normalization helpers for admin filings, parse runs, coverage, and unresolved CUSIPs.
- Add UI sections for filings, holdings coverage, and unresolved CUSIP mapping review.
- Add parse-runs drawer from a selected filing.
- Preserve existing manager, job, quarter, quality, amendment, and readiness workflows.

## Scope Out

- MVP 3 CUSIP corporate action temporal mapping UI.
- Batch reparse UI.
- Raw form/control primitives outside shared `components/ui`.
- Backend / schema / PRD changes.
- Marketing or landing pages.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §11 Admin Dashboard.
- `docs/prd/13f_automation_and_resilience_prd.md` §13 Admin API Requirements.
- `docs/prd/13f_automation_and_resilience_prd.md` §16 UX Copy Principles.
- `AGENTS.md` frontend UI standards.

## Files Likely to Change

- `frontend/lib/thirteenfAdmin.js`
- `frontend/lib/thirteenfAdmin.test.js`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-10_13f-admin-dashboard-ui.md`

## Tests First

- Add frontend normalization tests for filings caveats, parse-runs pagination, coverage null handling, and unresolved CUSIP rows.
- Then wire UI to the reviewed 1C2-01 backend endpoints.

## Docker Verification Commands

- `docker compose exec frontend npm test -- --runInBand` if a test script exists; otherwise run targeted Node tests directly via Docker.
- `docker compose exec frontend npm run lint`
- `docker compose exec frontend npm run build`

## Review Gate

- Tech Lead reviews admin dashboard UI semantics before considering MVP 1C-2 complete.

## Progress Notes

- 2026-05-10: Confirmed 13F-1C2-02 is next in execution plan. Reviewed PRD §11, §13, §16 and existing admin/13f page structure.
- 2026-05-10: Added frontend normalization tests for admin filings, parse runs, holdings coverage, and unresolved CUSIPs before wiring UI.
- 2026-05-10: Extended the existing admin 13F page with holdings coverage, filings/caveats table, parse-run history drawer, unresolved CUSIPs, and pending amendment group summaries.
- 2026-05-10: Browser check reached `/admin/13f`, but local auth redirected to login; visual authenticated-state verification requires a valid admin session.
- 2026-05-10: Docker verification:
  - `docker compose exec web node --test lib/thirteenfAdmin.test.js` -> 24 passed.
  - `docker compose exec web npm run lint` -> passed with existing `refreshAdminData` hook dependency warning in `app/(dashboard)/admin/13f/page.tsx`.
  - `docker compose exec web npm run build` -> passed with the same existing lint warning.
- 2026-05-10: Fixed authenticated UI warning where multiple admin tasks with the same code, such as `RECENT_JOB_FAILED`, produced duplicate React keys. Added normalizer coverage for duplicate task codes.
- 2026-05-10: Duplicate-key fix verification:
  - `docker compose exec web node --test lib/thirteenfAdmin.test.js` -> 25 passed.
  - `docker compose exec web npm run lint` -> passed with existing `refreshAdminData` hook dependency warning.
  - `docker compose exec web npm run build` -> passed with the same existing warning.
