# Oracle's Lens Final V1 Product Tightening

## Goal / Acceptance Criteria
- Apply final small-scope product feedback before engineering task decomposition.
- Tighten primary score visual hierarchy, New/Add weighting, timing flags, caution flag grouping, score confidence, and Milestone 1 boundaries.
- Keep the plan stable and avoid expanding V1 feature scope.

## Scope
- In:
  - `docs/plans/13f_oracles_lens_dashboard_product_plan.md`
  - Documentation-only product plan refinements.
- Out:
  - Code implementation.
  - API route creation.
  - Frontend design implementation.
  - Schema changes.

## Files to Change
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md`

## Test Plan
- Documentation-only change.
- Run `git diff --check`.

## Notes
- 2026-05-05: Final tightening pass. No new feature expansion; only product constraints and implementation clarity.
- 2026-05-05: Added main table primary score visual hierarchy, New/Add weighting limits, `score_confidence`, baseline notice vs row-level timing flags, caution flag grouping/priority, and explicit Milestone 1 no-production-UI boundary.

## Verification
- `git diff --check` passed.
