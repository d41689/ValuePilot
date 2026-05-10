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
- Ownership signal confidence and display rules.
- Decision record and approval checklist.

## Scope Out

- `ownership_changes` schema.
- Consecutive-quarter computation.
- `/stocks/{stock_id}/holders` implementation.
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
- Tech Lead did not approve implementing MVP2-01 schema, MVP2-02 computation, MVP2-03 stock holders aggregation, or Oracle's Lens investor signal UI until this gate closes.
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
- Heuristic corporate-action signals may downgrade confidence, but must not create corrected values.
- User-facing copy should avoid implying confirmed corporate action. Preferred language: "Potential identifier change; change signal may be incomplete."

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
- Threshold denominators are per reporting quarter, common shares only, across expected filers for that quarter.
- Options are excluded from common-weight and consensus calculations.
- Below 70%, do not show `new_position`, `exited_position`, `increased`, or `reduced` as primary labels.
- Even when quarter-level mapping passes, stock-level holder aggregation should expose mapping confidence and caveats for the specific `stock_id`.

Approval status: Pending Tech Lead / human owner.

### D3. 13F-NT Cross-Reference Strategy

Recommendation: MVP 2 should preserve the MVP 1 rule: when a prior or current quarter is 13F-NT (`notice_reported_elsewhere`), direct holdings changes for that manager should return `change_status=no_prior_data` rather than merging across reported-by managers. API responses may use `status=unavailable` where the endpoint has no reliable direct-change data to display.

Recommendation: Do not implement cross-manager reported-by consolidation in MVP 2. Keep it as MVP 3+ scope.

Rationale:
- PRD §7.3 says 13F-NT active filings do not enter holdings query paths and do not create parse_run / holdings rows.
- PRD §7.4 explicitly says prior-quarter 13F-NT cannot imply no holdings and should produce `no_prior_data`.
- PRD §9.2.2 says 13F-NT reported-by relationships are retained for MVP 3+ merged views.
- Cross-manager consolidation risks double counting and requires reliable `other_managers_reporting` resolution, attribution, and UI caveats.

Implementation constraint for MVP2-01+:
- 13F-NT must never produce empty holdings or "no positions" semantics.
- User-facing copy must say the manager filed a 13F Notice and its holdings may be reported by another manager; the manager is excluded from direct-holder consensus.
- `/stocks/{stock_id}/holders` direct consensus must count only `holding_attribution_status=direct`.
- Reported-for-other / shared / unresolved attribution stays excluded from direct consensus in MVP 2.
- Holder aggregation should expose counts separately enough to avoid overstating consensus: `direct_holder_count` as the primary count, with reported-elsewhere / unresolved attribution caveats or counts when available.

Approval status: Pending Tech Lead / human owner.

### D4. MVP 2 Scope Freeze

Recommendation: MVP 2 includes only:
- Consecutive-quarter ownership change analysis.
- `CUSIP_CHANGED` detection and handling: when CUSIP changes but both rows map to the same `stock_id`, classify as the same security with `change_status=cusip_changed`, not exit + new position.
- Precomputed ownership-change read model sufficient for P95 target.
- Formal activation of `GET /api/v1/13f/managers/{manager_id}/holdings/changes`.
- `GET /api/v1/13f/stocks/{stock_id}/holders` aggregation with PRD §9.2.3 fields.
- Portfolio weight calculation for common shares when denominator is available.
- Direct-holder consensus and caveat-safe user responses.
- Oracle's Lens investor signal UI display for PRD §9.2.1 signals, applying PRD §9.2.2 exclusion rules.

Explicitly excluded from MVP 2:
- Dataroma as a CUSIP source.
- Batch reparse by quarter/manager.
- CUSIP corporate action temporal mapping UI.
- Filing-level `value_unit_override`.
- Full historical backfill beyond already supported job primitives.
- AI moat score, buy/sell recommendations, or total AUM claims.

MVP 2 outputs ownership behavior signals for research prioritization, not investment recommendations.
Options are excluded from direct-holder consensus and common-share holder counts by default.

Approval status: Pending Tech Lead / human owner.

### D5. Ownership Signal Confidence for MVP 2

Recommendation: MVP 2 should classify ownership change signals into explicit confidence levels:

- `high_confidence`: direct filing, common shares, stable `stock_id`, quarter-level mapping readiness `>= 70%`, consecutive reliable quarters available, no unresolved amendment/confidential-treatment caveat.
- `medium_confidence`: direct filing and common shares, but with mapping, possible corporate-action, or confidential-treatment caveat.
- `low_confidence`: incomplete mapping, adjacent 13F-NT, Combination Report, confidential treatment, no reliable prior quarter, or unresolved attribution.
- `unavailable`: missing prior quarter, prior/current 13F-NT for direct manager changes, unresolved attribution, pending amendment, failed mapping, or below blocking threshold.

Oracle's Lens should only use `high_confidence` and selected `medium_confidence` signals in primary ranking or prominent display.

Implementation constraint for MVP2-01+:
- `ownership_changes` or its read model must be able to represent signal confidence, caveat codes, primary-display eligibility, and unavailable reason.
- UI/API copy must distinguish facts, inferred signals, weak signals, and unavailable states.

Approval status: Pending Tech Lead / human owner.

### D6. Change Signal Display Rules for MVP 2

Recommendation: Strong change labels are allowed only when both the current and comparison quarter have reliable direct data.

Rules:
- Emit `new_position` only when the prior quarter has reliable direct holdings data proving the security was absent.
- Emit `exited_position` only when the current quarter has reliable direct holdings data proving the security is absent.
- Emit `increased`, `reduced`, or `unchanged` only when both quarters have reliable direct common-share positions for the same security identity.
- Emit `cusip_changed` when CUSIP differs but temporal mapping resolves both rows to the same `stock_id`; this is not an exit + new pair.
- Emit `change_status=no_prior_data` or return API `status=unavailable` instead of strong labels when the prior/current quarter is missing, unresolved, 13F-NT, Combination-only for total-value comparisons, below mapping threshold, or blocked by pending/failed amendments.

Implementation constraint for MVP2-01+:
- `new_position` and `exited_position` must never be inferred from missing data.
- Below the ready mapping threshold, strong labels are not primary labels even if raw comparison rows exist.

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
- [ ] D5 ownership signal confidence levels approved.
- [ ] D6 change signal display rules approved.
- [ ] MVP2-01 explicitly approved to start.

## Progress Notes

- 2026-05-10: Created decision gate after Tech Lead approved entering MVP2-00 and blocked MVP2-01/02/03 until decisions close.
- 2026-05-10: Drafted conservative Senior Engineer recommendations that keep MVP 2 within PRD §17 and defer cross-manager 13F-NT consolidation and external corporate-action source selection.
- 2026-05-10: Accepted review feedback:
  - Added `CUSIP_CHANGED` handling explicitly to D4 scope-in.
  - Resolved the D4 ambiguity by keeping Oracle's Lens investor signal UI in MVP 2, consistent with PRD §17.
  - Clarified D2 threshold denominator as per reporting quarter, common shares only, across expected filers.
  - Clarified D3 terminology: `change_status=no_prior_data` is the computation enum, while API responses may use `status=unavailable`.
  - Added D5 signal confidence and D6 change display rules so MVP2-01 can design the schema/precompute contract with the required fields.
