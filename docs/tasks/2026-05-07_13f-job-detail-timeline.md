# 13F Job Detail Timeline

## Goal / Acceptance Criteria

- Add a deterministic job detail timeline so admins can answer "what happened?" without scraping container logs.
- Job detail payload should include lifecycle events from `job_runs` timestamps plus accession-level failures and quality issues from allowlisted `summary_json` fields.
- The admin UI should show the timeline and retry target hints in the existing Job Detail side panel.

## Scope

In:
- Backend `_job_payload` derived events.
- Tests for lifecycle, failed accession, quality issue, and retry target events.
- Frontend Job Detail event rendering.

Out:
- New log storage schema.
- Raw container log streaming.
- Arbitrary shell command or file access.

## Files to Change

- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`
- `docs/tasks/2026-05-07_13f-job-detail-timeline.md`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'`

## Progress Notes

- 2026-05-07: Started after quarter drilldown. Keep this derived from stored job metadata and summary JSON rather than adding raw log access.
- 2026-05-07: Added derived `events` to job detail payload for lifecycle timestamps, failed accessions, quality issues, and job errors.
- 2026-05-07: Added `retry_targets` derived from `summary_json.failed_accessions` so admins can retry specific accessions without parsing raw JSON.
- 2026-05-07: Updated the Job Detail side panel to show retry target buttons and a timeline before raw input/summary JSON.

## Verification

- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py -q` passed: 26 tests.
- `docker compose exec api pytest -q` passed: 237 tests.
- `docker compose exec web npm run lint` passed.
- `docker compose exec web sh -lc 'NODE_ENV=production npm run build'` passed.

## Contract Checklist

- Job timeline is derived from persisted `job_runs` fields and allowlisted summary JSON structures.
- No raw container logs, arbitrary files, or shell commands are exposed.
- Retry targets use existing allowlisted job types.
- No ingestion, holdings, manager identity, screener, parser, or formula semantics changed.
