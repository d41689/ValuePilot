# Task: Fix and backfill fact_nature for rates.*.cagr_est facts

## Goal / Acceptance Criteria
- New `rates.*.cagr_est` facts must include `fact_nature` in `value_json`.
- Existing parsed `rates.*.cagr_est` rows missing `fact_nature` should be backfilled in the local database.
- Taxonomy audit should stop reporting missing `fact_nature` for `rates.*.cagr_est`.

## Scope
**In**
- Mapping generation fix for `json_from` payloads
- One-off backfill script for existing parsed `rates.*.cagr_est` rows
- Tests and task log updates

**Out**
- Broad historical backfill for every missing `fact_nature`
- Schema changes
- Frontend work

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> normalized queryable facts
- `AGENTS.md` -> Docker-only verification and task logging

## Files To Change
- `docs/tasks/2026-04-23_backfill-rates-cagr-fact-nature.md`
- `backend/app/services/mapping_spec.py`
- `backend/tests/unit/test_value_line_field_taxonomy.py`
- `backend/scripts/backfill_rates_cagr_fact_nature.py`

## Execution Plan
1. Add a failing test proving `rates.*.cagr_est` generated facts should include taxonomy `fact_nature` even when `value_json` comes from `json_from`.
2. Update mapping generation to merge `fact_nature` into dict payloads.
3. Add and run a one-off backfill script for existing local rows missing `fact_nature`.
4. Re-run targeted tests, full tests, and the audit script.

## Contract Checks
- Preserve existing `value_json` payload fields such as `from_period`, `to_period`, and `value`.
- Only backfill parsed `rates.*.cagr_est` rows that currently lack `fact_nature`.
- Run all verification inside Docker.

## Rollback Strategy
- Revert mapping_spec change and skip running the backfill if the merge semantics prove incorrect.

## Progress Log
- [x] Add failing tests.
- [x] Implement mapping + backfill script.
- [x] Run targeted Docker verification.
- [x] Run backfill and record audit results.

## Notes / Decisions / Gotchas
- `json_from` payloads need metadata merge, not replacement.
- The local DB had `15` parsed `rates.*.cagr_est` rows missing `fact_nature`; these were backfilled in-place.
- After this step, the remaining missing `fact_nature` rows are only historical owners earnings facts.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_value_line_field_taxonomy.py tests/unit/test_audit_metric_taxonomy_coverage.py tests/unit/test_owners_earnings_facts.py`
- `docker compose exec api python -m scripts.backfill_rates_cagr_fact_nature --dry-run`
- `docker compose exec api python -m scripts.backfill_rates_cagr_fact_nature`
- `docker compose exec api python -m scripts.audit_metric_taxonomy_coverage --limit 50`
- `docker compose exec api pytest -q`
- Results:
  - Targeted tests: `6 passed in 0.11s`
  - Dry run: `matched=15 updated=15 dry_run=True`
  - Backfill: `matched=15 updated=15 dry_run=False`
  - Audit summary after backfill:
    - `covered_metric_keys=59`
    - `uncovered_metric_keys=0`
    - Missing `fact_nature` keys now only:
      - `owners_earnings_per_share`
      - `owners_earnings_per_share_normalized`
  - Full suite: `127 passed in 21.36s`
