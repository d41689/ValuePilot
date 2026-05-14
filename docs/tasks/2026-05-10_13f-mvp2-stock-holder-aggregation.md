# 13F MVP2-03 Stock Holder Aggregation

## Goal / Acceptance Criteria

Implement the user-facing `GET /api/v1/13f/stocks/{stock_id}/holders` aggregation for MVP 2.

Acceptance criteria:
- Response includes PRD §9.2.3 fields: `direct_holder_count`, `value_manager_direct_count`, `featured_holder_count`, `top_holders`, `recent_changes`, `attribution_caveat_count`, `data_caveats`, and `as_of_quarter`.
- Consensus counts use active HR/HR-A current parse-run holdings and `holding_attribution_status=direct`.
- Options are excluded from common-share holder counts and top holders.
- Shared/unresolved attribution does not enter consensus counts and is surfaced via `attribution_caveat_count`.
- Recent changes come from precomputed `ownership_changes` primary signals for the same stock/quarter.
- No investment recommendation, buy/sell copy, total AUM claim, or MVP 3 cross-manager 13F-NT consolidation.

## Scope In

- Backend service response builder for stock holder aggregation.
- Consumer route registration.
- Unit/API tests for response shape, attribution exclusion, manager-type counts, caveats, and recent changes.
- Task log updates with Docker verification results.

## Scope Out

- Frontend Oracle's Lens UI.
- MVP 3 cross-manager 13F-NT consolidation.
- External corporate action source.
- New schema migrations.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.2: exclusion rules for direct consensus.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2.3: stock holder aggregation response fields.
- `docs/prd/13f_automation_and_resilience_prd.md` §13: `GET /api/v1/13f/stocks/{stock_id}/holders`.
- `docs/prd/13f_automation_and_resilience_prd.md` §17: MVP 2 holder aggregation.
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2: direct consensus excludes shared/unresolved attribution.
- `docs/tasks/2026-05-10_13f-mvp2-decision-gate.md` D3-D6.

## Files Likely To Change

- `backend/app/services/thirteenf_user_api.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_user_api.py`
- `docs/tasks/2026-05-10_13f-mvp2-stock-holder-aggregation.md`

## Tests First

Write failing tests before implementation:
- Stock holders endpoint returns PRD §9.2.3 fields and counts only direct common-share holders.
- Shared/unresolved attribution increments `attribution_caveat_count` but does not enter consensus counts.
- `value_manager_direct_count` counts only `fundamental_long` / `activist`; `featured_holder_count` counts featured direct holders.
- `top_holders` is sorted by `portfolio_weight_pct` descending.
- `recent_changes` is sourced from primary `ownership_changes` rows and excludes non-primary / unsupported statuses.
- Confidential/combination filing caveats surface in `data_caveats`.

## Docker Verification Commands

- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py`
- `docker compose exec api pytest -q`

## Review Gate

Tech Lead should review:
- PRD §9.2.2 exclusion rules.
- PRD §9.2.3 response shape.
- Whether the response avoids investment recommendation semantics.
- Scope guard: no UI/MVP3/PRD/schema changes.

## Progress Notes

- 2026-05-10: Started MVP2-03 after MVP2-02 approval.
- 2026-05-10: Added TDD coverage for stock holder aggregation response shape, direct/common consensus counts, attribution caveat count, value-manager and featured counts, top-holder ordering, recent changes, and confidential/combination caveats.
- 2026-05-10: Implemented `build_user_stock_holders` and mounted `GET /api/v1/13f/stocks/{stock_id}/holders`. Default consensus excludes `manager_type=index_like|quant`, options, and non-direct attribution. Shared/unresolved attribution is surfaced only as `attribution_caveat_count`.
- 2026-05-10: Review follow-up accepted NB-1/NB-3/NB-4/NB-5/NB-6 and reduced NB-2 risk. `attribution_caveat_count` now counts distinct managers, same-quarter option exclusion is tested, no-holder unavailable response is tested, stock-level data caveats include `FILING_WINDOW_OPEN`, quarter query validation rejects invalid labels, and holder rows eager-load filing/manager relationships.

## Verification Results

- `docker compose exec api alembic upgrade head` — passed.
- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py tests/unit/test_13f_ownership_changes_compute.py tests/unit/test_13f_mvp2_ownership_changes_schema.py` — 39 passed.
- `docker compose exec api pytest -q` — 545 passed, 1 pre-existing SQLAlchemy rollback warning in `test_duplicate_fingerprint_within_same_parse_run_raises`.
- `docker compose exec api alembic upgrade head` — passed after review follow-up.
- `docker compose exec api pytest -q tests/unit/test_13f_user_api.py tests/unit/test_13f_ownership_changes_compute.py tests/unit/test_13f_mvp2_ownership_changes_schema.py` — 41 passed after review follow-up.
- `docker compose exec api pytest -q` — 547 passed after review follow-up, 1 pre-existing SQLAlchemy rollback warning in `test_duplicate_fingerprint_within_same_parse_run_raises`.

## Final Notes

- Scope stayed backend API/service only: no frontend, no schema migration, no PRD edits, no MVP 3 cross-manager 13F-NT consolidation.
- Recent changes consume precomputed `ownership_changes`; this task does not recompute ownership changes.
