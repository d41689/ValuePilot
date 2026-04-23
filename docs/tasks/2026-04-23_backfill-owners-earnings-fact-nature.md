# Task: Backfill fact_nature for owners earnings facts

## Goal / Acceptance Criteria
- Existing parsed `owners_earnings_per_share` rows missing `fact_nature` should be backfilled to `actual` or `estimate`.
- Existing parsed `owners_earnings_per_share_normalized` rows missing `fact_nature` should be backfilled to `snapshot`.
- After backfill, taxonomy audit should report no remaining `missing fact_nature` metric keys.

## Scope
**In**
- A one-off owners earnings backfill script
- Shared owners earnings fact-nature inference helper if needed
- Unit tests for the backfill behavior
- Task log updates and audit rerun

**Out**
- Reparse/backfill of unrelated metrics
- Schema changes
- Frontend changes

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` -> normalized facts and `metric_facts` as queryable truth
- `AGENTS.md` -> Docker-only verification and task logging

## Files To Change
- `docs/tasks/2026-04-23_backfill-owners-earnings-fact-nature.md`
- `backend/app/services/owners_earnings.py`
- `backend/scripts/backfill_owners_earnings_fact_nature.py`
- `backend/tests/unit/test_backfill_owners_earnings_fact_nature.py`

## Execution Plan
1. Add failing unit tests for owners earnings fact-nature backfill.
2. Implement owners earnings fact-nature inference and the backfill script.
3. Run targeted Docker verification.
4. Run the backfill locally and rerun the taxonomy audit.

## Contract Checks
- Preserve existing owners earnings values; only update `value_json.fact_nature`.
- Only backfill `source_type='parsed'` rows missing `fact_nature`.
- Use underlying canonical input facts for FY owners earnings nature inference.

## Rollback Strategy
- Revert the backfill script/helper changes and skip the backfill if the inferred semantics look wrong.

## Progress Log
- [x] Add failing tests.
- [x] Implement backfill logic.
- [x] Run targeted Docker verification.
- [x] Run backfill and record audit results.

## Notes / Decisions / Gotchas
- FY owners earnings semantics should follow the strongest input signal: if any source input is `estimate`, the derived owners earnings fact is `estimate`; otherwise `actual`.
- The live local DB had `39` parsed owners earnings rows missing `fact_nature`; these were backfilled in-place.
- After this step, the taxonomy audit reports no remaining parsed metric keys with missing `fact_nature`.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_backfill_owners_earnings_fact_nature.py tests/unit/test_owners_earnings_facts.py tests/unit/test_value_line_field_taxonomy.py`
- `docker compose exec api python -m scripts.backfill_owners_earnings_fact_nature --dry-run`
- `docker compose exec api python -m scripts.backfill_owners_earnings_fact_nature`
- `docker compose exec api python -m scripts.audit_metric_taxonomy_coverage --limit 50`
- `docker compose exec api pytest -q`
- Results:
  - Targeted tests: `6 passed in 0.10s`
  - Dry run: `matched=39 updated=39 dry_run=True`
  - Backfill: `matched=39 updated=39 dry_run=False`
  - Audit summary after backfill:
    - `covered_metric_keys=59`
    - `uncovered_metric_keys=0`
    - `Missing fact_nature metric keys` section is empty
  - Full suite: `129 passed in 22.79s`
