# 13F PRD Review Follow-ups

## Goal / Acceptance Criteria

- Review the Gemini findings against SEC/EDGAR source semantics and current PRD text.
- Apply accepted PRD fixes for filing deadline calendar, value unit parsing, 13F-NT linkage, schema field consistency, and Oracle's Lens caveats.
- Leave implementation-only findings for the engineering task phase instead of changing product semantics.

## Scope

In:
- Update `docs/prd/13f_automation_and_resilience_prd.md`.
- Record accepted/rejected review decisions in this task log.

Out:
- No backend schema migration or parser implementation.
- No frontend implementation.
- No database cleanup.

## Files to Change

- `docs/prd/13f_automation_and_resilience_prd.md`
- `docs/tasks/2026-05-09_13f-prd-review-followups.md`

## Test Plan

- Documentation-only change; Docker tests are not required.
- Run `rg` checks for removed stale references and new canonical wording.

## Decisions

- Accept: use SEC/EDGAR federal holiday/business day calendar for filing deadlines; do not use NYSE market holidays.
- Accept: strengthen parser requirement to read XML schema/root namespace/version rather than infer units from date only.
- Accept: parse and store identifiers for 13F-NT `other_managers_reporting` to support later consolidation and avoid duplicate consensus signals.
- Accept: clarify field definitions for `coverage_type` and holding-level `cusip_mapping_status`.
- Accept: switch holding fingerprint from derived `value_usd` to raw filing value inputs.
- Accept: correct stale section references and amendment enum wording.
- Accept: add caveats for partial portfolios and MVP 3+ Value Line integration.
- Defer to implementation phase: existing code model migration details such as BigInt schema changes.

## Progress Notes

- 2026-05-09: Created task log before editing PRD follow-ups.
- 2026-05-09: Verified SEC Form 13F FAQ Q25 and SEC EDGAR Calendar semantics; filing deadline calendar should follow SEC/EDGAR federal holidays and special EDGAR closures, not NYSE market holidays.
- 2026-05-09: Updated PRD for accepted review items and ran `rg` checks for stale NYSE proxy wording, amendment wording, field definitions, and schema-version requirements.
