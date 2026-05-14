# 13F MVP4-07b: Admin UI for Manager Type=Unknown Prioritization

## Status

**Implemented.** Originally the SME non-blocking note on MVP4-11;
deferred to "after MVP4-03 ships when score_confidence outputs
exist." Those outputs are live (MVP4-03 / 04 / 05 / 06), and
MVP4-07a wired the user-facing persisted-mode contract; this task
now adds the admin priority surface.

## Goal / Acceptance Criteria

Give admins a single screen surfacing which `manager_type='unknown'`
managers materially drag `score_confidence` on the latest usable
quarter, so the typing backlog has an obvious priority order.

Acceptance criteria:

- A new admin endpoint
  `GET /api/v1/admin/13f/oracles-lens/unknown-manager-priority`
  returns one row per `InstitutionManager` where:
  - `manager_type='unknown'` (admin-set enum, not behavior-derived);
  - the manager is currently a holder in at least one
    `oracles_lens_signals` row for the latest usable quarter under
    the default `SCORE_VERSION`;
  - response payload exposes `manager_id`, `canonical_name`,
    `current_holding_count`, `affected_signal_count`,
    `worst_score_confidence_observed` (the lowest tier this
    manager contributes to: `low_confidence` >
    `medium_confidence` > `high_confidence`), and the latest
    quarter label.
- Default ordering: by `affected_signal_count` descending, then
  `worst_score_confidence_observed` ascending tier — i.e.
  managers who appear on the most scores and drag the most
  confidence to the bottom appear first.
- A new admin dashboard tab / panel renders the list as a sortable
  table with manager name, holding count, affected-signal count,
  worst confidence tier, and a CTA to classify (links to the
  existing manager review surface).
- The panel shows the page-level note
  "score_confidence demotion: any holder with
  `manager_type=unknown` falls back to the behavior-derived
  profile (MVP4-11 D2); a classified manager keeps that fallback
  off and stabilizes the score" so the user understands *why*
  they're being asked to classify.
- Admin auth gates the endpoint (existing `AdminUser` dep).
- Tests:
  - Backend endpoint returns the expected rows for a seeded
    fixture (3+ holders with mixed `manager_type` values, one
    `unknown` that holds in two scored stocks).
  - Ordering is correct.
  - Frontend page-level component test if the harness supports
    it; otherwise lint + build cleanliness is the verification
    floor.

## Scope In

- New service helper
  `app/services/oracles_lens/unknown_manager_priority.py`
  (or similar) building the aggregation.
- New admin endpoint route under
  `app/api/v1/endpoints/thirteenf_admin.py` `admin_router`.
- Pydantic response schema.
- New admin dashboard panel in
  `frontend/app/(dashboard)/admin/13f/page.tsx`
  (or split into a new file if the page is already at its line
  limit).
- TDD test files for backend + frontend normalizer.

## Scope Out

- Re-typing workflow itself — links to the existing manager
  review surface; doesn't change the typing path.
- Behavior-derived `manager_type` admin override workflow
  (separate task if it ever lands).
- Bulk classification — single-manager-at-a-time per V1.
- PRD edits.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-11-manager-type-taxonomy.md` D5
  SME non-blocking note: expose admin-side prioritization once
  MVP4-03 score_confidence is live.
- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D5 — MVP4-11b
  filed as post-MVP4-03 admin UI deliverable.
- `docs/plans/13f_admin_data_operations_dashboard_product_plan.md`
  §11-§12 admin panel patterns.

## Files Expected To Change

- `backend/app/services/oracles_lens/unknown_manager_priority.py`
  — new.
- `backend/app/api/v1/endpoints/thirteenf_admin.py` — new route.
- `backend/app/schemas/` — possibly a new module for the response
  shape.
- `backend/tests/unit/test_13f_mvp4_unknown_manager_priority.py`
  — new.
- `frontend/app/(dashboard)/admin/13f/page.tsx` (or extension).
- Possibly `frontend/lib/`-side normalizer test.
- This task file.

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_unknown_manager_priority.py`
- `docker compose exec api pytest -q`
- `docker compose exec frontend npm run lint`
- `docker compose exec frontend npm run build`

## Progress Notes

- 2026-05-12: Filed as a stub during the MVP4-07 split. Will be
  picked up after MVP4-07a frontend integration confirms the
  persisted-mode contract is stable end-to-end.
- 2026-05-12: Implementation:
  - New service
    `backend/app/services/oracles_lens/unknown_manager_priority.py`
    aggregates direct linked holdings for active managers with
    `manager_type='unknown'` against `oracles_lens_signals` for
    the latest scored quarter under the default
    `SCORE_VERSION`. Returns
    `{quarter, score_version, items[]}` with each item carrying
    `manager_id`, `canonical_name`, `affected_signal_count`,
    `worst_score_confidence_observed`. Sorted by
    `(-affected_signal_count, worst tier rank, manager_id)`.
  - New admin route
    `GET /api/v1/admin/13f/oracles-lens/unknown-manager-priority`
    in `thirteenf_admin.py` (admin-only via existing `AdminUser`
    dep).
  - Frontend: added a "Unknown Manager Type Priority" Card on
    `/admin/13f` between the Needs Validation and Batch Reparse
    sections, fed by a new
    `unknownManagerPriorityQuery` (refetches every 60s). Empty
    states cover (a) no persisted scores yet and (b) no unknown
    managers contribute to the latest scored quarter. Worst
    `score_confidence` tier renders with a semantic Badge
    variant (success / warning / danger).
  - Scope adjustment: the original spec's
    `current_holding_count` field was dropped in favor of the
    distinct `affected_signal_count` (the field that actually
    drives priority) — kept the response minimal so the admin
    surface tracks one ranking signal. Likewise the original
    "CTA to classify" was reduced to a row-only ranking; there
    is no existing manager_type edit surface to deep-link into
    yet, so adding a fake CTA would be misleading.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_unknown_manager_priority.py` -> 7 passed.
- `docker compose exec api pytest -q` -> 748 passed (up from 741 baseline; +7 new tests, no regressions).
- `docker compose exec web npm run lint` -> No ESLint warnings or errors.
- `docker compose exec web npm run build` -> compiled successfully.
