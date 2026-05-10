# MVP2-00 Pre-MVP2 Decision Gate

## Goal / Acceptance Criteria

- Close the PRD §20 questions that block MVP 2 implementation.
- Produce a clear MVP 2 decision record for Tech Lead / human owner approval.
- Freeze MVP 2 scope before any schema, computation, aggregation API, or UI work begins.
- Explicitly block `MVP2-01 Ownership Changes Schema / Precompute Contract` until this decision gate is approved.

## Scope In

- Corporate action strategy for MVP 2.
- CUSIP mapping rate threshold strategy for change analysis.
- 13F-NT cross-reference strategy for changes and holder aggregation.
- MVP 2 scope freeze against PRD §17 / §9.2.
- Decision record and approval checklist.

## Scope Out

- `ownership_changes` schema.
- Consecutive-quarter computation.
- `/stocks/{stock_id}/holders` implementation.
- Oracle's Lens investor signal UI.
- Any MVP 3 feature: Dataroma, batch reparse, corporate action UI, filing-level value-unit override, full historical backfill.
- PRD edits.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §7.2 holding attribution.
- `docs/prd/13f_automation_and_resilience_prd.md` §7.3 13F-NT holdings query contract.
- `docs/prd/13f_automation_and_resilience_prd.md` §7.4 holdings change calculation.
- `docs/prd/13f_automation_and_resilience_prd.md` §9.2 Oracle's Lens investor signals.
- `docs/prd/13f_automation_and_resilience_prd.md` §17 MVP delivery plan.
- `docs/prd/13f_automation_and_resilience_prd.md` §20 open questions.

## Files Likely to Change

- `docs/tasks/2026-05-10_13f-mvp2-decision-gate.md`

## Tests First

- No code tests for this decision-gate task.
- The output is a decision record. MVP2-01 must add tests before implementation.

## Docker Verification Commands

- Not applicable for this documentation-only gate.
- No runtime code, migration, frontend, or backend behavior changes are expected.

## Review Gate

- Tech Lead and human owner must approve this record before MVP2-01 starts.

## Current Status

- Tech Lead approved entering `MVP2-00 Pre-MVP2 Decision Gate`.
- Tech Lead did not approve MVP2-01 schema, MVP2-02 computation, MVP2-03 stock holders aggregation, or Oracle's Lens investor signal UI.
- This task intentionally makes no implementation changes.

## Decision Record Draft

### D1. Corporate Action Source for MVP 2

Recommendation: MVP 2 should use only PRD §7.4 corporate-action heuristics and must label them as uncertain (`possible_split_or_merger`, `CUSIP_CHANGED`, or equivalent caveat). MVP 2 should not integrate a paid or external corporate action source.

Rationale:
- PRD §7.4 already defines heuristic thresholds and explicitly says they are "possible" signals only.
- MVP 2 can avoid misclassifying CUSIP/share changes as exit + new by using existing `stock_id` temporal mapping plus `CUSIP_CHANGED`.
- External corporate action source selection has vendor, licensing, data quality, and backfill implications that are closer to MVP 3 resilience/data-quality scope.

Implementation constraint for MVP2-01+:
- Do not adjust historical `value_usd`, `ssh_prnamt`, or holdings quantities from heuristic signals.
- Do not present heuristic corporate actions as facts.
- `change_status=cusip_changed` is a caveat / classification aid, not a corrected historical position.

Approval status: Pending Tech Lead / human owner.

### D2. CUSIP Mapping Rate Threshold

Recommendation: MVP 2 should use the existing global thresholds from PRD §19:
- `< 50%` linked common holdings: block change analysis for the affected quarter/scope.
- `50%–70%`: allow snapshot or limited display with warning; do not show high-confidence change signals.
- `>= 70%`: allow change analysis if other readiness gates pass.

Recommendation: Do not add per-manager thresholds in MVP 2. Instead, record manager-level mapping rates in quality/readiness outputs so a future MVP can justify per-manager exceptions with data.

Rationale:
- PRD §19 already closed the global minimum linked holdings ratio decision.
- Per-manager thresholds introduce policy complexity and can make user-facing confidence inconsistent.
- MVP 2 should prioritize predictable behavior and transparent caveats.

Implementation constraint for MVP2-01+:
- Change analysis must be unavailable or warning-capped when the relevant scope fails mapping thresholds.
- The denominator remains common shares only; options are excluded from common-weight and consensus calculations.

Approval status: Pending Tech Lead / human owner.

### D3. 13F-NT Cross-Reference Strategy

Recommendation: MVP 2 should preserve the MVP 1 rule: when a prior or current quarter is 13F-NT (`notice_reported_elsewhere`), direct holdings changes for that manager should return `change_status=no_prior_data` or unavailable rather than merging across reported-by managers.

Recommendation: Do not implement cross-manager reported-by consolidation in MVP 2. Keep it as MVP 3+ scope.

Rationale:
- PRD §7.3 says 13F-NT active filings do not enter holdings query paths and do not create parse_run / holdings rows.
- PRD §7.4 explicitly says prior-quarter 13F-NT cannot imply no holdings and should produce `no_prior_data`.
- PRD §9.2.2 says 13F-NT reported-by relationships are retained for MVP 3+ merged views.
- Cross-manager consolidation risks double counting and requires reliable `other_managers_reporting` resolution, attribution, and UI caveats.

Implementation constraint for MVP2-01+:
- 13F-NT must never produce empty holdings or "no positions" semantics.
- `/stocks/{stock_id}/holders` direct consensus must count only `holding_attribution_status=direct`.
- Reported-for-other / shared / unresolved attribution stays excluded from direct consensus in MVP 2.

Approval status: Pending Tech Lead / human owner.

### D4. MVP 2 Scope Freeze

Recommendation: MVP 2 includes only:
- Consecutive-quarter ownership change analysis.
- Precomputed ownership-change read model sufficient for P95 target.
- Formal activation of `GET /api/v1/13f/managers/{manager_id}/holdings/changes`.
- `GET /api/v1/13f/stocks/{stock_id}/holders` aggregation with PRD §9.2.3 fields.
- Portfolio weight calculation for common shares when denominator is available.
- Direct-holder consensus and caveat-safe user responses.

Explicitly excluded from MVP 2:
- Dataroma as a CUSIP source.
- Batch reparse by quarter/manager.
- CUSIP corporate action temporal mapping UI.
- Filing-level `value_unit_override`.
- Full historical backfill beyond already supported job primitives.
- AI moat score, buy/sell recommendations, or total AUM claims.

Approval status: Pending Tech Lead / human owner.

## Proposed Next Tasks After Approval

1. `MVP2-01 Ownership Changes Schema / Precompute Contract`
2. `MVP2-02 Consecutive-Quarter Change Analysis`
3. `MVP2-03 /stocks/{stock_id}/holders Aggregation`
4. `MVP2-04 Oracle's Lens Investor Signal UI`

## Approval Checklist

- [ ] D1 Corporate action MVP 2 strategy approved.
- [ ] D2 CUSIP mapping threshold strategy approved.
- [ ] D3 13F-NT cross-reference strategy approved.
- [ ] D4 MVP 2 scope freeze approved.
- [ ] MVP2-01 explicitly approved to start.

## Progress Notes

- 2026-05-10: Created decision gate after Tech Lead approved entering MVP2-00 and blocked MVP2-01/02/03 until decisions close.
- 2026-05-10: Drafted conservative Senior Engineer recommendations that keep MVP 2 within PRD §17 and defer cross-manager 13F-NT consolidation and external corporate-action source selection.
