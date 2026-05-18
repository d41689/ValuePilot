# 13F PRD Calendar Wording Cleanup

## Goal / Acceptance Criteria

- Align the remaining `official_filing_deadline` acceptance criterion with the v1.11 NYSE holiday calendar decision.
- Ensure no remaining PRD wording implies the old ambiguous federal/market calendar phrasing.

## Scope

In:
- Update `docs/prd/13f_automation_and_resilience_prd.md`.

Out:
- No schema, API, parser, or UI implementation changes.
- No PRD semantic expansion beyond the wording cleanup.

## Files to Change

- `docs/prd/13f_automation_and_resilience_prd.md`

## Test Plan

- Documentation-only change; no Docker test required.
- Run `rg` to confirm the old phrase is gone and NYSE holiday wording remains.

## Progress Notes

- 2026-05-09: Created task log before editing PRD wording.
- 2026-05-09: Updated the remaining acceptance criterion to use NYSE holiday wording.
- 2026-05-09: Verified with `rg` that the old ambiguous federal/market calendar phrases no longer appear in the PRD.
