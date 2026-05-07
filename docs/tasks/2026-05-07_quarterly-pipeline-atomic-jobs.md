# 2026-05-07 Quarterly Pipeline Atomic Jobs

## Goal / Acceptance Criteria
- Split `quarterly_pipeline` execution into visible, retryable stage jobs.
- If enrichment fails after index fetch or holdings ingestion, admins can retry only the enrichment stage from the Dashboard.
- Preserve existing idempotent ingestion behavior and job lock semantics.
- Keep data contracts unchanged: no schema changes, no screener/query behavior changes, no raw SQL or eval changes.

## Scope
- In:
  - Backend JobRun orchestration for quarterly pipeline stages.
  - Retry target metadata for failed enrichment jobs.
  - Dashboard lock-key support for enrichment retry actions.
  - Unit coverage for stage job creation and enrichment-only retry target behavior.
- Out:
  - Database schema changes.
  - Parser or CUSIP normalization behavior changes.
  - New dependency graph / async child-job scheduler.

## Files to Change
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`
- `frontend/app/(dashboard)/admin/13f/page.tsx`

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py`
- `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py`

## Progress Notes
- 2026-05-07: Found partial implementation that added `enrich_metadata`, but `quarterly_pipeline` still executed enrichment inside the parent job rather than as a visible retryable stage job.
- 2026-05-07: Updated `quarterly_pipeline` to create visible `pipeline` stage JobRuns for `fetch_quarter_index`, `ingest_holdings`, `enrich_metadata`, and `quality_check`.
- 2026-05-07: Added retry target metadata for failed `enrich_metadata` / `enrich_cusip` jobs so the Dashboard can show a retry-only-enrichment action.
- 2026-05-07: Updated Dashboard lock-key handling, retry target payloads, and manual action label to use `enrich_metadata` as the enrichment retry unit.
- 2026-05-07: Review fixes made the parent `quarterly_pipeline` retain `summary_json` on retryable stage failures instead of raising; enrichment and quality failures now surface as stage failures and parent `partial_success`.
- 2026-05-07: Updated tests to lock the post-review behavior: enrichment failure continues to quality check, parent retry targets include `enrich_metadata`, and parent summary remains inspectable.

## Verification
- 2026-05-07: `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` passed (`38 passed`).
- 2026-05-07: `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py` passed (`3 passed`).
- 2026-05-07: `docker compose exec web npm run lint` passed with no ESLint warnings or errors.
- 2026-05-07: Post-review verification repeated: `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py` passed (`38 passed`); `docker compose exec api pytest -q tests/unit/test_scheduler_alignment.py` passed (`3 passed`); `docker compose exec web npm run lint` passed.

## Contract Checklist
- [x] No database schema changes.
- [x] No screener/query source changes; `metric_facts` contract untouched.
- [x] No raw SQL generation from user input added.
- [x] No formula eval/exec changes.
- [x] 13F job lock semantics preserved with stage-level lock keys.
