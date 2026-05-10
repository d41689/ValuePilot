# 13F-1C1-01 Readiness Summary and Data Quality Service

## Goal / Acceptance Criteria

- Implement PRD-compliant readiness levels: `ready`, `usable_with_warning`, `experimental`, and `unavailable`.
- Compute readiness from current active filings and product-queryable current holdings only.
- Compute expected filers by excluding managers with active 13F-NT filings for the quarter.
- Compute manager coverage ratio, filing parse success ratio, linked common holding ratio, linked all holding ratio, and CUSIP mapping ratio.
- Expose `nt_detection_supported` and `coverage_ratio.estimated`; readiness must not become `ready` when NT detection is unsupported.
- Cap readiness at `usable_with_warning` for confidential treatment, combination/partial filings, pending amendments, or amendment failures.
- Report data gap, NT, confidential, partial coverage, amendment pending, and amendment failed quarter lists.
- Use `official_filing_deadline` from active filings for window/readiness logic, not a raw `quarter_end + 45` helper.
- Preserve zero-vs-unavailable semantics: ratios with no denominator are `null` plus a structured unavailable reason, not `0`.

## Scope In

- Backend readiness service.
- Admin/consumer readiness endpoint wiring.
- Unit tests for readiness truth table, denominator definitions, caps, and null-ratio behavior.

## Scope Out

- MVP 2 change analysis.
- Frontend/UI.
- PRD edits.
- Schema migrations unless an implementation blocker is found.

## PRD References

- `docs/prd/13f_automation_and_resilience_prd.md` §9.1 historical coverage and caveat quarter lists.
- `docs/prd/13f_automation_and_resilience_prd.md` §10.1 readiness levels and ready minimum standards.
- `docs/prd/13f_automation_and_resilience_prd.md` §10.2 data quality metrics.
- `docs/prd/13f_automation_and_resilience_prd.md` §10.3 zero-vs-unavailable semantics.
- `docs/prd/13f_automation_and_resilience_prd.md` §15.2 alert threshold alignment.
- `docs/prd/13f_automation_and_resilience_prd.md` §18 acceptance criteria.

## Files Likely To Change

- `backend/app/services/thirteenf_readiness.py` (new)
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/tests/unit/test_13f_readiness.py` (new)
- `docs/tasks/2026-05-10_13f-readiness-summary.md`

## Tests First

- `nt_detection_supported=false` caps readiness and marks coverage ratio estimated.
- Active 13F-NT manager is excluded from expected filer denominator.
- Confidential active filing caps readiness at `usable_with_warning`.
- Combination/partial active filing caps readiness at `usable_with_warning`.
- CUSIP mapping below ready threshold blocks `ready`.
- Pending or failed amendments cap readiness at `usable_with_warning`.
- No active common holdings returns null linked-common ratio with an unavailable reason.
- Readiness uses `official_filing_deadline` from active filings.

## Docker Verification Commands

- `docker compose exec api pytest -q tests/unit/test_13f_readiness.py`
- `docker compose exec api pytest -q tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_nt_handler.py tests/unit/test_13f_parse_run_audit.py tests/unit/test_13f_cusip_enrichment.py`
- `docker compose exec api pytest -q tests/unit`

## Review Gate

Tech Lead must review readiness truth table and denominator definitions before 13F-1C1-02 user-facing 13F API safe responses depends on this contract.

## Progress Notes

- 2026-05-10: Started after local history showed 13F-1B-08 review fixes committed (`30eb8f4`). Dependencies 13F-1B-03, 13F-1B-05, and 13F-1B-07 are present with task logs. Git worktree was clean except no tracked modifications.
- 2026-05-10: Wrote red tests in `tests/unit/test_13f_readiness.py` for readiness thresholds, NT denominator exclusion, NT unsupported cap, confidential/partial/amendment caps, low CUSIP mapping, null ratio semantics, and official-deadline gating.
- 2026-05-10: Implemented `thirteenf_readiness.build_readiness_summary()` with PRD §10 metrics and quarter lists. The service evaluates only active filings and holdings reachable through the current parse-run query contract.
- 2026-05-10: Wired admin readiness payload to include PRD readiness metrics while preserving legacy dashboard compatibility. Consumer readiness remains limited to pre-existing safe fields; broader user-facing contract belongs to 13F-1C1-02.
- 2026-05-10: Docker verification:
  - `docker compose exec api pytest -q tests/unit/test_13f_readiness.py` -> 9 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_readiness.py tests/unit/test_13f_admin_dashboard.py` -> 59 passed.
  - `docker compose exec api pytest -q tests/unit/test_13f_readiness.py tests/unit/test_13f_admin_dashboard.py tests/unit/test_13f_nt_handler.py tests/unit/test_13f_parse_run_audit.py tests/unit/test_13f_cusip_enrichment.py` -> 84 passed.
  - `docker compose exec api pytest -q tests/unit` -> 466 passed, 1 existing SQLAlchemy transaction warning in `test_13f_holdings_parser.py::test_duplicate_fingerprint_within_same_parse_run_raises`.
