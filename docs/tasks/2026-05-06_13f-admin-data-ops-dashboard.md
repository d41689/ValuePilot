# 13F Admin Data Operations Dashboard Product Plan

## Goal / Acceptance Criteria
- Create a product plan for an admin-facing 13F data capture and management dashboard.
- Make the plan actionable for review before implementation.
- Cover current production reality: the scheduler can be enabled while the manager / CIK whitelist is empty, which means no usable 13F holdings are captured.
- Define how admins see quarter-by-quarter ingestion status, unresolved tasks, manual trigger actions, and data completeness.
- Explicitly handle in-window quarters such as 2026-Q1 on 2026-05-06, where some filings may exist but the quarter is not yet complete because the approximate filing deadline is 2026-05-15.

## Scope
- In:
  - Product requirements for an admin 13F operations dashboard.
  - Quarter status model and completeness rules.
  - Admin task queue design.
  - Manual job trigger design.
  - CIK review workflow.
  - Monitoring, failure recovery, and quality status.
- Out:
  - Code implementation.
  - Schema migrations.
  - Frontend component work.
  - Changes to the immutable PRD.

## Files to Change
- `docs/tasks/2026-05-06_13f-admin-data-ops-dashboard.md`
- `docs/plans/13f_admin_data_operations_dashboard_product_plan.md`

## Test Plan
- Documentation-only change; no Docker runtime verification required.
- Review with product / engineering owner before implementation.
- If this plan moves into implementation, verification should run inside Docker:
  - `docker compose exec api pytest -q`
  - `docker compose exec web npm run lint`

## Notes
- 2026-05-06: Product plan drafted on branch `codex-13f-admin-dashboard-product-design`.
- 2026-05-06: Added `Admin-Resolvable vs Escalation Required` section to clarify which 13F issues admins can fix directly and which require engineering / infrastructure / external dependency escalation.
