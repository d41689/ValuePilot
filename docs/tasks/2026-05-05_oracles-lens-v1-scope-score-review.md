# Oracle's Lens V1 Scope and Score Review

## Goal / Acceptance Criteria
- Review the second product feedback on the Oracle's Lens 13F dashboard plan.
- Tighten V1 around explainable heuristics, score components, unknown manager coverage, valuation reference strength, and scope control.
- Avoid turning composite scores into opaque investment conclusions.

## Scope
- In:
  - Product decision hierarchy.
  - V1 heuristic examples for signal weighting and conviction scoring.
  - API explanation components.
  - Unknown manager visibility.
  - Research next steps.
  - Milestone scope tightening.
- Out:
  - Backend/API implementation.
  - Frontend implementation.
  - Schema changes.

## Files to Change
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md`

## Test Plan
- Documentation-only change.
- Run `git diff --check`.

## Notes
- 2026-05-05: Accepted the feedback direction. Will keep V1 explainable and scoped, and avoid making anti-crowding or capital allocation look more precise than current data supports.
- 2026-05-05: Added product decision hierarchy, V1 signal-weight heuristic example, capped 0-100 conviction score components, score explanation payloads, unknown manager signal coverage, valuation reference type/confidence, research next steps, and a tighter V1 milestone.
- 2026-05-05: Partially accepted distinctive / anti-crowding: kept as advanced/weak proxy for V1; `crowded_mega_cap` is V2-only until market cap or broad ownership data exists.

## Verification
- `git diff --check` passed.
