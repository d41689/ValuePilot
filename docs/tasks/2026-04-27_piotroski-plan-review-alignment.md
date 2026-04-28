# Piotroski Plan Review Alignment

## Goal / Acceptance Criteria
- Review the Piotroski F-Score planning notes against the supplied F-Score reference material.
- Accept corrections that tighten the implementation contract without expanding v0.1 scope.
- Update `docs/plans/piotroski_f_score_calculation_plan.md` to clarify accepted decisions and rejected/deferred suggestions.

## Scope
In:
- Documentation-only updates to the Piotroski F-Score calculation plan.
- Clarify canonical Piotroski definitions versus Value Line proxy fields.
- Clarify unsupported/deferred scope for financial companies, TTM scoring, Guru integration, trend scoring, and anomaly screens.

Out:
- No production code changes.
- No schema or PRD changes.
- No parser or mapping implementation changes.

## Files to Change
- `docs/plans/piotroski_f_score_calculation_plan.md`
- `docs/tasks/2026-04-27_piotroski-plan-review-alignment.md`

## Test Plan
- Documentation-only change; no Docker test is required.
- Verify the plan remains consistent with `docs/metric_facts_mapping_spec.yml` naming and existing Value Line metric semantics.

## Progress Notes
- 2026-04-27: Created task log before editing the plan.
- 2026-04-27: Updated the plan to distinguish canonical Piotroski formulas from Value Line proxy inputs.
- 2026-04-27: Removed the previous insurance revenue fallback from the generic v0.1 F-Score plan and made financial companies unsupported/deferred by default.
- 2026-04-27: Deferred TTM scoring, F-Score trend, Guru blending, thresholds, and anomaly radar to later screening/portfolio layers.
- 2026-04-27: Re-reviewed the detailed feedback. Replaced the earlier blanket insurance exclusion with an explicit `insurance_adjusted` variant because the AXS-style Value Line layout provides premiums earned, underwriting margin, total assets, net profit, and shares.
- 2026-04-27: Renamed the plan to Value Line-adjusted Piotroski F-Score and added variant/method/calculation version rules.
- 2026-04-27: Changed fiscal period handling to derive `period_end_date` from the company fiscal year end where available, with FICO-style September 30 handling called out.
- 2026-04-27: Added partial total diagnostics and split reusable ratio calculation from F-Score calculation.
- 2026-04-27: Added final pre-implementation review clarifications for deterministic method priority and partial total `fact_nature` aggregation.

## Verification
- Documentation-only change; Docker tests not run.
- Text review confirmed insurance premium revenue is only allowed under `variant = insurance_adjusted`, not under `standard`.

## Change Summary
- Accepted: annual canonical F-Score baseline, proxy labeling, deterministic method priority, fiscal-year period dating, score-specific units, standard component key names, partial total diagnostics, reusable ratio service, partial total `fact_nature`, and explicit insurance-adjusted scoring.
- Deferred/rejected: separate standard/proxy metric-key namespaces, TTM, trend scoring, Guru integration, thresholding, anomaly radar, bank-specific scoring, and standalone scripts outside `metric_facts` lineage.
